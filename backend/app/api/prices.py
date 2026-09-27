from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import DB, AdminUser, CurrentUser
from app.models import Platform, PriceSnapshot, Product
from app.models.enums import Category
from app.pricing.base import NotFoundError, PriceProviderError
from app.pricing.pricecharting import is_pricecharting_url
from app.schemas.catalog import ProductOut
from app.services import pricing
from app.services.settings import get_scraper_settings

router = APIRouter(tags=["prices"])


def _provider_error(e: PriceProviderError) -> HTTPException:
    if isinstance(e, NotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, "PriceCharting page not found")
    return HTTPException(status.HTTP_502_BAD_GATEWAY, f"PriceCharting request failed: {e}")


def _product(db: DB, product_id: int) -> Product:
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    return product


# --- Search & import ----------------------------------------------------------


class SearchHit(BaseModel):
    source_id: str
    title: str
    url: str
    console_name: str | None
    console_slug: str | None
    image_url: str | None
    loose: Decimal | None
    cib: Decimal | None
    new: Decimal | None
    platform_id: int | None  # our platform mapped from the console slug
    platform_match: bool  # matches the platform the user filtered on
    product_id: int | None  # already in our catalog


@router.get("/pricecharting/search", response_model=list[SearchHit])
def search(
    db: DB, _: CurrentUser, q: str = Query(min_length=2, max_length=200), platform_id: int | None = None
):
    try:
        results = pricing.get_provider().search(q)
    except PriceProviderError as e:
        raise _provider_error(e) from None

    slug_to_platform: dict[str, int] = {}
    for p in db.scalars(
        select(Platform).where(Platform.pricecharting_slug.is_not(None)).order_by(Platform.id)
    ):
        slug_to_platform.setdefault(p.pricecharting_slug, p.id)  # oldest platform wins if a console is shared
    known = dict(
        db.execute(
            select(Product.pricecharting_id, Product.id).where(
                Product.pricecharting_id.in_([r.source_id for r in results])
            )
        ).all()
    )
    hits = [
        SearchHit(
            source_id=r.source_id,
            title=r.title,
            url=r.url,
            console_name=r.console_name,
            console_slug=r.console_slug,
            image_url=r.image_url,
            loose=r.prices.loose,
            cib=r.prices.cib,
            new=r.prices.new,
            platform_id=slug_to_platform.get(r.console_slug),
            platform_match=platform_id is not None and slug_to_platform.get(r.console_slug) == platform_id,
            product_id=known.get(r.source_id),
        )
        for r in results
    ]
    hits.sort(key=lambda h: not h.platform_match)  # stable: keeps site relevance order otherwise
    return hits


class ImportRequest(BaseModel):
    url: str
    platform_id: int | None = None
    category: Category | None = None
    upc: str | None = Field(default=None, pattern=r"^\d{8,14}$")


@router.post("/products/import", response_model=ProductOut)
def import_product(body: ImportRequest, db: DB, _: CurrentUser):
    if not is_pricecharting_url(body.url):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Not a PriceCharting product URL")
    try:
        return pricing.import_product(
            db, body.url, platform_id=body.platform_id, category=body.category, upc=body.upc
        )
    except LookupError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from None
    except PriceProviderError as e:
        raise _provider_error(e) from None


# --- Link / refresh -----------------------------------------------------------


class LinkRequest(BaseModel):
    url: str


@router.post("/products/{product_id}/link", response_model=ProductOut)
def link_product(product_id: int, body: LinkRequest, db: DB, user: CurrentUser):
    product = _product(db, product_id)
    if product.pricecharting_url and not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only admins can re-link a product")
    if not is_pricecharting_url(body.url):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Not a PriceCharting product URL")
    try:
        page = pricing.get_provider().fetch(body.url)
    except PriceProviderError as e:
        raise _provider_error(e) from None
    other = db.scalar(
        select(Product).where(Product.pricecharting_id == page.source_id, Product.id != product.id)
    )
    if other:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Already linked to '{other.title}' (#{other.id})")
    if product.pricecharting_id != page.source_id:
        # Different product on the site: old history no longer applies.
        for snap in db.scalars(select(PriceSnapshot).where(PriceSnapshot.product_id == product.id)):
            db.delete(snap)
        product.image_path = None
        product.image_url = None
    settings = get_scraper_settings(db)
    pricing.apply_page(db, product, page, backfill=settings.backfill_history, provider=pricing.get_provider())
    db.commit()
    db.refresh(product)
    return product


@router.delete("/products/{product_id}/link", response_model=ProductOut)
def unlink_product(product_id: int, db: DB, _: AdminUser):
    product = _product(db, product_id)
    product.pricecharting_id = None
    product.pricecharting_url = None
    db.commit()
    db.refresh(product)
    return product


@router.post("/products/{product_id}/refresh", response_model=ProductOut)
def refresh(product_id: int, db: DB, user: CurrentUser):
    product = _product(db, product_id)
    if not product.pricecharting_url:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Product is not linked to PriceCharting")
    cooldown = get_scraper_settings(db).user_refresh_cooldown_minutes
    if not user.is_admin and product.last_priced_at and cooldown:
        ready_at = product.last_priced_at + timedelta(minutes=cooldown)
        if ready_at > datetime.now(UTC).replace(tzinfo=None):
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Prices were updated recently; try later")
    try:
        pricing.refresh_product(db, product)
    except PriceProviderError as e:
        raise _provider_error(e) from None
    db.refresh(product)
    return product


# --- Price history & images ---------------------------------------------------


class SnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    captured_on: date
    loose: Decimal | None
    cib: Decimal | None
    new: Decimal | None
    graded: Decimal | None
    box_only: Decimal | None
    manual_only: Decimal | None
    source: str


@router.get("/products/{product_id}/prices", response_model=list[SnapshotOut])
def price_history(product_id: int, db: DB, _: CurrentUser, since: date | None = None):
    _product(db, product_id)
    stmt = (
        select(PriceSnapshot)
        .where(PriceSnapshot.product_id == product_id)
        .order_by(PriceSnapshot.captured_on)
    )
    if since:
        stmt = stmt.where(PriceSnapshot.captured_on >= since)
    return db.scalars(stmt).all()


@router.get("/products/{product_id}/image", include_in_schema=False)
def product_image(product_id: int, db: DB, _: CurrentUser):
    path = pricing.image_file(_product(db, product_id))
    if path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No image")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})
