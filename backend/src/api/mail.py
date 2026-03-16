"""Mail API router — sync, status, list, detail, delete, cursor endpoints."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_session
from src.logging_config import get_logger
from src.models.mail import IncomingEmail, MailSyncCursor, MailSyncRun
from src.services.mail_service import (
    SyncAlreadyRunningError,
    is_sync_running,
    run_sync,
)

logger = get_logger(__name__)
router = APIRouter(tags=["mail"])
templates = Jinja2Templates(directory="src/templates")

# Sentinel passed to mail_sync_result.html when sync is already running
_IN_PROGRESS_SENTINEL = {
    "outcome": None,
    "new_count": 0,
    "skipped_count": 0,
    "error_message": None,
    "finished_at": None,
}


# ---------------------------------------------------------------------------
# Phase 3: User Story 1 — sync endpoints
# ---------------------------------------------------------------------------


@router.post("/mail/sync", response_class=HTMLResponse)
async def trigger_sync(request: Request, session: AsyncSession = Depends(get_session)):
    """Trigger a Gmail sync. Returns an HTMX fragment with the run outcome."""
    if is_sync_running():
        return templates.TemplateResponse(
            request,
            "mail_sync_result.html",
            {"run": _IN_PROGRESS_SENTINEL},
        )

    adapter = request.app.state.mail_adapter
    run = await run_sync(adapter, session, triggered_by="manual")
    return templates.TemplateResponse(
        request,
        "mail_sync_result.html",
        {"run": run},
    )


@router.get("/mail/sync/status", response_class=HTMLResponse)
async def sync_status(request: Request, session: AsyncSession = Depends(get_session)):
    """Return the sync status HTMX fragment (polled every 3 seconds by mail_list.html)."""
    result = await session.execute(
        select(MailSyncRun).order_by(desc(MailSyncRun.started_at)).limit(1)
    )
    last_run = result.scalar_one_or_none()
    return templates.TemplateResponse(
        request,
        "mail_sync_status.html",
        {"is_syncing": is_sync_running(), "last_run": last_run},
    )


# ---------------------------------------------------------------------------
# Phase 4: User Story 2 — browse/delete/cursor endpoints (added by T019)
# ---------------------------------------------------------------------------


@router.get("/mail", response_class=HTMLResponse)
async def mail_list(request: Request, session: AsyncSession = Depends(get_session)):
    """Render the mail list page (FR-011, FR-012, FR-013)."""
    emails_result = await session.execute(
        select(IncomingEmail).order_by(desc(IncomingEmail.received_at))
    )
    emails = emails_result.scalars().all()

    last_run_result = await session.execute(
        select(MailSyncRun).order_by(desc(MailSyncRun.started_at)).limit(1)
    )
    last_run = last_run_result.scalar_one_or_none()

    cursor_result = await session.execute(
        select(MailSyncCursor).where(MailSyncCursor.id == 1)
    )
    cursor = cursor_result.scalar_one_or_none()

    return templates.TemplateResponse(
        request,
        "mail_list.html",
        {
            "emails": emails,
            "last_run": last_run,
            "cursor": cursor,
        },
    )


@router.get("/mail/{email_id}", response_class=HTMLResponse)
async def mail_detail(
    email_id: int, request: Request, session: AsyncSession = Depends(get_session)
):
    """Render the email detail page (FR-012, FR-021)."""
    result = await session.execute(
        select(IncomingEmail).where(IncomingEmail.id == email_id)
    )
    email = result.scalar_one_or_none()
    if email is None:
        raise HTTPException(status_code=404, detail="Email not found")
    return templates.TemplateResponse(
        request,
        "mail_detail.html",
        {"email": email},
    )


@router.delete("/mail/{email_id}", response_class=HTMLResponse)
async def delete_email(
    email_id: int, session: AsyncSession = Depends(get_session)
):
    """Permanently delete an email (FR-020). Returns empty 200 for HTMX swap."""
    result = await session.execute(
        select(IncomingEmail).where(IncomingEmail.id == email_id)
    )
    email = result.scalar_one_or_none()
    if email is None:
        raise HTTPException(status_code=404, detail="Email not found")
    await session.delete(email)
    await session.commit()
    return HTMLResponse("")


@router.post("/mail/cursor", response_class=HTMLResponse)
async def reset_cursor(
    session: AsyncSession = Depends(get_session),
    last_synced_at: str = Form(""),
):
    """Upsert the MailSyncCursor singleton (FR-018)."""
    from sqlalchemy import select as sa_select

    new_ts: datetime | None = None
    if last_synced_at and last_synced_at.strip():
        try:
            raw = last_synced_at.strip()
            # Accept ISO 8601 with or without timezone
            if raw.endswith("Z"):
                raw = raw[:-1] + "+00:00"
            new_ts = datetime.fromisoformat(raw)
            if new_ts.tzinfo is None:
                new_ts = new_ts.replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(
                status_code=422, detail=f"Invalid datetime format: {last_synced_at!r}"
            )

    # ORM-level upsert (dialect-agnostic: works with PG and SQLite)
    result = await session.execute(
        sa_select(MailSyncCursor).where(MailSyncCursor.id == 1)
    )
    cursor = result.scalar_one_or_none()
    if cursor is None:
        cursor = MailSyncCursor(id=1, last_synced_at=new_ts, overlap_minutes=5)
        session.add(cursor)
    else:
        cursor.last_synced_at = new_ts
        cursor.updated_at = datetime.now(tz=timezone.utc)
    await session.commit()

    if new_ts is None:
        cursor_desc = "reset (full re-sync on next run)"
    else:
        cursor_desc = new_ts.strftime("%Y-%m-%d %H:%M UTC")

    html = (
        f'<div style="color:#2e7d32;padding:0.5rem 0">'
        f"✓ Cursor updated to: <strong>{cursor_desc}</strong>. "
        f"The next sync will fetch emails from this date forward."
        f"</div>"
    )
    return HTMLResponse(html)
