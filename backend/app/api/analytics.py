from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Query

from app.api.deps import DB, CurrentUser
from app.services import analytics
from app.services.filters import Filters

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _today():
    return datetime.now(UTC).date()


@router.get("/overview")
def overview(db: DB, user: CurrentUser, filters: Filters, top: int = Query(10, ge=1, le=50)):
    holdings = analytics.load_holdings(db, user.id, filters)
    return {
        **analytics.overview(holdings, _today()),
        "top_items": analytics.top_items(holdings, top),
    }


@router.get("/timeseries")
def timeseries(db: DB, user: CurrentUser, filters: Filters, range: Literal["3m", "1y", "5y", "all"] = "1y"):
    holdings = analytics.load_holdings(db, user.id, filters)
    return analytics.timeseries(holdings, _today(), range)


@router.get("/breakdown")
def breakdown(
    db: DB,
    user: CurrentUser,
    filters: Filters,
    by: Literal[
        "brand", "platform", "era", "media_type", "category", "condition", "genre", "status", "region"
    ] = "brand",
):
    return analytics.breakdown(analytics.load_holdings(db, user.id, filters), by)


@router.get("/movers")
def movers(
    db: DB,
    user: CurrentUser,
    filters: Filters,
    days: int = Query(30, ge=1, le=3650),
    min_value: Decimal = Query(Decimal(5), ge=0),
    limit: int = Query(10, ge=1, le=100),
):
    holdings = analytics.load_holdings(db, user.id, filters)
    return analytics.movers(holdings, _today(), days, min_value, limit)
