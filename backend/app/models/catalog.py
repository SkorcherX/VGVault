from datetime import UTC, date, datetime

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.enums import Category, MediaType


class Platform(Base):
    __tablename__ = "platforms"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    slug: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    brand: Mapped[str] = mapped_column(String(64), index=True)
    generation: Mapped[int | None]
    era: Mapped[str | None] = mapped_column(String(64))
    media_type: Mapped[str] = mapped_column(String(16), default=MediaType.cartridge)
    handheld: Mapped[bool] = mapped_column(default=False)
    region: Mapped[str] = mapped_column(String(16), default="NTSC-U")
    release_year: Mapped[int | None]
    pricecharting_slug: Mapped[str | None] = mapped_column(String(128))


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("pricecharting_id", name="uq_products_pricecharting_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255), index=True)
    platform_id: Mapped[int] = mapped_column(ForeignKey("platforms.id"), index=True)
    category: Mapped[str] = mapped_column(String(16), default=Category.game, index=True)
    region: Mapped[str | None] = mapped_column(String(16))
    genre: Mapped[str | None] = mapped_column(String(64))
    release_date: Mapped[date | None]
    upc: Mapped[str | None] = mapped_column(String(32), index=True)
    pricecharting_id: Mapped[str | None] = mapped_column(String(32))
    pricecharting_url: Mapped[str | None] = mapped_column(String(512))
    image_path: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))

    platform: Mapped[Platform] = relationship(lazy="joined")
