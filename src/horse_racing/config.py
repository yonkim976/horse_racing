from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables or a local .env file."""

    database_url: str = "sqlite:///data/horse_racing.sqlite3"
    log_level: str = "INFO"
    data_go_kr_service_key: SecretStr | None = None
    raw_data_dir: Path = Path("data/raw")
    kra_api_base_url: str = "https://apis.data.go.kr/B551015"
    http_timeout_seconds: float = 30.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="HORSE_RACING_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
