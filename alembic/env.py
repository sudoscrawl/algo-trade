"""Alembic async migration environment — uses asyncio.run + connection.run_sync."""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

# Register all models with Base.metadata before autogenerate inspects it.
import app.data.models  # noqa: F401
from alembic import context
from app.config import config as settings
from app.data.engine import Base

alembic_cfg = context.config

if alembic_cfg.config_file_name is not None:
    fileConfig(alembic_cfg.config_file_name)

# Inject the URL from pydantic settings (escaping % for ConfigParser).
alembic_cfg.set_main_option(
    "sqlalchemy.url",
    settings.db_url.replace("%", "%%"),
)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations without a live DB connection (generates SQL script)."""
    context.configure(
        url=settings.db_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        alembic_cfg.get_section(alembic_cfg.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
