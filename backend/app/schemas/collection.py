from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import Condition, ItemStatus
from app.schemas.catalog import ProductOut


class ItemFields(BaseModel):
    status: ItemStatus = ItemStatus.owned
    condition: Condition = Condition.loose
    has_item: bool = True
    has_box: bool = False
    has_manual: bool = False
    has_inserts: bool = False
    grade: str | None = None
    quantity: int = Field(default=1, ge=1)
    purchase_price: Decimal | None = Field(default=None, ge=0)
    purchase_date: date | None = None
    sold_price: Decimal | None = Field(default=None, ge=0)
    sold_date: date | None = None
    target_price: Decimal | None = Field(default=None, ge=0)
    location: str | None = None
    tags: list[str] = []
    notes: str | None = None


class ItemCreate(ItemFields):
    product_id: int


class ItemUpdate(BaseModel):
    """All optional; only provided fields are applied."""

    product_id: int | None = None
    status: ItemStatus | None = None
    condition: Condition | None = None
    has_item: bool | None = None
    has_box: bool | None = None
    has_manual: bool | None = None
    has_inserts: bool | None = None
    grade: str | None = None
    quantity: int | None = Field(default=None, ge=1)
    purchase_price: Decimal | None = Field(default=None, ge=0)
    purchase_date: date | None = None
    sold_price: Decimal | None = Field(default=None, ge=0)
    sold_date: date | None = None
    target_price: Decimal | None = Field(default=None, ge=0)
    location: str | None = None
    tags: list[str] | None = None
    notes: str | None = None


class BulkUpdate(BaseModel):
    ids: list[int] = Field(min_length=1)
    changes: ItemUpdate


class ItemOut(ItemFields):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product: ProductOut
    created_at: datetime
    updated_at: datetime


class ItemPage(BaseModel):
    items: list[ItemOut]
    total: int


class Facets(BaseModel):
    brands: list[str]
    eras: list[str]
    platforms: list[dict]
    regions: list[str]
    tags: list[str]
    locations: list[str]


class Summary(BaseModel):
    items: int
    quantity: int
    cost_basis: float
