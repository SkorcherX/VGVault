"""App settings stored in the DB, editable by admins at runtime."""

from typing import Any

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.models import Setting


class ScraperSettings(BaseModel):
    enabled: bool = True
    cron: str = "0 3 * * 0"  # weekly, Sunday 03:00 (container TZ)
    min_delay: float = Field(4.0, ge=1)
    max_delay: float = Field(10.0, ge=1)
    max_consecutive_failures: int = Field(5, ge=1)
    # Skip products already priced within this many hours during a scheduled run.
    min_hours_between_updates: int = Field(20, ge=0)
    user_refresh_cooldown_minutes: int = Field(60, ge=0)
    backfill_history: bool = True

    @field_validator("cron")
    @classmethod
    def _valid_cron(cls, v: str) -> str:
        from app.services.scheduler import cron_trigger

        try:
            cron_trigger(v)
        except ValueError as e:
            raise ValueError(f"Invalid cron expression: {e}") from None
        return v

    @field_validator("max_delay")
    @classmethod
    def _delay_order(cls, v: float, info) -> float:
        if v < info.data.get("min_delay", 0):
            raise ValueError("max_delay must be >= min_delay")
        return v


KEY = "scraper"


def get_scraper_settings(db: Session) -> ScraperSettings:
    row = db.get(Setting, KEY)
    return ScraperSettings(**(row.value if row and isinstance(row.value, dict) else {}))


def save_scraper_settings(db: Session, settings: ScraperSettings) -> None:
    value: dict[str, Any] = settings.model_dump()
    row = db.get(Setting, KEY)
    if row:
        row.value = value
    else:
        db.add(Setting(key=KEY, value=value))
    db.commit()
