from datetime import datetime
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.clock import Clock
from app.config import Settings


def get_sessionmaker(request: Request) -> async_sessionmaker[AsyncSession]:
    sm: async_sessionmaker[AsyncSession] = request.app.state.sessionmaker
    return sm


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_now(request: Request) -> datetime:
    """One `now` per request, from the injectable clock (DECISIONS D-018)."""
    clock: Clock = request.app.state.clock
    return clock.now()


SessionMaker = Annotated[async_sessionmaker[AsyncSession], Depends(get_sessionmaker)]
AppSettings = Annotated[Settings, Depends(get_settings_dep)]
Now = Annotated[datetime, Depends(get_now)]
