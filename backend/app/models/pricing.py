from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import JSON, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

Money = Numeric(12, 2)


class PriceSnapshot(Base):
    """One row per product per day. Append-only history."""

    __tablename__ = "price_snapshots"
    __table_args__ = (UniqueConstraint("product_id", "captured_on", name="uq_snapshot_product_day"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    captured_on: Mapped[date] = mapped_column(index=True)
    loose: Mapped[Decimal | None] = mapped_column(Money)
    cib: Mapped[Decimal | None] = mapped_column(Money)
    new: Mapped[Decimal | None] = mapped_column(Money)
    graded: Mapped[Decimal | None] = mapped_column(Money)
    box_only: Mapped[Decimal | None] = mapped_column(Money)
    manual_only: Mapped[Decimal | None] = mapped_column(Money)
    # "scrape" = read from the live page; "history" = backfilled from the site's chart data.
    source: Mapped[str] = mapped_column(String(16), default="scrape")
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


class ScrapeRun(Base):
    __tablename__ = "scrape_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    trigger: Mapped[str] = mapped_column(String(16))  # schedule | manual
    status: Mapped[str] = mapped_column(String(16), default="running")
    started_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    finished_at: Mapped[datetime | None]
    total: Mapped[int] = mapped_column(default=0)
    succeeded: Mapped[int] = mapped_column(default=0)
    failed: Mapped[int] = mapped_column(default=0)
    skipped: Mapped[int] = mapped_column(default=0)
    message: Mapped[str | None] = mapped_column(Text)


class ScrapeError(Base):
    __tablename__ = "scrape_errors"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("scrape_runs.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    url: Mapped[str | None] = mapped_column(String(512))
    http_status: Mapped[int | None]
    kind: Mapped[str] = mapped_column(String(16))  # http | blocked | parse | network
    message: Mapped[str] = mapped_column(Text)
    snapshot_path: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC), index=True)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[object] = mapped_column(JSON)


class NotificationLog(Base):
    """Sent alerts, so the same price change is never announced twice."""

    __tablename__ = "notification_log"
    __table_args__ = (UniqueConstraint("item_id", "kind", "captured_on", name="uq_notification_once"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("collection_items.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(16))  # move | wishlist
    captured_on: Mapped[date]
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
