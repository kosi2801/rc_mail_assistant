"""Health checks for DB, LLM, and mail credentials (FR-003, FR-004, FR-005)."""
import asyncio
from dataclasses import dataclass
from enum import Enum

from sqlalchemy import text

from src.config import settings
from src.database import engine
from src.logging_config import get_logger

logger = get_logger(__name__)

CHECK_TIMEOUT = 3.0  # seconds per individual check


class CheckStatus(str, Enum):
    OK = "ok"
    UNREACHABLE = "unreachable"
    UNCONFIGURED = "unconfigured"


@dataclass
class HealthResult:
    db: CheckStatus
    llm: CheckStatus
    mail: CheckStatus

    @property
    def overall(self) -> str:
        if all(v == CheckStatus.OK for v in (self.db, self.llm, self.mail)):
            return "ok"
        return "degraded"


async def _check_db() -> CheckStatus:
    try:
        async with asyncio.timeout(CHECK_TIMEOUT):
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        return CheckStatus.OK
    except Exception as exc:
        logger.warning("health_check_db_failed", error=str(exc))
        return CheckStatus.UNREACHABLE


async def _check_llm() -> CheckStatus:
    from src.services.llm_service import get_default_llm_adapter  # avoid circular import at module level
    return await get_default_llm_adapter().ping()


async def _check_mail() -> CheckStatus:
    """Credentials-presence check only — no Gmail API call (FR-002a)."""
    creds = (settings.gmail_client_id, settings.gmail_client_secret, settings.gmail_refresh_token)
    if all(creds):
        return CheckStatus.OK
    return CheckStatus.UNCONFIGURED


async def get_health() -> HealthResult:
    db_status, llm_status, mail_status = await asyncio.gather(
        _check_db(), _check_llm(), _check_mail()
    )
    result = HealthResult(db=db_status, llm=llm_status, mail=mail_status)
    logger.info("health_check_complete", status=result.overall, db=db_status, llm=llm_status, mail=mail_status)
    return result
