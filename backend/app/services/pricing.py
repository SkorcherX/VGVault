"""Price fetching, snapshot storage and the scheduled refresh run."""

import logging
import threading
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import CollectionItem, Platform, PriceSnapshot, Product, ScrapeError, ScrapeRun
from app.models.enums import Category
from app.pricing.base import BlockedError, PriceProvider, PriceProviderError, PriceSet, ProductPage
from app.pricing.pricecharting import PriceChartingProvider, RateLimiter
from app.services.settings import ScraperSettings, get_scraper_settings

log = logging.getLogger(__name__)

# --- Provider singleton -------------------------------------------------------

_provider: PriceProvider | None = None
_limiter = RateLimiter(4.0, 10.0)


def get_provider() -> PriceProvider:
    global _provider
    if _provider is None:
        _provider = PriceChartingProvider(_limiter)
    return _provider


def set_provider(provider: PriceProvider | None) -> None:
    """Swap the provider (used by tests)."""
    global _provider
    _provider = provider


def configure_limiter(settings: ScraperSettings) -> None:
    _limiter.min_delay = settings.min_delay
    _limiter.max_delay = settings.max_delay


# --- Snapshots ----------------------------------------------------------------


def _upsert_snapshot(db: Session, product_id: int, day: date, prices: PriceSet, source: str) -> None:
    snap = db.scalar(
        select(PriceSnapshot).where(PriceSnapshot.product_id == product_id, PriceSnapshot.captured_on == day)
    )
    if snap is None:
        db.add(PriceSnapshot(product_id=product_id, captured_on=day, source=source, **prices.as_dict()))
    elif source == "scrape" or snap.source == "history":
        for key, value in prices.as_dict().items():
            setattr(snap, key, value)
        snap.source = source


def _backfill_history(db: Session, product_id: int, history: dict[date, PriceSet]) -> int:
    existing = set(
        db.scalars(select(PriceSnapshot.captured_on).where(PriceSnapshot.product_id == product_id))
    )
    added = 0
    for day, prices in history.items():
        if day not in existing and not prices.is_empty():
            db.add(
                PriceSnapshot(product_id=product_id, captured_on=day, source="history", **prices.as_dict())
            )
            added += 1
    return added


def _cache_image(product: Product, provider: PriceProvider) -> None:
    if not product.image_url or product.image_path:
        return
    try:
        images = get_settings().config_dir / "images"
        images.mkdir(parents=True, exist_ok=True)
        path = images / f"{product.id}.jpg"
        path.write_bytes(provider.download(product.image_url))
        product.image_path = str(path)
    except Exception as e:  # cover art is best-effort
        log.warning("Image download failed for product %s: %s", product.id, e)


def apply_page(
    db: Session, product: Product, page: ProductPage, *, backfill: bool, provider: PriceProvider
) -> None:
    """Store a fetched page's prices (and metadata) against a product. Caller commits."""
    product.pricecharting_id = page.source_id
    product.pricecharting_url = page.url
    product.genre = product.genre or page.genre
    product.release_date = product.release_date or page.release_date
    product.image_url = page.image_url or product.image_url
    if backfill:
        _backfill_history(db, product.id, page.history)
    if not page.prices.is_empty():
        _upsert_snapshot(db, product.id, datetime.now(UTC).date(), page.prices, "scrape")
    product.last_priced_at = datetime.now(UTC).replace(tzinfo=None)
    db.flush()
    _cache_image(product, provider)


def record_error(
    db: Session, error: Exception, *, product: Product | None = None, run_id: int | None = None
) -> ScrapeError:
    kind = getattr(error, "kind", "http")
    snapshot_path = None
    html = getattr(error, "html", None)
    if html and kind == "parse":
        folder = get_settings().config_dir / "snapshots"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{product.id if product else 'x'}-{datetime.now(UTC):%Y%m%dT%H%M%S}.html"
        path.write_text(html, encoding="utf-8")
        snapshot_path = str(path)
    row = ScrapeError(
        run_id=run_id,
        product_id=product.id if product else None,
        url=product.pricecharting_url if product else None,
        http_status=getattr(error, "status", None),
        kind=kind,
        message=str(error)[:2000],
        snapshot_path=snapshot_path,
    )
    db.add(row)
    return row


def refresh_product(db: Session, product: Product) -> None:
    """Fetch and store current prices for one linked product. Raises PriceProviderError."""
    if not product.pricecharting_url:
        raise PriceProviderError("Product is not linked to PriceCharting")
    settings = get_scraper_settings(db)
    configure_limiter(settings)
    provider = get_provider()
    try:
        page = provider.fetch(product.pricecharting_url)
    except PriceProviderError as e:
        record_error(db, e, product=product)
        db.commit()
        raise
    apply_page(db, product, page, backfill=settings.backfill_history, provider=provider)
    db.commit()


def resolve_platform(db: Session, console_slug: str | None, fallback_id: int | None) -> Platform | None:
    if console_slug:
        platform = db.scalar(select(Platform).where(Platform.pricecharting_slug == console_slug).limit(1))
        if platform:
            return platform
    return db.get(Platform, fallback_id) if fallback_id else None


