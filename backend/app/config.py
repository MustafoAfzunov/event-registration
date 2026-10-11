from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, read from environment variables (see .env.example)."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    app_env: str = "development"
    database_url: str = "postgresql+psycopg://eventreg:eventreg@localhost:5432/eventreg"
    # Pool per process. Must cover concurrent requests that may all wait on one event lock.
    db_pool_size: int = 10
    db_max_overflow: int = 20
    # Seconds the health check waits for the database before reporting it unhealthy.
    health_db_timeout_seconds: float = 2.0

    # Organizer auth (DECISIONS D-011).
    organizer_password: str = Field(min_length=8)
    session_secret: str = Field(min_length=32)
    session_max_age_seconds: int = 12 * 3600
    cookie_secure: bool = False  # True behind HTTPS; local compose is plain HTTP

    # Used to build links in emails, e.g. the manage link /r/{token}.
    public_base_url: str = "http://localhost:8080"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # required fields come from env
