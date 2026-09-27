"""Opt-in, read-only collection sharing between signed-in users of this instance.

Notes and storage location are never shared. Purchase/sold/target prices and dates are
shared only when the owner also opts in to `share_paid`.
"""

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.collection import build_facets, query_items
from app.api.deps import DB, CurrentUser
from app.models import User
from app.schemas.collection import Facets, ItemOut
from app.services import analytics
from app.services.filters import Filters, ItemFilters

router = APIRouter(tags=["sharing"])

ALWAYS_PRIVATE = {"notes": None, "location": None}
PAID_FIELDS = {
    "purchase_price": None,
    "purchase_date": None,
    "sold_price": None,
    "sold_date": None,
    "target_price": None,
}


class SharingSettings(BaseModel):
    share_collection: bool = False
    share_paid: bool = False


class Sharer(BaseModel):
    id: int
    username: str
    items: int
    total_value: float
    shows_paid: bool


class SharedPage(BaseModel):
    owner: str
    shows_paid: bool
    items: list[ItemOut]
    total: int


@router.get("/auth/sharing", response_model=SharingSettings)
def get_sharing(user: CurrentUser):
    return SharingSettings(share_collection=user.share_collection, share_paid=user.share_paid)


@router.put("/auth/sharing", response_model=SharingSettings)
def update_sharing(body: SharingSettings, user: CurrentUser, db: DB):
    user.share_collection = body.share_collection
    user.share_paid = body.share_collection and body.share_paid
    db.commit()
    return SharingSettings(share_collection=user.share_collection, share_paid=user.share_paid)


def _owner(db: DB, owner_id: int, viewer: User) -> User:
    owner = db.get(User, owner_id)
    # Same response whether the user doesn't exist or just isn't sharing.
    if not owner or not owner.is_active or not owner.share_collection or owner.id == viewer.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No shared collection here")
    return owner


def _redact(item, owner: User) -> ItemOut:
    out = ItemOut.model_validate(item)
    hidden = ALWAYS_PRIVATE | ({} if owner.share_paid else PAID_FIELDS)
    return out.model_copy(update=hidden)


@router.get("/shared", response_model=list[Sharer])
def list_sharers(db: DB, viewer: CurrentUser):
    owners = db.scalars(
        select(User)
        .where(User.share_collection, User.is_active, User.id != viewer.id)
        .order_by(User.username)
    ).all()
    today = datetime.now(UTC).date()
    out = []
    for owner in owners:
        o = analytics.overview(analytics.load_holdings(db, owner.id, ItemFilters.none()), today)
        out.append(
            Sharer(
                id=owner.id,
                username=owner.username,
                items=o["quantity"],
                total_value=o["total_value"],
                shows_paid=owner.share_paid,
            )
        )
    return out


@router.get("/shared/{owner_id}/collection", response_model=SharedPage)
def shared_collection(
    owner_id: int,
    db: DB,
    viewer: CurrentUser,
    filters: Filters,
    sort: str = "title",
    order: Literal["asc", "desc"] = "asc",
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
):
    owner = _owner(db, owner_id, viewer)
    if not owner.share_paid and sort in ("purchase_price", "purchase_date"):
        sort = "title"  # don't leak the order of hidden values
    filters.location = None
    filters.search_notes = False
    items, total = query_items(db, owner.id, filters, sort, order, offset, limit)
    return SharedPage(
        owner=owner.username,
        shows_paid=owner.share_paid,
        items=[_redact(i, owner) for i in items],
        total=total,
    )


@router.get("/shared/{owner_id}/facets", response_model=Facets)
def shared_facets(owner_id: int, db: DB, viewer: CurrentUser):
    owner = _owner(db, owner_id, viewer)
    return build_facets(db, owner.id).model_copy(update={"locations": []})


@router.get("/shared/{owner_id}/summary")
def shared_summary(owner_id: int, db: DB, viewer: CurrentUser):
    owner = _owner(db, owner_id, viewer)
    o = analytics.overview(
        analytics.load_holdings(db, owner.id, ItemFilters.none()), datetime.now(UTC).date()
    )
    summary = {
        "owner": owner.username,
        "total_value": o["total_value"],
        "quantity": o["quantity"],
        "unpriced": o["unpriced"],
    }
    if owner.share_paid:
        summary["cost_basis"] = o["cost_basis"]
    return summary
