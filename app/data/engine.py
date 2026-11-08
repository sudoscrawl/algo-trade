"""Async SQLAlchemy engine, session factory, and declarative base."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import config


class Base(DeclarativeBase):
    pass


engine = create_async_engine(url=config.db_url, echo=False)

sessionmaker = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    class_=AsyncSession,
)
