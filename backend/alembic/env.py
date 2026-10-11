import os

from sqlalchemy import create_engine, pool

from alembic import context
from app.models import Base

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    # Callers (tests) may set sqlalchemy.url explicitly; otherwise use DATABASE_URL.
    # Read the env var directly so migrating needs no unrelated app settings (secrets).
    return config.get_main_option("sqlalchemy.url") or os.environ["DATABASE_URL"]


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # psycopg 3 works in sync mode with the same "postgresql+psycopg" URL the app uses.
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
