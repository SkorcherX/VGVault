"""Background job: link a user's unlinked products to PriceCharting.

For each product in the user's collection that has no PriceCharting ID:
  * if it already has a PriceCharting URL (e.g. from an import), fetch it directly;
  * otherwise search by title and accept only an unambiguous match: exactly one result
    on the product's platform with the same title (or the same words in another order).
Anything else is left for the user to link by hand, and listed in the job status.
Runs one job at a time; shares the scraper's rate limiter.
"""

import logging
import re
import threading
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models import CollectionItem, Product
from app.pricing.base import BlockedError, NotFoundError, PriceProviderError
from app.services import pricing
from app.services.importer import norm
from app.services.settings import get_scraper_settings

log = logging.getLogger(__name__)


@dataclass
class AutoLinkState:
    running: bool = False
    user_id: int | None = None
    total: int = 0
    done: int = 0
    linked: int = 0
    current: str | None = None
    unmatched: list[dict] = field(default_factory=list)
    error: str | None = None
    cancel: threading.Event = field(default_factory=threading.Event)


_lock = threading.Lock()
_state = AutoLinkState()


def state_for(user_id: int) -> dict:
    s = _state
    mine = s.user_id == user_id
    return {
        "running": s.running and mine,
        "busy": s.running and not mine,  # someone else's job is using the scraper
        "total": s.total if mine else 0,
        "done": s.done if mine else 0,
        "linked": s.linked if mine else 0,
        "current": s.current if mine else None,
        "unmatched": s.unmatched if mine else [],
        "error": s.error if mine else None,
    }


def cancel(user_id: int) -> bool:
    if _state.running and _state.user_id == user_id:
        _state.cancel.set()
        return True
    return False


def unlinked_products(db: Session, user_id: int) -> list[Product]:
    return list(
        db.scalars(
            select(Product)
            .join(CollectionItem, CollectionItem.product_id == Product.id)
            .where(CollectionItem.user_id == user_id, Product.pricecharting_id.is_(None))
            .distinct()
            .order_by(Product.title)
        ).unique()
    )


def start(user_id: int) -> bool:
    """Start a job in a background thread. False if one is already running."""
    if not _lock.acquire(blocking=False):
        return False
    s = _state
    s.running, s.user_id = True, user_id
    s.total = s.done = s.linked = 0
    s.current, s.error = None, None
    s.unmatched = []
    s.cancel.clear()
    threading.Thread(target=_run, args=(user_id,), daemon=True, name="autolink").start()
    return True


def _run(user_id: int) -> None:
    try:
        with SessionLocal() as db:
            _link_all(db, user_id)
    except Exception as e:
        log.exception("Auto-link failed")
        _state.error = str(e)
    finally:
        _state.running = False
        _state.current = None
        _lock.release()


def _link_all(db: Session, user_id: int) -> None:
    s = _state
    settings = get_scraper_settings(db)
    pricing.configure_limiter(settings)
    provider = pricing.get_provider()
    products = unlinked_products(db, user_id)
    s.total = len(products)
    for product in products:
        if s.cancel.is_set():
            s.error = "Cancelled"
            return
        s.current = product.title
        try:
            url = product.pricecharting_url or _find_match(provider, product)
            page = None
            if url is not None:
                try:
                    page = provider.fetch(url)
                except NotFoundError:
                    if not product.pricecharting_url:
                        raise
                    # A stored link (e.g. from an import) whose page has moved: search by title instead.
                    product.pricecharting_url = None
                    url = _find_match(provider, product)
                    page = provider.fetch(url) if url else None
            if page is None:
                s.unmatched.append(
                    {"product_id": product.id, "title": product.title, "platform": product.platform.name}
                )
            else:
                clash = db.scalar(
                    select(Product).where(
                        Product.pricecharting_id == page.source_id, Product.id != product.id
                    )
                )
                if clash:
                    s.unmatched.append(
                        {
                            "product_id": product.id,
                            "title": product.title,
                            "platform": product.platform.name,
                            "reason": f"same PriceCharting page as '{clash.title}'",
                        }
                    )
                    product.pricecharting_url = None
                else:
                    pricing.apply_page(
                        db, product, page, backfill=settings.backfill_history, provider=provider
                    )
                    s.linked += 1
                db.commit()
        except BlockedError as e:
            db.rollback()
            s.error = f"PriceCharting blocked requests ({e}); stopped"
            return
        except PriceProviderError as e:
            db.rollback()
            s.unmatched.append(
                {
                    "product_id": product.id,
                    "title": product.title,
                    "platform": product.platform.name,
                    "reason": str(e),
                }
            )
        s.done += 1


def _words(title: str) -> frozenset[str]:
    return frozenset(w for w in re.findall(r"[a-z0-9]+", title.lower().replace("'", "")) if w)


def _find_match(provider, product: Product) -> str | None:
    """Exact normalized title first; else same words in any order (e.g. "GoldenEye 007" vs
    "007 GoldenEye"). Either way, exactly one candidate on the product's platform."""
    slug = product.platform.pricecharting_slug
    if not slug:
        return None
    candidates = [r for r in provider.search(product.title) if r.console_slug == slug]
    for same in (
        lambda r: norm(r.title) == norm(product.title),
        lambda r: _words(r.title) == _words(product.title),
    ):
        hits = [r for r in candidates if same(r)]
        if len(hits) == 1:
            return hits[0].url
        if len(hits) > 1:
            return None  # ambiguous: leave it for the user
    return None
