"""Scheduled SQLite backups into /config/backups, with retention."""

import logging
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import engine
from app.models import Setting

log = logging.getLogger(__name__)

KEY = "backup"
NAME_RE = re.compile(r"^vgvault-\d{8}-\d{6}\.db$")


class BackupSettings(BaseModel):
    enabled: bool = True
    cron: str = "30 2 * * *"  # daily 02:30
    keep: int = Field(14, ge=1, le=365)

    @field_validator("cron")
    @classmethod
    def _valid_cron(cls, v: str) -> str:
        from app.services.scheduler import cron_trigger

        try:
            cron_trigger(v)
        except ValueError as e:
            raise ValueError(f"Invalid cron expression: {e}") from None
        return v


def get_backup_settings(db: Session) -> BackupSettings:
    row = db.get(Setting, KEY)
    return BackupSettings(**(row.value if row and isinstance(row.value, dict) else {}))


def save_backup_settings(db: Session, settings: BackupSettings) -> None:
    row = db.get(Setting, KEY)
    if row:
        row.value = settings.model_dump()
    else:
        db.add(Setting(key=KEY, value=settings.model_dump()))
    db.commit()


def supported() -> bool:
    return engine.dialect.name == "sqlite"


def backup_dir() -> Path:
    path = get_settings().config_dir / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_backups() -> list[dict]:
    out = []
    for f in sorted(backup_dir().glob("vgvault-*.db"), reverse=True):
        if NAME_RE.match(f.name):
            stat = f.stat()
            out.append(
                {
                    "name": f.name,
                    "size": stat.st_size,
                    "created_at": datetime.fromtimestamp(stat.st_mtime, UTC),
                }
            )
    return out


def resolve(name: str) -> Path | None:
    if not NAME_RE.match(name):
        return None
    path = backup_dir() / name
    return path if path.is_file() else None


def create_backup(keep: int | None = None) -> Path:
    """Consistent online copy via SQLite's backup API (safe while the app is running)."""
    if not supported():
        raise RuntimeError("Built-in backups only support SQLite; back up Postgres with pg_dump")
    dest = backup_dir() / f"vgvault-{datetime.now(UTC):%Y%m%d-%H%M%S}.db"
    raw = engine.raw_connection()
    try:
        target = sqlite3.connect(dest)
        try:
            raw.driver_connection.backup(target)
        finally:
            target.close()
    finally:
        raw.close()
    log.info("Backup written: %s", dest)
    if keep:
        prune(keep)
    return dest


def prune(keep: int) -> int:
    removed = 0
    for b in list_backups()[keep:]:
        (backup_dir() / b["name"]).unlink(missing_ok=True)
        removed += 1
    return removed


def scheduled_backup() -> None:
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        keep = get_backup_settings(db).keep
    try:
        create_backup(keep)
    except Exception:
        log.exception("Scheduled backup failed")
