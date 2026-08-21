from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables or a local .env file."""

    database_url: str = "sqlite:///data/horse_racing.sqlite3"
    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="HORSE_RACING_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
