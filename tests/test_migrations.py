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
    # Production was created by create_all() with the models of revision 0001 and has no alembic_version table
    from alembic import command

    command.upgrade(_alembic_config(database_url), BASELINE_REVISION)

    def make_legacy(connection):
        connection.execute(text("DROP TABLE alembic_version"))
        connection.execute(text("INSERT INTO users (telegram_id) VALUES (42)"))

    _run(database_url, make_legacy)

    run_migrations(database_url)

    assert _run(database_url, _current_revision) == ScriptDirectory.from_config(
        _alembic_config(database_url)
    ).get_current_head()
    assert _run(database_url, lambda c: c.execute(text("SELECT telegram_id FROM users")).scalars().all()) == [42]
    assert _run(database_url, _schema_diff) == []


def test_backfill_gives_undated_receipts_their_upload_date(database_url):
    from alembic import command

    command.upgrade(_alembic_config(database_url), "0001")

    def insert_undated(connection):
        connection.execute(text("INSERT INTO users (telegram_id) VALUES (1)"))
        connection.execute(text(
            "INSERT INTO receipts (user_id, date, total_amount, currency, blob_name, created_at) "
            "VALUES (1, NULL, 5, 'CZK', 'b', '2026-02-14 10:00:00')"
        ))

    _run(database_url, insert_undated)
    run_migrations(database_url)
    assert str(_run(database_url, lambda c: c.execute(text("SELECT date FROM receipts")).scalar_one())) == "2026-02-14"
