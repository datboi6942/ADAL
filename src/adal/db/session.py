import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from adal.config import settings

logger = structlog.get_logger(__name__)

_engine = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            settings.database_url,
            echo=False,
            future=True,
        )
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _sessionmaker


async def get_session() -> AsyncSession:
    async with get_sessionmaker()() as session:
        yield session


async def init_db():
    from adal.db.models import Base

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        result = await conn.execute(text("PRAGMA table_info(meta_diagnostics)"))
        existing_cols = {row[1] for row in result.fetchall()}
        migrations = [
            ("first_iteration", "INTEGER DEFAULT 0"),
            ("last_iteration", "INTEGER DEFAULT 0"),
            ("pattern_category", "VARCHAR(32) DEFAULT 'other'"),
        ]
        for col_name, col_def in migrations:
            if col_name not in existing_cols:
                await conn.execute(text(f"ALTER TABLE meta_diagnostics ADD COLUMN {col_name} {col_def}"))
                logger.info("db_migration", table="meta_diagnostics", column=col_name)
    logger.info("Database initialized", url=settings.database_url)
