from datetime import UTC, datetime

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.enums import Role


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default=Role.user)
    is_active: Mapped[bool] = mapped_column(default=True)
    # Bumped on password reset / disable to invalidate existing sessions.
    token_version: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    notify: Mapped[dict] = mapped_column(JSON, default=dict)
    # Opt-in: other signed-in users may view this collection (read-only).
    share_collection: Mapped[bool] = mapped_column(default=False)
    # ...and also see purchase/sold prices and dates.
    share_paid: Mapped[bool] = mapped_column(default=False)

    @property
    def is_admin(self) -> bool:
        return self.role == Role.admin
