from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, read from environment variables (see .env.example)."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    app_env: str = "development"
    database_url: str = "postgresql+psycopg://eventreg:eventreg@localhost:5432/eventreg"
    # Seconds the health check waits for the database before reporting it unhealthy.
    health_db_timeout_seconds: float = 2.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
