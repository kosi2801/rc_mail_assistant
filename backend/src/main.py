"""FastAPI application factory with lifespan startup/shutdown (FR-008, FR-009)."""
import asyncio
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src import logging_config
from src.config import settings
from src.database import connect_with_retry
from src.logging_config import get_logger

logger = get_logger(__name__)


def _validate_required_env() -> None:
    """Exit immediately if required secrets are missing (FR-009, FR-014)."""
    missing = []
    if not settings.secret_key or settings.secret_key == "change_me_to_a_random_32_char_string":
        missing.append("SECRET_KEY")
    if not settings.postgres_password:
        missing.append("POSTGRES_PASSWORD")
    if missing:
        logger.error("startup_env_missing", missing=missing)
        sys.exit(1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging_config.configure()
    logger.info("startup_begin", version="0.1.0")

    _validate_required_env()
    logger.info("startup_env_ok")

    await connect_with_retry()
    logger.info("startup_db_ok")

    alembic_cfg = AlembicConfig("alembic.ini")
    await asyncio.to_thread(alembic_command.upgrade, alembic_cfg, "head")
    logger.info("startup_migrations_ok")

    yield

    logger.info("shutdown")


app = FastAPI(title="Repair Cafe Mail Assistant", lifespan=lifespan)

# Import and register routers after app creation to avoid circular imports
from alembic import command as alembic_command  # noqa: E402
from alembic.config import Config as AlembicConfig  # noqa: E402
from fastapi import Request  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402
from fastapi.responses import HTMLResponse  # noqa: E402
from fastapi.templating import Jinja2Templates  # noqa: E402
from starlette.exceptions import HTTPException as StarletteHTTPException  # noqa: E402

from src.api import health, config as config_router  # noqa: E402

app.include_router(health.router)
app.include_router(config_router.router)

_templates = Jinja2Templates(directory="src/templates")


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return _templates.TemplateResponse(
        "error.html",
        {"request": request, "status_code": exc.status_code, "detail": exc.detail},
        status_code=exc.status_code,
    )


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Root landing page — inline health summary (FR-013)."""
    return _templates.TemplateResponse("dashboard.html", {"request": request})
