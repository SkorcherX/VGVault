import secrets
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    config_dir: Path = Path("/config")
    database_url: str | None = None
    secret_key: str | None = None
    access_token_minutes: int = 60 * 24 * 14
    cookie_secure: bool = False
    allow_registration: bool = False

    @property
    def db_url(self) -> str:
        return self.database_url or f"sqlite:///{self.config_dir / 'vgvault.db'}"

    def resolved_secret_key(self) -> str:
        """Use SECRET_KEY if given, else persist a generated one in /config."""
        if self.secret_key:
            return self.secret_key
        path = self.config_dir / "secret.key"
        if path.exists():
            return path.read_text().strip()
        self.config_dir.mkdir(parents=True, exist_ok=True)
        key = secrets.token_urlsafe(48)
        path.write_text(key)
        return key


@lru_cache
def get_settings() -> Settings:
    return Settings()
