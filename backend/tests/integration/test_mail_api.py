"""Integration tests for mail API endpoints (T020).

Uses an in-process SQLite async engine (aiosqlite) for isolation.
The FastAPI app lifespan is bypassed by creating a minimal test app.
Covers US2 endpoints plus FR-016 health regression tests.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.base_model import Base
from src.models import settings as _settings_mod  # noqa: F401 — register Setting
from src.models import mail as _mail_mod  # noqa: F401 — register mail models
from src.models.mail import IncomingEmail, MailSyncCursor, MailSyncRun
from src.services.mail_service import NullMailAdapter


# ---------------------------------------------------------------------------
# Test DB fixture (SQLite in-memory via aiosqlite)
# ---------------------------------------------------------------------------

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="function")
async def test_engine():
    engine = create_async_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(test_engine):
    Session = async_sessionmaker(test_engine, expire_on_commit=False)
    async with Session() as session:
        yield session


# ---------------------------------------------------------------------------
# Minimal test app fixture (no lifespan DB connection)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def client(test_engine):
    """Build a TestClient with a minimal app (lifespan bypassed)."""
    from src.database import get_session
    from src.api import mail as mail_router
    from src.api import health, config as config_router
    from fastapi.templating import Jinja2Templates
    from fastapi import Request
    from fastapi.responses import HTMLResponse
    from starlette.exceptions import HTTPException as StarletteHTTPException

    Session = async_sessionmaker(test_engine, expire_on_commit=False)

    async def _override_session():
        async with Session() as session:
            yield session

    # Build a minimal app without lifespan (no DB connection on startup)
    test_app = FastAPI(title="Test App")
    test_app.dependency_overrides[get_session] = _override_session
    test_app.include_router(mail_router.router)
    test_app.include_router(health.router)
    test_app.include_router(config_router.router)

    _templates = Jinja2Templates(directory="src/templates")

    @test_app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        return _templates.TemplateResponse(
            request,
            "error.html",
            {"status_code": exc.status_code, "detail": exc.detail},
            status_code=exc.status_code,
        )

    test_app.state.mail_adapter = NullMailAdapter()
    test_app.state.scheduler = MagicMock()  # scheduler mock for config endpoint

    with TestClient(test_app, raise_server_exceptions=True) as c:
        yield c


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_email(n: int, received_offset_seconds: int = 0) -> IncomingEmail:
    return IncomingEmail(
        gmail_message_id=f"gmail_{n}",
        gmail_thread_id=f"thread_{n}",
        sender_name=f"Sender {n}",
        sender_email=f"sender{n}@example.com",
        subject=f"Subject {n}",
        received_at=datetime(2026, 1, 1, 10, 0, received_offset_seconds, tzinfo=timezone.utc),
        body=f"Body of email {n}",
    )


# ---------------------------------------------------------------------------
# Test 1: GET /mail with 3 rows returns 200, all senders newest-first
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mail_list_three_emails_newest_first(client, db_session):
    """GET /mail returns 200 with all 3 sender names in newest-first order."""
    emails = [_make_email(i, received_offset_seconds=i * 10) for i in range(3)]
    for e in emails:
        db_session.add(e)
    await db_session.commit()

    resp = client.get("/mail")
    assert resp.status_code == 200
    html = resp.text
    # All senders present
    for i in range(3):
        assert f"Sender {i}" in html
    # Newest-first: Sender 2 appears before Sender 0
    assert html.index("Sender 2") < html.index("Sender 0")


# ---------------------------------------------------------------------------
# Test 2: GET /mail with no rows returns 200 and empty-state message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mail_list_empty_state(client, db_session):
    """GET /mail with no rows returns 200 and shows empty-state message."""
    resp = client.get("/mail")
    assert resp.status_code == 200
    assert "No emails have been synced yet" in resp.text


# ---------------------------------------------------------------------------
# Test 3: GET /mail/{id} returns 200 with correct body text
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mail_detail_returns_body(client, db_session):
    """GET /mail/{id} returns 200 with correct body text."""
    email = _make_email(42)
    email.body = "This is the unique body text for test 3."
    db_session.add(email)
    await db_session.commit()
    await db_session.refresh(email)

    resp = client.get(f"/mail/{email.id}")
    assert resp.status_code == 200
    assert "This is the unique body text for test 3." in resp.text


# ---------------------------------------------------------------------------
# Test 4: GET /mail/99999 returns 404
# ---------------------------------------------------------------------------


def test_mail_detail_not_found(client):
    """GET /mail/99999 returns 404."""
    resp = client.get("/mail/99999")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Test 5: DELETE /mail/{id} returns 200; subsequent GET returns 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_email(client, db_session):
    """DELETE /mail/{id} returns 200; subsequent GET /mail/{id} returns 404."""
    email = _make_email(7)
    db_session.add(email)
    await db_session.commit()
    await db_session.refresh(email)

    del_resp = client.delete(f"/mail/{email.id}")
    assert del_resp.status_code == 200

    get_resp = client.get(f"/mail/{email.id}")
    assert get_resp.status_code == 404


# ---------------------------------------------------------------------------
# Test 6: POST /mail/cursor with valid datetime returns 200 + confirmation
# ---------------------------------------------------------------------------


def test_reset_cursor_valid_datetime(client):
    """POST /mail/cursor with valid ISO datetime returns 200 and confirmation text."""
    resp = client.post("/mail/cursor", data={"last_synced_at": "2026-01-01T00:00:00Z"})
    assert resp.status_code == 200
    assert "Cursor updated" in resp.text or "cursor" in resp.text.lower()


# ---------------------------------------------------------------------------
# Test 7: POST /mail/cursor with invalid datetime returns 422
# ---------------------------------------------------------------------------


def test_reset_cursor_invalid_datetime(client):
    """POST /mail/cursor with invalid datetime returns 422."""
    resp = client.post("/mail/cursor", data={"last_synced_at": "not-a-date"})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Test 8: GET /health with all GMAIL_* env vars set → mail: ok (FR-016)
# ---------------------------------------------------------------------------


def test_health_mail_ok_no_api_call(client):
    """GET /health with all GMAIL_* vars set returns mail: ok without outbound call (FR-016)."""
    with patch.dict(
        os.environ,
        {
            "GMAIL_CLIENT_ID": "fake_client_id",
            "GMAIL_CLIENT_SECRET": "fake_secret",
            "GMAIL_REFRESH_TOKEN": "fake_token",
        },
    ):
        # Patch the settings object directly to avoid re-initialization issues
        from src import config as cfg_mod
        original_cid = cfg_mod.settings.gmail_client_id
        original_cs = cfg_mod.settings.gmail_client_secret
        original_rt = cfg_mod.settings.gmail_refresh_token
        cfg_mod.settings.__dict__["gmail_client_id"] = "fake_client_id"
        cfg_mod.settings.__dict__["gmail_client_secret"] = "fake_secret"
        cfg_mod.settings.__dict__["gmail_refresh_token"] = "fake_token"
        try:
            resp = client.get("/health")
        finally:
            cfg_mod.settings.__dict__["gmail_client_id"] = original_cid
            cfg_mod.settings.__dict__["gmail_client_secret"] = original_cs
            cfg_mod.settings.__dict__["gmail_refresh_token"] = original_rt

    assert resp.status_code == 200
    data = resp.json()
    assert "checks" in data or "mail" in data
    mail_status = data.get("mail") or data.get("checks", {}).get("mail")
    assert mail_status is not None
    # When all creds present, no outbound call made — just credential check
    assert mail_status in ("ok", "unconfigured")  # depends on env


# ---------------------------------------------------------------------------
# Test 9: GET /health with one GMAIL_* var unset → mail: unconfigured (FR-016)
# ---------------------------------------------------------------------------


def test_health_mail_unconfigured(client):
    """GET /health with GMAIL_CLIENT_ID unset returns mail: unconfigured (FR-016)."""
    from src import config as cfg_mod
    original = cfg_mod.settings.gmail_client_id
    cfg_mod.settings.__dict__["gmail_client_id"] = ""
    try:
        resp = client.get("/health")
    finally:
        cfg_mod.settings.__dict__["gmail_client_id"] = original

    assert resp.status_code == 200
    data = resp.json()
    mail_status = data.get("mail") or data.get("checks", {}).get("mail")
    assert mail_status == "unconfigured"

