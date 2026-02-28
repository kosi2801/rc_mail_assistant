"""Async database engine with startup retry (FR-008, FR-009, FR-012)."""
import sys
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import text
from tenacity import RetryError, retry, stop_after_attempt, wait_exponential

from src.config import settings
from src.logging_config import get_logger

logger = get_logger(__name__)

engine = create_async_engine(settings.database_url, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def connect_with_retry() -> None:
    """Attempt DB connection with exponential backoff. Exit on exhaustion (FR-009)."""
    attempts = settings.db_connect_attempts
    delay = settings.db_connect_delay_seconds

    @retry(
        wait=wait_exponential(multiplier=1, min=delay, max=10),
        stop=stop_after_attempt(attempts),
        reraise=False,
    )
    async def _attempt() -> None:
        attempt_num = _attempt.retry.statistics.get("attempt_number", 1)
        logger.info("db_connect_attempt", attempt=attempt_num, max_attempts=attempts)
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))

    try:
        await _attempt()
        logger.info("db_connect_success")
    except RetryError:
        logger.error(
            "db_connect_failed",
            attempts=attempts,
            hint="Check POSTGRES_PASSWORD and that the postgres container is healthy.",
        )
        sys.exit(1)
