"""Alembic migrations must build exactly the schema described by the models.

These are sync tests because run_migrations() calls asyncio.run itself, like the bot does via to_thread.
"""
import asyncio

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from db.database import Base
from db.migrations import BASELINE_REVISION, _alembic_config, run_migrations


@pytest.fixture
def database_url(tmp_path):
    return "sqlite+aiosqlite:///" + str(tmp_path / "migrations.db").replace("\\", "/")


def _run(database_url: str, sync_fn):
    """Runs sync_fn(connection) against the database and returns its result."""
    async def runner():
        engine = create_async_engine(database_url, poolclass=NullPool)
        try:
            async with engine.begin() as connection:
                return await connection.run_sync(sync_fn)
        finally:
            await engine.dispose()
    return asyncio.run(runner())


def _schema_diff(connection):
    return compare_metadata(MigrationContext.configure(connection), Base.metadata)


def _current_revision(connection):
    return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def test_single_migration_head(database_url):
    heads = ScriptDirectory.from_config(_alembic_config(database_url)).get_heads()
    assert len(heads) == 1, f"multiple migration heads, merge them: {heads}"


def test_migrations_build_the_model_schema(database_url):
    run_migrations(database_url)
    assert _run(database_url, _schema_diff) == []


def test_running_migrations_twice_is_safe(database_url):
    run_migrations(database_url)
    run_migrations(database_url)
    head = ScriptDirectory.from_config(_alembic_config(database_url)).get_current_head()
    assert _run(database_url, _current_revision) == head


def test_legacy_create_all_database_is_stamped_and_keeps_data(database_url):
    def create_legacy_schema(connection):
        Base.metadata.create_all(connection)
        connection.execute(text("INSERT INTO users (telegram_id) VALUES (42)"))

    _run(database_url, create_legacy_schema)

    run_migrations(database_url)

    assert _run(database_url, _current_revision) in (
        BASELINE_REVISION,
        ScriptDirectory.from_config(_alembic_config(database_url)).get_current_head(),
    )
    assert _run(database_url, lambda c: c.execute(text("SELECT telegram_id FROM users")).scalars().all()) == [42]
    assert _run(database_url, _schema_diff) == []
