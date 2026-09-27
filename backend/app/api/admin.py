from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select

from app.api.deps import DB, AdminUser
from app.models import CollectionItem, Product, ScrapeError, ScrapeRun
from app.services import pricing, scheduler
from app.services.settings import ScraperSettings, get_scraper_settings, save_scraper_settings

router = APIRouter(prefix="/admin/scraper", tags=["admin"])


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    trigger: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    total: int
    succeeded: int
    failed: int
    skipped: int
    message: str | None


class ErrorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int | None
    product_id: int | None
    product_title: str | None = None
    url: str | None
    http_status: int | None
    kind: str
    message: str
    snapshot_path: str | None
    created_at: datetime


class ScraperStatus(BaseModel):
    settings: ScraperSettings
    running: bool
    current_run_id: int | None
    current_item: str | None
    next_run_at: datetime | None
    linked_products: int
    tracked_products: int
    unlinked_products: int
    runs: list[RunOut]


@router.get("", response_model=ScraperStatus)
def scraper_status(db: DB, _: AdminUser):
    active = pricing.current_run()
    in_use = select(CollectionItem.product_id).distinct()
    tracked = db.scalar(
        select(func.count()).where(Product.id.in_(in_use), Product.pricecharting_url.is_not(None))
    )
    unlinked = db.scalar(
        select(func.count()).where(Product.id.in_(in_use), Product.pricecharting_url.is_(None))
    )
    return ScraperStatus(
        settings=get_scraper_settings(db),
        running=active is not None,
        current_run_id=active.run_id if active else None,
        current_item=active.current if active else None,
        next_run_at=scheduler.next_run_time(),
        linked_products=db.scalar(select(func.count()).where(Product.pricecharting_url.is_not(None))) or 0,
        tracked_products=tracked or 0,
        unlinked_products=unlinked or 0,
        runs=db.scalars(select(ScrapeRun).order_by(ScrapeRun.id.desc()).limit(20)).all(),
    )


@router.put("/settings", response_model=ScraperSettings)
def update_settings(body: ScraperSettings, db: DB, _: AdminUser):
    save_scraper_settings(db, body)
    pricing.configure_limiter(body)
    scheduler.apply(body)
    return body


class RunRequest(BaseModel):
    force: bool = False


@router.post("/run", status_code=202)
def start_run(body: RunRequest, _: AdminUser):
    if pricing.current_run():
        raise HTTPException(status.HTTP_409_CONFLICT, "A price update is already running")
    scheduler.run_now(force=body.force)
    return {"started": True}


@router.post("/cancel", status_code=202)
def cancel(_: AdminUser):
    if not pricing.cancel_run():
        raise HTTPException(status.HTTP_409_CONFLICT, "No price update is running")
    return {"cancelling": True}


@router.get("/errors", response_model=list[ErrorOut])
def errors(db: DB, _: AdminUser, limit: int = Query(50, le=500), run_id: int | None = None):
    stmt = (
        select(ScrapeError, Product.title)
        .outerjoin(Product, Product.id == ScrapeError.product_id)
        .order_by(ScrapeError.id.desc())
        .limit(limit)
    )
    if run_id:
        stmt = stmt.where(ScrapeError.run_id == run_id)
    out = []
    for err, title in db.execute(stmt).all():
        item = ErrorOut.model_validate(err)
        item.product_title = title
        out.append(item)
    return out