def import_product(db: Session, url: str, *, platform_id: int | None, category: Category | None) -> Product:
    """Create (or return existing) catalog product from a PriceCharting page, with prices."""
    settings = get_scraper_settings(db)
    configure_limiter(settings)
    provider = get_provider()
    page = provider.fetch(url)
    existing = db.scalar(select(Product).where(Product.pricecharting_id == page.source_id))
    if existing:
        return existing
    platform = resolve_platform(db, page.console_slug, platform_id)
    if platform is None:
        raise LookupError(
            f"No platform is mapped to PriceCharting console '{page.console_slug}'. "
            "Pick a platform, or ask an admin to set its PriceCharting slug."
        )
    product = Product(
        title=page.title,
        platform_id=platform.id,
        category=category or (Category.console if page.is_system else Category.game),
    )
    db.add(product)
    db.flush()
    apply_page(db, product, page, backfill=settings.backfill_history, provider=provider)
    db.commit()
    db.refresh(product)
    return product


# --- Scheduled / manual full run ---------------------------------------------


@dataclass
class RunState:
    run_id: int | None = None
    current: str | None = None
    cancel: threading.Event = field(default_factory=threading.Event)


_run_lock = threading.Lock()
_state = RunState()


def current_run() -> RunState | None:
    return _state if _run_lock.locked() else None


def cancel_run() -> bool:
    if not _run_lock.locked():
        return False
    _state.cancel.set()
    return True


def products_to_update(db: Session, settings: ScraperSettings, *, force: bool) -> list[Product]:
    """Linked products that are in at least one collection/wishlist, stalest first."""
    in_use = exists().where(CollectionItem.product_id == Product.id)
    stmt = select(Product).where(Product.pricecharting_url.is_not(None), in_use)
    if not force and settings.min_hours_between_updates:
        cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=settings.min_hours_between_updates)
        stmt = stmt.where((Product.last_priced_at.is_(None)) | (Product.last_priced_at < cutoff))
    stmt = stmt.order_by(Product.last_priced_at.is_not(None), Product.last_priced_at)
    return list(db.scalars(stmt).unique())


def mark_interrupted_runs(db: Session) -> None:
    """Runs left 'running' by a previous process (restart/crash) can never finish."""
    for run in db.scalars(select(ScrapeRun).where(ScrapeRun.status == "running")):
        run.status, run.message = "interrupted", "App restarted during run"
        run.finished_at = run.finished_at or datetime.now(UTC).replace(tzinfo=None)
    db.commit()


def run_price_update(trigger: str = "schedule", *, force: bool = False) -> int | None:
    """Refresh all in-use products. Returns the run id, or None if a run is already active."""
    if not _run_lock.acquire(blocking=False):
        log.info("Price update already running; skipping %s trigger", trigger)
        return None
    try:
        _state.cancel.clear()
        with SessionLocal() as db:
            return _do_run(db, trigger, force)
    finally:
        _state.run_id = None
        _state.current = None
        _run_lock.release()


def _do_run(db: Session, trigger: str, force: bool) -> int:
    settings = get_scraper_settings(db)
    configure_limiter(settings)
    provider = get_provider()
    products = products_to_update(db, settings, force=force)
    run = ScrapeRun(trigger=trigger, total=len(products))
    db.add(run)
    db.commit()
    _state.run_id = run.id
    log.info("Price update %d started (%s): %d products", run.id, trigger, len(products))

    consecutive_failures = 0
    for product in products:
        if _state.cancel.is_set():
            run.status, run.message = "cancelled", "Cancelled by admin"
            break
        _state.current = product.title
        try:
            page = provider.fetch(product.pricecharting_url)
            apply_page(db, product, page, backfill=settings.backfill_history, provider=provider)
            run.succeeded += 1
            consecutive_failures = 0
        except PriceProviderError as e:
            db.rollback()
            record_error(db, e, product=product, run_id=run.id)
            run.failed += 1
            consecutive_failures += 1
            if isinstance(e, BlockedError):
                run.status, run.message = "blocked", f"Blocked by site ({e}); stopping run"
                db.commit()
                break
            if consecutive_failures >= settings.max_consecutive_failures:
                run.status, run.message = (
                    "failed",
                    f"{consecutive_failures} consecutive failures; stopping run",
                )
                db.commit()
                break
        except Exception as e:  # unexpected bug: record and keep going
            log.exception("Unexpected error pricing product %s", product.id)
            db.rollback()
            record_error(db, e, product=product, run_id=run.id)
            run.failed += 1
        db.commit()

    if run.status == "running":
        run.status = "ok" if run.failed == 0 else "partial"
    run.skipped = run.total - run.succeeded - run.failed
    run.finished_at = datetime.now(UTC).replace(tzinfo=None)
    db.commit()
    log.info("Price update %d finished: %s", run.id, run.status)
    return run.id


def latest_prices(db: Session, product_ids: list[int]) -> dict[int, PriceSnapshot]:
    """Most recent snapshot per product."""
    if not product_ids:
        return {}
    newest = (
        select(PriceSnapshot.product_id, func.max(PriceSnapshot.captured_on).label("day"))
        .where(PriceSnapshot.product_id.in_(product_ids))
        .group_by(PriceSnapshot.product_id)
        .subquery()
    )
    rows = db.scalars(
        select(PriceSnapshot).join(
            newest,
            (PriceSnapshot.product_id == newest.c.product_id) & (PriceSnapshot.captured_on == newest.c.day),
        )
    )
    return {snap.product_id: snap for snap in rows}


def image_file(product: Product) -> Path | None:
    if product.image_path:
        path = Path(product.image_path)
        if path.is_file():
            return path
    return None
