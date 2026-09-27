"""Collection filters shared by the collection list and analytics endpoints."""

import json
from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy import Select, String, cast, or_, select
from sqlalchemy.orm import contains_eager

from app.models import CollectionItem, Platform, Product
from app.models.enums import Category, Condition, ItemStatus, MediaType


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
        # Shared (read-only) views must not let viewers probe private notes via search.
        self.search_notes = True

    @classmethod
    def none(cls) -> "ItemFilters":
        """No filtering. (Calling cls() directly outside FastAPI would keep Query() markers.)"""
        return cls(None, [], [], [], [], [], [], [], [], None, None, None, None)

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
