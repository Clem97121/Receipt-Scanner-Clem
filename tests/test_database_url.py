from sqlalchemy.engine import make_url

from db.database import normalize_database_url

NEON_DIRECT = (
    "postgresql://owner:p%40ss@ep-cool-name-123456.eu-central-1.aws.neon.tech/receipts"
    "?sslmode=require&channel_binding=require"
)
NEON_POOLED = NEON_DIRECT.replace("ep-cool-name-123456.", "ep-cool-name-123456-pooler.")


def test_neon_url_gets_asyncpg_driver_and_ssl():
    url, connect_args = normalize_database_url(NEON_DIRECT)
    parsed = make_url(url)
    assert parsed.drivername == "postgresql+asyncpg"
    assert parsed.query == {"ssl": "require"}  # sslmode / channel_binding are libpq-only
    assert parsed.password == "p@ss"  # URL-encoded password survives
    assert connect_args == {}


def test_neon_pooler_disables_prepared_statement_caching():
    url, connect_args = normalize_database_url(NEON_POOLED)
    assert make_url(url).query["prepared_statement_cache_size"] == "0"
    assert connect_args["statement_cache_size"] == 0
    name_func = connect_args["prepared_statement_name_func"]
    assert name_func() != name_func()  # unique names avoid collisions behind PgBouncer


def test_existing_asyncpg_url_is_kept():
    url = "postgresql+asyncpg://u:p@db-host:5432/receipts"
    assert normalize_database_url(url) == (url, {})


def test_sslmode_disable_does_not_force_ssl():
    url, _ = normalize_database_url("postgres://u:p@localhost/db?sslmode=disable")
    assert make_url(url).query == {}


def test_sqlite_is_untouched():
    url = "sqlite+aiosqlite:///tmp/test.db"
    assert normalize_database_url(url) == (url, {})
