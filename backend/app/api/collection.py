import json
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import contains_eager

from app.api.deps import DB, CurrentUser
from app.models import CollectionItem, Platform, Product
from app.models.enums import Category, Condition, ItemStatus, MediaType
from app.schemas.collection import (
    BulkUpdate,
    Facets,
    ItemCreate,
    ItemOut,
    ItemPage,
    ItemUpdate,
    Summary,
)

router = APIRouter(prefix="/collection", tags=["collection"])

SORTS = {
    "title": Product.title,
    "platform": Platform.name,
    "brand": Platform.brand,
    "condition": CollectionItem.condition,
    "purchase_price": CollectionItem.purchase_price,
    "purchase_date": CollectionItem.purchase_date,
    "created_at": CollectionItem.created_at,
}


def _own_item(db: DB, user_id: int, item_id: int) -> CollectionItem:
    item = db.get(CollectionItem, item_id)
    if not item or item.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
    return item


def _check_product(db: DB, product_id: int | None) -> None:
    if product_id is not None and not db.get(Product, product_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown product")


@router.get("", response_model=ItemPage)
def list_items(
    db: DB,
    user: CurrentUser,
    q: str | None = None,
    status_: list[ItemStatus] = Query([], alias="status"),
    category: list[Category] = Query([]),
    platform_id: list[int] = Query([]),
    brand: list[str] = Query([]),
    era: list[str] = Query([]),
    media_type: list[MediaType] = Query([]),
    condition: list[Condition] = Query([]),
    region: list[str] = Query([]),
    handheld: bool | None = None,
    tag: str | None = None,
    location: str | None = None,
    sort: str = "title",
    order: Literal["asc", "desc"] = "asc",
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
):
    stmt = (
        select(CollectionItem)
        .join(CollectionItem.product)
        .join(Product.platform)
        .where(CollectionItem.user_id == user.id)
    )
    for values, column in [
        (status_, CollectionItem.status),
        (category, Product.category),
        (platform_id, Product.platform_id),
        (brand, Platform.brand),
        (era, Platform.era),
        (media_type, Platform.media_type),
        (condition, CollectionItem.condition),
    ]:
        if values:
            stmt = stmt.where(column.in_(values))
    if region:
        stmt = stmt.where(
            or_(
                Product.region.in_(region),
                Product.region.is_(None) & Platform.region.in_(region),
            )
        )
    if handheld is not None:
        stmt = stmt.where(Platform.handheld == handheld)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Product.title.ilike(like), CollectionItem.notes.ilike(like)))
    if tag:
        # Tags are a JSON list; match the serialized element in its text form.
        stmt = stmt.where(cast(CollectionItem.tags, String).like(f"%{json.dumps(tag)}%"))
    if location:
        stmt = stmt.where(CollectionItem.location == location)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    column = SORTS.get(sort, Product.title)
    ordered = column.desc().nulls_last() if order == "desc" else column.asc().nulls_last()
    stmt = (
        stmt.options(contains_eager(CollectionItem.product).contains_eager(Product.platform))
        .order_by(ordered, CollectionItem.id)
        .offset(offset)
        .limit(limit)
    )
    return ItemPage(items=db.scalars(stmt).unique().all(), total=total)


@router.get("/facets", response_model=Facets)
def facets(db: DB, user: CurrentUser):
    rows = db.execute(
        select(Platform, Product.region, CollectionItem.tags, CollectionItem.location)
        .join(Product, Product.platform_id == Platform.id)
        .join(CollectionItem, CollectionItem.product_id == Product.id)
        .where(CollectionItem.user_id == user.id)
    ).all()
    platforms = {p.id: p for p, *_ in rows}
    return Facets(
        brands=sorted({p.brand for p in platforms.values()}),
        eras=sorted({p.era for p in platforms.values() if p.era}),
        platforms=[{"id": p.id, "name": p.name} for p in sorted(platforms.values(), key=lambda p: p.name)],
        regions=sorted({r for _, r, _, _ in rows if r} | {p.region for p in platforms.values()}),
        tags=sorted({t for _, _, tags, _ in rows for t in (tags or [])}),
        locations=sorted({loc for *_, loc in rows if loc}),
    )


@router.get("/summary", response_model=Summary)
def summary(db: DB, user: CurrentUser):
    count, quantity, cost = db.execute(
        select(
            func.count(CollectionItem.id),
            func.coalesce(func.sum(CollectionItem.quantity), 0),
            func.coalesce(func.sum(CollectionItem.purchase_price * CollectionItem.quantity), 0),
        ).where(CollectionItem.user_id == user.id, CollectionItem.status == ItemStatus.owned)
    ).one()
    return Summary(items=count, quantity=int(quantity), cost_basis=float(cost))


@router.get("/{item_id}", response_model=ItemOut)
def get_item(item_id: int, db: DB, user: CurrentUser):
    return _own_item(db, user.id, item_id)


@router.post("", response_model=ItemOut, status_code=201)
def create_item(body: ItemCreate, db: DB, user: CurrentUser):
    _check_product(db, body.product_id)
    item = CollectionItem(user_id=user.id, **body.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.patch("/bulk", response_model=list[ItemOut])
def bulk_update(body: BulkUpdate, db: DB, user: CurrentUser):
    changes = body.changes.model_dump(exclude_unset=True)
    _check_product(db, changes.get("product_id"))
    items = (
        db.scalars(
            select(CollectionItem).where(CollectionItem.id.in_(body.ids), CollectionItem.user_id == user.id)
        )
        .unique()
        .all()
    )
    if len(items) != len(set(body.ids)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "One or more items not found")
    for item in items:
        for key, value in changes.items():
            setattr(item, key, value)
    db.commit()
    return items


@router.patch("/{item_id}", response_model=ItemOut)
def update_item(item_id: int, body: ItemUpdate, db: DB, user: CurrentUser):
    item = _own_item(db, user.id, item_id)
    changes = body.model_dump(exclude_unset=True)
    _check_product(db, changes.get("product_id"))
    for key, value in changes.items():
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{item_id}", status_code=204)
def delete_item(item_id: int, db: DB, user: CurrentUser):
    db.delete(_own_item(db, user.id, item_id))
    db.commit()
