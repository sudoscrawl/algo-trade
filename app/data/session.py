"""Async session context manager for use in services and writers."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from app.data.engine import sessionmaker


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession]:
    """Yield a transactional async session; commits on success, rolls back on error."""
    async with sessionmaker.begin() as session:
        yield session
