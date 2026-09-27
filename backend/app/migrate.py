from pathlib import Path

from alembic.config import Config

from alembic import command
from app.core.config import get_settings

BACKEND_DIR = Path(__file__).resolve().parent.parent


def alembic_config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", get_settings().db_url.replace("%", "%%"))
    return cfg


def run_migrations() -> None:
    command.upgrade(alembic_config(), "head")
