import csv
import io
import json
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import case, func, select
from sqlalchemy.orm import aliased

from app.api.deps import DB, CurrentUser
from app.models import CollectionItem, Platform, PriceSnapshot, Product
from app.models.enums import ItemStatus
from app.pricing.base import CONDITION_FIELDS
from app.schemas.collection import (
    BulkUpdate,
    Facets,
    ItemCreate,
    ItemOut,
    ItemPage,
    ItemUpdate,
    Summary,
)
from app.services.filters import Filters, items_query
from app.services.valuation import attach_prices

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


def _join_latest_price(stmt):
    """Join each item's latest snapshot; return the stmt and a price-for-its-condition expression."""
    newest = (
        select(PriceSnapshot.product_id, func.max(PriceSnapshot.captured_on).label("day"))
        .group_by(PriceSnapshot.product_id)
        .subquery()
    )
    snap = aliased(PriceSnapshot)
    stmt = stmt.outerjoin(newest, newest.c.product_id == CollectionItem.product_id).outerjoin(
        snap, (snap.product_id == newest.c.product_id) & (snap.captured_on == newest.c.day)
    )
    price = case(*[(CollectionItem.condition == c, getattr(snap, c)) for c in CONDITION_FIELDS], else_=None)
    return stmt, price


def _check_product(db: DB, product_id: int | None) -> None:
    if product_id is not None and not db.get(Product, product_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown product")


@router.get("", response_model=ItemPage)
def list_items(
    db: DB,
    user: CurrentUser,
    filters: Filters,
    sort: str = "title",
    order: Literal["asc", "desc"] = "asc",
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
):
    stmt = items_query(user.id, filters)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    if sort in ("market_price", "value"):
        stmt, price = _join_latest_price(stmt)
        column = price if sort == "market_price" else price * CollectionItem.quantity
    else:
        column = SORTS.get(sort, Product.title)
    ordered = column.desc().nulls_last() if order == "desc" else column.asc().nulls_last()
    stmt = stmt.order_by(ordered, CollectionItem.id).offset(offset).limit(limit)
    return ItemPage(items=attach_prices(db, db.scalars(stmt).unique()), total=total)


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


EXPORT_FIELDS = [
    "title", "platform", "brand", "category", "region", "status", "condition", "quantity",
    "has_item", "has_box", "has_manual", "has_inserts", "grade",
    "purchase_price", "purchase_date", "sold_price", "sold_date", "target_price",
    "location", "tags", "notes", "market_price", "value", "priced_on",
    "pricecharting_id", "pricecharting_url", "upc",
]  # fmt: skip


def _export_row(item) -> dict:
    p = item.product
    return {
        "title": p.title,
        "platform": p.platform.name,
        "brand": p.platform.brand,
        "category": p.category,
        "region": p.region or p.platform.region,
        "status": item.status,
        "condition": item.condition,
        "quantity": item.quantity,
        "has_item": item.has_item,
        "has_box": item.has_box,
        "has_manual": item.has_manual,
        "has_inserts": item.has_inserts,
        "grade": item.grade,
        "purchase_price": item.purchase_price,
        "purchase_date": item.purchase_date,
        "sold_price": item.sold_price,
        "sold_date": item.sold_date,
        "target_price": item.target_price,
        "location": item.location,
        "tags": item.tags or [],
        "notes": item.notes,
        "market_price": item.market_price,
        "value": item.value,
        "priced_on": item.priced_on,
        "pricecharting_id": p.pricecharting_id,
        "pricecharting_url": p.pricecharting_url,
        "upc": p.upc,
    }


@router.get("/export")
def export(db: DB, user: CurrentUser, filters: Filters, format: Literal["csv", "json"] = "csv"):
    stmt = items_query(user.id, filters).order_by(Platform.name, Product.title, CollectionItem.id)
    rows = [_export_row(i) for i in attach_prices(db, db.scalars(stmt).unique())]
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    filename = f"vgvault-{user.username}-{stamp}.{format}"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    if format == "json":
        body = json.dumps(rows, default=str, indent=2)
        return Response(body, media_type="application/json", headers=headers)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=EXPORT_FIELDS)
    writer.writeheader()
    for row in rows:
        writer.writerow({**row, "tags": "; ".join(row["tags"])})
    # BOM so Excel opens UTF-8 correctly
    return Response("\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)


@router.get("/summary", response_model=Summary)
def summary(db: DB, user: CurrentUser):
    owned = attach_prices(
        db,
        db.scalars(
            select(CollectionItem).where(
                CollectionItem.user_id == user.id, CollectionItem.status == ItemStatus.owned
            )
        ).unique(),
    )
    return Summary(
        items=len(owned),
        quantity=sum(i.quantity for i in owned),
        cost_basis=float(sum((i.purchase_price or 0) * i.quantity for i in owned)),
        total_value=float(sum(i.value or 0 for i in owned)),
        unpriced=sum(1 for i in owned if i.value is None),
    )


@router.get("/{item_id}", response_model=ItemOut)
def get_item(item_id: int, db: DB, user: CurrentUser):
    return attach_prices(db, [_own_item(db, user.id, item_id)])[0]


@router.post("", response_model=ItemOut, status_code=201)
def create_item(body: ItemCreate, db: DB, user: CurrentUser):
    _check_product(db, body.product_id)
    item = CollectionItem(user_id=user.id, **body.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return attach_prices(db, [item])[0]


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
    return attach_prices(db, items)


@router.patch("/{item_id}", response_model=ItemOut)
def update_item(item_id: int, body: ItemUpdate, db: DB, user: CurrentUser):
    item = _own_item(db, user.id, item_id)
    changes = body.model_dump(exclude_unset=True)
    _check_product(db, changes.get("product_id"))
    for key, value in changes.items():
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return attach_prices(db, [item])[0]


@router.delete("/{item_id}", status_code=204)
def delete_item(item_id: int, db: DB, user: CurrentUser):
    db.delete(_own_item(db, user.id, item_id))
    db.commit()
