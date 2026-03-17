"""Integration tests for health fragment Gmail status rows (feature 005).

Tests:
  TC-01: gmail_status="ok", masked email displayed
  TC-02: gmail_status="unconfigured" → "— Not Connected"
  TC-03: gmail_status="token_error"  → "⚠ Token Error"
  TC-04: DB down (get_connection_status raises) → "? Unknown", HTTP 200
  TC-05: gmail_oauth_configured=False → "— Not Configured"
  TC-06: gmail_oauth_configured=True  → "✓ Configured"
  TC-07: sentinel email → "(account unknown — please re-authorize)"
  TC-08: regression — Database + LLM / Ollama rows present, no 5xx
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.base_model import Base
from src.models import settings as _settings_mod  # noqa: F401 — register Setting
from src.models import mail as _mail_mod  # noqa: F401 — register mail models
from src.models import gmail_credential as _gc_mod  # noqa: F401 — register GmailCredential
from src.services.mail_service import ConnectorStatus

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


# ---------------------------------------------------------------------------
# DB / Session fixtures
# ---------------------------------------------------------------------------


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
# Minimal app factory (lifespan bypassed)
# ---------------------------------------------------------------------------


def _build_test_app(test_engine):
    """Build a minimal FastAPI app with health router and SQLite session override."""
    from src.database import get_session
    from src.api import health as health_router

    Session = async_sessionmaker(test_engine, expire_on_commit=False)

    async def _override_session():
        async with Session() as session:
            yield session

    test_app = FastAPI(title="Test Health App")
    test_app.dependency_overrides[get_session] = _override_session
    test_app.include_router(health_router.router)
    return test_app


@pytest.fixture
def client(test_engine):
    test_app = _build_test_app(test_engine)
    with TestClient(test_app, raise_server_exceptions=False) as c:
        yield c


# ---------------------------------------------------------------------------
# TestHealthFragmentGmailStatus
# ---------------------------------------------------------------------------


class TestHealthFragmentGmailStatus:
    """8 acceptance test cases for feature 005 health fragment Gmail rows."""

    def test_tc01_connected_with_masked_email(self, test_engine):
        """TC-01: gmail_status=ok → ✓ Connected + masked email al***@example.com."""
        mock_credential = MagicMock()
        mock_credential.account_email = "alice@example.com"

        with patch("src.api.health.GmailCredentialService") as mock_svc_cls:
            mock_svc = mock_svc_cls.return_value
            mock_svc.get_connection_status = AsyncMock(return_value=ConnectorStatus.OK)
            mock_svc.get = AsyncMock(return_value=mock_credential)

            test_app = _build_test_app(test_engine)
            with TestClient(test_app, raise_server_exceptions=False) as c:
                resp = c.get("/health/fragment")

        assert resp.status_code == 200
        assert "✓ Connected" in resp.text
        assert "al***@example.com" in resp.text
        assert 'href="/config"' in resp.text  # FR-003: config link present in ok state

    def test_tc02_unconfigured_token(self, test_engine):
        """TC-02: gmail_status=unconfigured → — Not Connected."""
        with patch("src.api.health.GmailCredentialService") as mock_svc_cls:
            mock_svc = mock_svc_cls.return_value
            mock_svc.get_connection_status = AsyncMock(
                return_value=ConnectorStatus.UNCONFIGURED
            )

            test_app = _build_test_app(test_engine)
            with TestClient(test_app, raise_server_exceptions=False) as c:
                resp = c.get("/health/fragment")

        assert resp.status_code == 200
        assert "— Not Connected" in resp.text

    def test_tc03_token_error(self, test_engine):
        """TC-03: gmail_status=token_error → ⚠ Token Error."""
        with patch("src.api.health.GmailCredentialService") as mock_svc_cls:
            mock_svc = mock_svc_cls.return_value
            mock_svc.get_connection_status = AsyncMock(
                return_value=ConnectorStatus.TOKEN_ERROR
            )

            test_app = _build_test_app(test_engine)
            with TestClient(test_app, raise_server_exceptions=False) as c:
                resp = c.get("/health/fragment")

        assert resp.status_code == 200
        assert "⚠ Token Error" in resp.text
        assert 'href="/config"' in resp.text  # SC-003: token-error state links to config

    def test_tc04_db_down_graceful_degradation(self, test_engine):
        """TC-04: get_connection_status raises → ? Unknown, HTTP 200."""
        with patch("src.api.health.GmailCredentialService") as mock_svc_cls:
            mock_svc = mock_svc_cls.return_value
            mock_svc.get_connection_status = AsyncMock(
                side_effect=Exception("db down")
            )

            test_app = _build_test_app(test_engine)
            with TestClient(test_app, raise_server_exceptions=False) as c:
                resp = c.get("/health/fragment")

        assert resp.status_code == 200
        assert "? Unknown" in resp.text

    def test_tc05_oauth_not_configured(self, test_engine):
        """TC-05: gmail_client_id/secret empty → — Not Configured."""
        with patch("src.api.health.GmailCredentialService") as mock_svc_cls:
            mock_svc = mock_svc_cls.return_value
            mock_svc.get_connection_status = AsyncMock(
                return_value=ConnectorStatus.UNCONFIGURED
            )
            with patch("src.api.health.settings") as mock_settings:
                mock_settings.gmail_client_id = ""
                mock_settings.gmail_client_secret = ""

                test_app = _build_test_app(test_engine)
                with TestClient(test_app, raise_server_exceptions=False) as c:
                    resp = c.get("/health/fragment")

        assert resp.status_code == 200
        assert "— Not Configured" in resp.text
        assert 'href="/config"' in resp.text  # FR-003: not-configured state links to config

    def test_tc06_oauth_configured(self, test_engine):
        """TC-06: gmail_client_id/secret set → ✓ Configured."""
        with patch("src.api.health.GmailCredentialService") as mock_svc_cls:
            mock_svc = mock_svc_cls.return_value
            mock_svc.get_connection_status = AsyncMock(
                return_value=ConnectorStatus.UNCONFIGURED
            )
            with patch("src.api.health.settings") as mock_settings:
                mock_settings.gmail_client_id = "x"
                mock_settings.gmail_client_secret = "y"

                test_app = _build_test_app(test_engine)
                with TestClient(test_app, raise_server_exceptions=False) as c:
                    resp = c.get("/health/fragment")

        assert resp.status_code == 200
        assert "✓ Configured" in resp.text

    def test_tc07_sentinel_email_display(self, test_engine):
        """TC-07: sentinel email → (account unknown — please re-authorize)."""
        mock_credential = MagicMock()
        mock_credential.account_email = "migrated-from-env"

        with patch("src.api.health.GmailCredentialService") as mock_svc_cls:
            mock_svc = mock_svc_cls.return_value
            mock_svc.get_connection_status = AsyncMock(return_value=ConnectorStatus.OK)
            mock_svc.get = AsyncMock(return_value=mock_credential)

            test_app = _build_test_app(test_engine)
            with TestClient(test_app, raise_server_exceptions=False) as c:
                resp = c.get("/health/fragment")

        assert resp.status_code == 200
        assert "(account unknown — please re-authorize)" in resp.text

    def test_tc08_regression_existing_rows_present(self, test_engine):
        """TC-08: Database and LLM / Ollama rows still render; no 5xx."""
        with patch("src.api.health.GmailCredentialService") as mock_svc_cls:
            mock_svc = mock_svc_cls.return_value
            mock_svc.get_connection_status = AsyncMock(
                return_value=ConnectorStatus.UNCONFIGURED
            )

            test_app = _build_test_app(test_engine)
            with TestClient(test_app, raise_server_exceptions=False) as c:
                resp = c.get("/health/fragment")

        assert resp.status_code == 200
        assert "Database" in resp.text
        assert "LLM / Ollama" in resp.text
        # At least one known status string for existing service rows
        known_statuses = ["✓ ok", "— unconfigured", "✗ unreachable"]
        assert any(s in resp.text for s in known_statuses)
        # I1: old row must not reappear
        assert "Gmail Credentials" not in resp.text

    def test_tc09_health_page_contains_gmail_rows(self, test_engine):
        """TC-09: /health/page (full page) renders Gmail App Credentials and OAuth Token rows."""
        with patch("src.api.health.GmailCredentialService") as mock_svc_cls:
            mock_svc = mock_svc_cls.return_value
            mock_svc.get_connection_status = AsyncMock(
                return_value=ConnectorStatus.UNCONFIGURED
            )

            test_app = _build_test_app(test_engine)
            with TestClient(test_app, raise_server_exceptions=False) as c:
                resp = c.get("/health/page")

        assert resp.status_code == 200
        assert "Gmail App Credentials" in resp.text
        assert "Gmail OAuth Token" in resp.text
        assert "Gmail Credentials" not in resp.text  # old row must not appear
