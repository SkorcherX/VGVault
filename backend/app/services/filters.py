"""Collection filters shared by the collection list and analytics endpoints."""

import json
from typing import Annotated, Literal

from fastapi import Depends, Query
from sqlalchemy import Select, String, case, cast, func, or_, select
from sqlalchemy.orm import contains_eager

from app.models import CollectionItem, Platform, Product
from app.models.enums import Category, Condition, ItemStatus, MediaType


def _rated(rating, present):
    return func.coalesce(case((present, rating), else_=None), 99)


# Overall condition: the lowest rating among the parts the item has (NULL if none are rated).
# SQLite's multi-argument min() is a scalar function.
overall_rating = func.nullif(
    func.min(
        _rated(CollectionItem.item_rating, CollectionItem.has_item),
        _rated(CollectionItem.box_rating, CollectionItem.has_box),
        _rated(CollectionItem.manual_rating, CollectionItem.has_manual),
    ),
    99,
)
RATING_BANDS = {"mint": (9, 10), "excellent": (7, 8), "good": (5, 6), "poor": (1, 4)}
RatingBand = Literal["mint", "excellent", "good", "poor", "unrated"]


class ItemFilters:
    def __init__(
        self,
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
        acquired_from: str | None = None,
        rating: list[RatingBand] = Query([]),
    ):
        self.q = q
        self.status = status_
        self.category = category
        self.platform_id = platform_id
        self.brand = brand
        self.era = era
        self.media_type = media_type
        self.condition = condition
        self.region = region
        self.handheld = handheld
        self.tag = tag
        self.location = location
        self.acquired_from = acquired_from
        self.rating = rating
        # Shared (read-only) views must not let viewers probe private notes via search.
        self.search_notes = True

    @classmethod
    def none(cls) -> "ItemFilters":
        """No filtering. (Calling cls() directly outside FastAPI would keep Query() markers.)"""
        return cls(None, [], [], [], [], [], [], [], [], None, None, None, None, [])

    def apply(self, stmt: Select) -> Select:
        """Apply to a query that already joins CollectionItem -> Product -> Platform."""
        for values, column in [
            (self.status, CollectionItem.status),
            (self.category, Product.category),
            (self.platform_id, Product.platform_id),
            (self.brand, Platform.brand),
            (self.era, Platform.era),
            (self.media_type, Platform.media_type),
            (self.condition, CollectionItem.condition),
        ]:
            if values:
                stmt = stmt.where(column.in_(values))
        if self.region:
            stmt = stmt.where(
                or_(
                    Product.region.in_(self.region),
                    Product.region.is_(None) & Platform.region.in_(self.region),
                )
            )
        if self.rating:
            stmt = stmt.where(
                or_(
                    *[
                        overall_rating.is_(None)
                        if band == "unrated"
                        else overall_rating.between(*RATING_BANDS[band])
                        for band in self.rating
                    ]
                )
            )
        if self.handheld is not None:
            stmt = stmt.where(Platform.handheld == self.handheld)
        if self.q:
            like = f"%{self.q}%"
            if self.search_notes:
                stmt = stmt.where(or_(Product.title.ilike(like), CollectionItem.notes.ilike(like)))
            else:
                stmt = stmt.where(Product.title.ilike(like))
        if self.tag:
            # Tags are a JSON list; match the serialized element in its text form.
            stmt = stmt.where(cast(CollectionItem.tags, String).like(f"%{json.dumps(self.tag)}%"))
        if self.location:
            stmt = stmt.where(CollectionItem.location == self.location)
        if self.acquired_from:
            stmt = stmt.where(CollectionItem.acquired_from == self.acquired_from)
        return stmt


Filters = Annotated[ItemFilters, Depends()]


def items_query(user_id: int, filters: ItemFilters) -> Select:
    """Filtered items for a user, with product and platform eagerly loaded."""
    stmt = (
        select(CollectionItem)
        .join(CollectionItem.product)
        .join(Product.platform)
        .where(CollectionItem.user_id == user_id)
        .options(contains_eager(CollectionItem.product).contains_eager(Product.platform))
    )
    return filters.apply(stmt)
