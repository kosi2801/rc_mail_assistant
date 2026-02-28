"""Health API endpoints: GET /health (JSON) and GET /health/fragment (HTML)."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from src.services.health_service import get_health

router = APIRouter(tags=["health"])
templates = Jinja2Templates(directory="src/templates")


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
async def health_fragment(request: Request):
    """HTML fragment for HTMX inline embedding (no full page wrapper)."""
    result = await get_health()
    return templates.TemplateResponse(
        "health_fragment.html",
        {"request": request, "health": result},
    )


@router.get("/health/page", response_class=HTMLResponse)
async def health_page(request: Request):
    """Full health status page."""
    result = await get_health()
    return templates.TemplateResponse(
        "health.html",
        {"request": request, "health": result, "llm_degraded": result.llm.value != "ok"},
    )
