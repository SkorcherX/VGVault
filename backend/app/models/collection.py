from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import JSON, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.catalog import Product
from app.models.enums import Condition, ItemStatus

Money = Numeric(12, 2)


class CollectionItem(Base):
    __tablename__ = "collection_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default=ItemStatus.owned, index=True)
    condition: Mapped[str] = mapped_column(String(16), default=Condition.loose)
    has_item: Mapped[bool] = mapped_column(default=True)
    has_box: Mapped[bool] = mapped_column(default=False)
    has_manual: Mapped[bool] = mapped_column(default=False)
    has_inserts: Mapped[bool] = mapped_column(default=False)
    grade: Mapped[str | None] = mapped_column(String(32))
    quantity: Mapped[int] = mapped_column(default=1)
    purchase_price: Mapped[Decimal | None] = mapped_column(Money)
    purchase_date: Mapped[date | None]
    sold_price: Mapped[Decimal | None] = mapped_column(Money)
    sold_date: Mapped[date | None]
    target_price: Mapped[Decimal | None] = mapped_column(Money)
    location: Mapped[str | None] = mapped_column(String(128))
    acquired_from: Mapped[str | None] = mapped_column(String(64))  # e.g. Game Store, eBay
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    product: Mapped[Product] = relationship(lazy="joined")
