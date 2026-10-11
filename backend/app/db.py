from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def make_engine(database_url: str) -> AsyncEngine:
    # pool_pre_ping: survive Postgres restarts without surfacing stale-connection errors.
    return create_async_engine(database_url, pool_pre_ping=True)
