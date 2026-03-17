"""Health API endpoints: GET /health (JSON) and GET /health/fragment (HTML)."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database import get_session
from src.logging_config import get_logger
from src.services.gmail_credential_service import GmailCredentialService, mask_email
from src.services.health_service import get_health

logger = get_logger(__name__)

router = APIRouter(tags=["health"])
templates = Jinja2Templates(directory="src/templates")


async def _get_gmail_context(session: AsyncSession) -> dict:
    """Derive Gmail status context for health templates.

    Returns a dict with keys:
        gmail_oauth_configured: bool — True if client ID + secret are set in env
        gmail_status: str            — ConnectorStatus value or "unknown" on DB error
        gmail_account: str | None    — masked email or None
    """
    gmail_oauth_configured: bool = bool(
        settings.gmail_client_id and settings.gmail_client_secret
    )
    gmail_status: str = "unknown"
    gmail_account: str | None = None
    try:
        service = GmailCredentialService(session)
        status_enum = await service.get_connection_status()
        gmail_status = status_enum.value
        if gmail_status == "ok":
            try:
                credential = await service.get()
                if credential and credential.account_email:
                    gmail_account = mask_email(credential.account_email)
            except Exception:
                pass  # gmail_account stays None; gmail_status preserved
    except Exception:
        logger.warning("health_fragment_gmail_status_failed")
    return {
        "gmail_oauth_configured": gmail_oauth_configured,
        "gmail_status": gmail_status,
        "gmail_account": gmail_account,
    }


@router.get("/health")
async def health_json():
    """JSON health response for Docker/Portainer healthchecks and API consumers."""
    result = await get_health()
    return {
        "status": result.overall,
        "checks": {
            "db": result.db.value,
            "llm": result.llm.value,
            "mail": result.mail.value,
        },
    }


@router.get("/health/fragment", response_class=HTMLResponse)
async def health_fragment(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """HTML fragment for HTMX inline embedding (no full page wrapper)."""
    result = await get_health()
    gmail_ctx = await _get_gmail_context(session)
    return templates.TemplateResponse(
        request,
        "health_fragment.html",
        {"health": result, **gmail_ctx},
    )


@router.get("/health/page", response_class=HTMLResponse)
async def health_page(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Full health status page."""
    result = await get_health()
    gmail_ctx = await _get_gmail_context(session)
    return templates.TemplateResponse(
        request,
        "health.html",
        {"health": result, "llm_degraded": result.llm.value != "ok", **gmail_ctx},
    )
