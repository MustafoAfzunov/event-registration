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

    # Live updates (SSE): comment sent this often so proxies keep idle streams open.
    sse_keepalive_seconds: float = 15.0

    # Used to build links in emails, e.g. the manage link /r/{token}.
    public_base_url: str = "http://localhost:8080"

    # --- Email delivery (worker) ---
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_timeout_seconds: float = 10.0
    mail_from: str = "Event Registration <no-reply@eventreg.example.com>"
    # Outbox dispatcher (ARCHITECTURE 4.5, DECISIONS D-007).
    outbox_poll_seconds: float = 1.0
    outbox_batch_size: int = Field(default=10, ge=1)
    # A claimed batch is leased this long; must exceed the worst-case time to send the batch.
    outbox_lease_seconds: float = 120.0
    outbox_max_attempts: int = Field(default=8, ge=1)
    outbox_backoff_base_seconds: float = 5.0
    outbox_backoff_max_seconds: float = 3600.0
    # Optional pause between two sends (SMTP provider rate limits). 0 = no pause.
    outbox_send_interval_seconds: float = 0.0
    # Touched on every dispatcher loop; the container healthcheck checks its age.
    # Container-local liveness marker with no content, so a predictable /tmp path is fine.
    worker_heartbeat_file: str = "/tmp/worker-heartbeat"  # noqa: S108


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # required fields come from env
