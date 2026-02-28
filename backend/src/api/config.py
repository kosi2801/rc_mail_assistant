"""Config API: GET/POST /config + POST /config/test/{service} (contracts/health-and-config.md)."""
import asyncio

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database import engine, get_session
from src.logging_config import get_logger
from src.models.settings import KNOWN_KEYS
from src.services import config_service

logger = get_logger(__name__)
router = APIRouter(tags=["config"])
templates = Jinja2Templates(directory="src/templates")

TEST_TIMEOUT = 5.0  # seconds


@router.get("/config", response_class=HTMLResponse)
async def config_page(request: Request, session: AsyncSession = Depends(get_session)):
    config = await config_service.get_all(session)
    llm_degraded = not settings.ollama_base_url
    return templates.TemplateResponse(
        "config.html",
        {"request": request, "config": config, "llm_degraded": llm_degraded},
    )


@router.post("/config")
async def save_config(
    session: AsyncSession = Depends(get_session),
    llm_endpoint: str | None = Form(None),
    llm_model: str | None = Form(None),
    event_date: str | None = Form(None),
    event_location: str | None = Form(None),
    event_offerings: str | None = Form(None),
):
    # Empty strings from form inputs are treated as "no change"
    raw = {
        "llm_endpoint": llm_endpoint,
        "llm_model": llm_model,
        "event_date": event_date,
        "event_location": event_location,
        "event_offerings": event_offerings,
    }
    updates = {k: v for k, v in raw.items() if v}  # skip None and ""
    logger.info("config_save", keys=sorted(updates.keys()))
    return await config_service.upsert(session, updates)


_STATUS_STYLES = {
    "ok":              "color:#2e7d32;font-weight:600",  # green
    "unconfigured":    "color:#e65100",                  # amber
    "unreachable":     "color:#b71c1c;font-weight:600",  # red
    "model_not_found": "color:#e65100",                  # amber — Ollama up, model missing
}
_STATUS_ICONS = {"ok": "✓", "unconfigured": "—", "unreachable": "✗", "model_not_found": "—"}


def _test_html(status: str, detail: str) -> HTMLResponse:
    style = _STATUS_STYLES.get(status, "")
    icon = _STATUS_ICONS.get(status, "")
    html = f'<span style="{style}">{icon} {status}</span> <span style="color:#6c757d;font-size:0.8rem">{detail}</span>'
    return HTMLResponse(content=html)


@router.post("/config/test/{service}", response_class=HTMLResponse)
async def test_connection(service: str, session: AsyncSession = Depends(get_session)):
    if service not in ("db", "llm", "mail"):
        raise HTTPException(status_code=422, detail=f"Unknown service: {service}")

    if service == "db":
        try:
            async with asyncio.timeout(TEST_TIMEOUT):
                async with engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))
            logger.info("config_test_db", status="ok")
            return _test_html("ok", "Database connection successful")
        except Exception as exc:
            logger.warning("config_test_db", status="unreachable", error=str(exc))
            return _test_html("unreachable", str(exc))

    if service == "llm":
        if not settings.ollama_base_url:
            return _test_html("unconfigured", "OLLAMA_BASE_URL not set")
        try:
            async with asyncio.timeout(TEST_TIMEOUT):
                async with httpx.AsyncClient() as client:
                    resp = await client.get(f"{settings.ollama_base_url.rstrip('/')}/api/tags")
                    resp.raise_for_status()
                    installed = [m["name"] for m in resp.json().get("models", [])]
        except Exception as exc:
            logger.warning("config_test_llm", status="unreachable", error=str(exc))
            return _test_html("unreachable", str(exc))

        config = await config_service.get_all(session)
        model = (config.get("llm_model") or "").strip()
        if not model:
            logger.info("config_test_llm", status="ok", model="(none configured)")
            return _test_html("ok", f"Ollama reachable at {settings.ollama_base_url} — no model configured yet")

        # Ollama may store names as "llama3.2:latest"; match on prefix before ":"
        match = any(m == model or m.split(":")[0] == model.split(":")[0] for m in installed)
        if match:
            logger.info("config_test_llm", status="ok", model=model)
            return _test_html("ok", f"Model '{model}' is available at {settings.ollama_base_url}")
        else:
            available = ", ".join(installed) or "(none)"
            logger.warning("config_test_llm", status="model_not_found", model=model, installed=available)
            return _test_html("model_not_found", f"Ollama is reachable but model '{model}' is not installed. Run: ollama pull {model}")

    # mail
    creds = (settings.gmail_client_id, settings.gmail_client_secret, settings.gmail_refresh_token)
    if all(creds):
        logger.info("config_test_mail", status="ok")
        return _test_html("ok", "Gmail credentials are present")
    logger.info("config_test_mail", status="unconfigured")
    return _test_html("unconfigured", "One or more GMAIL_* env vars are missing")
