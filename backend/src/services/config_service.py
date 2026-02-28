"""CRUD service for non-sensitive config persisted in the settings table."""
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.logging_config import get_logger
from src.models.settings import KNOWN_KEYS, Setting

logger = get_logger(__name__)

ConfigDict = dict[str, str | None]


async def get_all(session: AsyncSession) -> ConfigDict:
    rows = (await session.execute(select(Setting))).scalars().all()
    result: ConfigDict = {k: None for k in KNOWN_KEYS}
    for row in rows:
        if row.key in KNOWN_KEYS:
            result[row.key] = row.value
    return result


async def upsert(session: AsyncSession, updates: dict[str, str]) -> ConfigDict:
    """Upsert provided keys; returns full config after save."""
    for key, value in updates.items():
        stmt = (
            pg_insert(Setting)
            .values(key=key, value=value)
            .on_conflict_do_update(index_elements=["key"], set_={"value": value})
        )
        await session.execute(stmt)
        logger.info("config_updated", key=key)
    await session.commit()
    return await get_all(session)
