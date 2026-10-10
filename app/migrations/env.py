import asyncio
import os

from alembic import context

from db.database import Base, make_engine, normalize_database_url
import db.models  # noqa: F401  (registers the models on Base.metadata)

config = context.config
target_metadata = Base.metadata


def get_database_url() -> str:
    """Prefers a URL passed in by db/migrations.py, falls back to the DATABASE_URL environment variable."""
    url = config.get_main_option("sqlalchemy.url") or os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL environment variable is not set")
    return url


def run_migrations_offline() -> None:
    """Generates SQL without connecting to the database (alembic upgrade --sql)."""
    context.configure(
        url=normalize_database_url(get_database_url())[0],
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # Batch mode lets ALTER-style migrations also run on SQLite (used in tests)
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Applies migrations over an async connection (asyncpg in production)."""
    engine = make_engine(get_database_url())
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
