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

    # Wire mail adapter (T013)
    from google.auth.exceptions import RefreshError  # noqa: PLC0415
    from src.adapters.gmail_adapter import GmailAdapter  # noqa: PLC0415
    from src.services.mail_service import MailCredentialsError, NullMailAdapter, run_sync  # noqa: PLC0415

    try:
        app.state.mail_adapter = GmailAdapter()
        logger.info("startup_mail_adapter_ok")
    except (RefreshError, MailCredentialsError) as exc:
        logger.warning("startup_mail_adapter_failed", error=str(exc))
        app.state.mail_adapter = NullMailAdapter()

    # Wire scheduler (T022)
    from apscheduler.schedulers.asyncio import AsyncIOScheduler  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415
    from src.models.settings import Setting  # noqa: PLC0415
    from src.services import scheduler_service  # noqa: PLC0415
    from src.database import AsyncSessionLocal  # noqa: PLC0415

    scheduler = AsyncIOScheduler()

    # Read poll interval from settings table (default 0 = disabled)
    poll_minutes = 0
    try:
        async with AsyncSessionLocal() as _sess:
            result = await _sess.execute(
                select(Setting.value).where(Setting.key == "mail_poll_interval_minutes")
            )
            row = result.scalar_one_or_none()
            if row:
                poll_minutes = int(row)
    except Exception as exc:
        logger.warning("startup_scheduler_poll_interval_read_failed", error=str(exc))

    async def _sync_fn() -> None:
        """Bound coroutine passed to the scheduler."""
        async with AsyncSessionLocal() as _session:
            await run_sync(app.state.mail_adapter, _session, triggered_by="scheduler")

    await scheduler_service.start(scheduler, poll_minutes, _sync_fn)
    app.state.scheduler = scheduler
    logger.info("startup_scheduler_ok", poll_minutes=poll_minutes)

    yield

    await scheduler_service.shutdown(app.state.scheduler)
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
from src.api import mail as mail_router  # noqa: E402

app.include_router(health.router)
app.include_router(config_router.router)
app.include_router(mail_router.router)

_templates = Jinja2Templates(directory="src/templates")


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return _templates.TemplateResponse(
        request,
        "error.html",
        {"status_code": exc.status_code, "detail": exc.detail},
        status_code=exc.status_code,
    )


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Root landing page — inline health summary (FR-013)."""
    return _templates.TemplateResponse(request, "dashboard.html")
