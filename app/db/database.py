import os
from uuid import uuid4

from dotenv import load_dotenv
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is not set")


def normalize_database_url(url: str) -> tuple[str, dict]:
    """Adapts a Postgres URL (e.g. copied from Neon) for SQLAlchemy + asyncpg; returns (url, connect_args).

    - postgresql:// and postgres:// get the asyncpg driver;
    - libpq's sslmode/channel_binding, which asyncpg rejects, become asyncpg's ssl option;
    - PgBouncer endpoints (Neon "-pooler" hosts) get prepared statement caching disabled,
      because transaction pooling breaks asyncpg's named prepared statements.
    Other URLs (e.g. SQLite in tests) are returned unchanged.
    """
    parsed = make_url(url)
    if parsed.drivername in ("postgresql", "postgres", "postgresql+psycopg2", "postgresql+psycopg"):
        parsed = parsed.set(drivername="postgresql+asyncpg")
    if parsed.drivername != "postgresql+asyncpg":
        return url, {}

    query = dict(parsed.query)
    sslmode = query.pop("sslmode", None)
    query.pop("channel_binding", None)
    if sslmode and sslmode != "disable" and "ssl" not in query:
        query["ssl"] = "require"

    connect_args = {}
    if "-pooler." in (parsed.host or ""):
        query["prepared_statement_cache_size"] = "0"
        connect_args = {
            "statement_cache_size": 0,
            "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4()}__",
        }

    return parsed.set(query=query).render_as_string(hide_password=False), connect_args


def make_engine(url: str) -> AsyncEngine:
    """Engine without a connection pool: on Lambda every invocation opens and closes its own connections."""
    normalized_url, connect_args = normalize_database_url(url)
    return create_async_engine(normalized_url, echo=False, poolclass=NullPool, connect_args=connect_args)


engine = make_engine(DATABASE_URL)

AsyncSessionLocal = async_sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False
)

class Base(DeclarativeBase):
    pass

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
