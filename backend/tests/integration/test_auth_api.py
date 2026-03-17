"""Integration tests for Gmail OAuth auth endpoints (T009, T018).

Tests:
  T009: GET /auth/gmail/initiate — 302 to Google, oauth_state cookie set; 503 when GMAIL_CLIENT_ID missing
        GET /auth/gmail/callback — CSRF validation, Google error, no refresh token
  T018: POST /auth/gmail/disconnect — HTMX path (200 + fragment), non-HTMX path (302)

Uses a minimal FastAPI app (lifespan bypassed) with an in-memory SQLite DB.
Pattern follows test_mail_api.py conventions.
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
    """Build a minimal FastAPI app with auth router and SQLite session override."""
    from src.database import get_session
    from src.api import auth as auth_router

    Session = async_sessionmaker(test_engine, expire_on_commit=False)

    async def _override_session():
        async with Session() as session:
            yield session

    test_app = FastAPI(title="Test Auth App")
    test_app.dependency_overrides[get_session] = _override_session
    test_app.include_router(auth_router.router)
    return test_app


@pytest.fixture
def client(test_engine):
    test_app = _build_test_app(test_engine)
    with TestClient(test_app, raise_server_exceptions=False) as c:
        yield c


# ---------------------------------------------------------------------------
# T009 — GET /auth/gmail/initiate
# ---------------------------------------------------------------------------


class TestGmailInitiate:
    def test_redirect_when_oauth_not_configured(self, test_engine):
        """Redirects to /config?gmail_error=oauth_unconfigured when client creds missing."""
        with patch("src.api.auth.settings") as mock_settings:
            mock_settings.gmail_client_id = ""
            mock_settings.gmail_client_secret = ""
            mock_settings.secret_key = "test-key"
            mock_settings.gmail_redirect_uri = ""

            test_app = _build_test_app(test_engine)
            with TestClient(test_app, raise_server_exceptions=False) as client:
                resp = client.get("/auth/gmail/initiate", follow_redirects=False)

        assert resp.status_code == 302
        assert resp.headers["location"] == "/config?gmail_error=oauth_unconfigured"

    def test_302_to_google_when_configured(self, test_engine):
        """Returns 302 with Location pointing to Google OAuth."""
        with (
            patch("src.api.auth.settings") as mock_settings,
            patch("src.api.auth._build_flow") as mock_build_flow,
        ):
            mock_settings.gmail_client_id = "test-client-id"
            mock_settings.gmail_client_secret = "test-client-secret"
            mock_settings.secret_key = "test-secret-key-32-chars-long!!!!"
            mock_settings.gmail_redirect_uri = ""

            mock_flow = MagicMock()
            mock_flow.authorization_url.return_value = (
                "https://accounts.google.com/o/oauth2/auth?client_id=test",
                "state-value",
            )
            mock_build_flow.return_value = mock_flow

            test_app = _build_test_app(test_engine)
            with TestClient(test_app, raise_server_exceptions=False) as client:
                resp = client.get("/auth/gmail/initiate", follow_redirects=False)

        assert resp.status_code == 302
        assert "accounts.google.com" in resp.headers["location"]

    def test_oauth_state_cookie_set(self, test_engine):
        """HttpOnly oauth_state cookie is set on redirect."""
        with (
            patch("src.api.auth.settings") as mock_settings,
            patch("src.api.auth._build_flow") as mock_build_flow,
        ):
            mock_settings.gmail_client_id = "test-client-id"
            mock_settings.gmail_client_secret = "test-client-secret"
            mock_settings.secret_key = "test-secret-key-32-chars-long!!!!"
            mock_settings.gmail_redirect_uri = ""

            mock_flow = MagicMock()
            mock_flow.authorization_url.return_value = (
                "https://accounts.google.com/o/oauth2/auth?client_id=test",
                "state",
            )
            mock_build_flow.return_value = mock_flow

            test_app = _build_test_app(test_engine)
            with TestClient(test_app, raise_server_exceptions=False) as client:
                resp = client.get("/auth/gmail/initiate", follow_redirects=False)

        assert "oauth_state" in resp.cookies

    # --- T001: prompt tests ---------------------------------------------------

    def test_prompt_exact_value(self, test_engine):
        """authorization_url is called with prompt='select_account consent' exactly (SC-001)."""
        with (
            patch("src.api.auth.settings") as mock_settings,
            patch("src.api.auth._build_flow") as mock_build_flow,
        ):
            mock_settings.gmail_client_id = "test-client-id"
            mock_settings.gmail_client_secret = "test-client-secret"
            mock_settings.secret_key = "test-secret-key-32-chars-long!!!!"
            mock_settings.gmail_redirect_uri = ""

            mock_flow = MagicMock()
            mock_flow.authorization_url.return_value = (
                "https://accounts.google.com/o/oauth2/auth?client_id=test",
                "state-value",
            )
            mock_build_flow.return_value = mock_flow

            test_app = _build_test_app(test_engine)
            with TestClient(test_app, raise_server_exceptions=False) as client:
                client.get("/auth/gmail/initiate", follow_redirects=False)

        _, kwargs = mock_flow.authorization_url.call_args
        assert kwargs["prompt"] == "select_account consent"

    # --- T003: login_hint tests -----------------------------------------------

    def test_login_hint_present_when_credential_exists(self, test_engine):
        """authorization_url receives login_hint=account_email when a credential is stored."""
        mock_cred = MagicMock()
        mock_cred.account_email = "alice@example.com"

        with (
            patch("src.api.auth.settings") as mock_settings,
            patch("src.api.auth._build_flow") as mock_build_flow,
            patch("src.api.auth.GmailCredentialService") as mock_cred_svc_cls,
        ):
            mock_settings.gmail_client_id = "test-client-id"
            mock_settings.gmail_client_secret = "test-client-secret"
            mock_settings.secret_key = "test-secret-key-32-chars-long!!!!"
            mock_settings.gmail_redirect_uri = ""

            mock_flow = MagicMock()
            mock_flow.authorization_url.return_value = (
                "https://accounts.google.com/o/oauth2/auth?client_id=test",
                "state-value",
            )
            mock_build_flow.return_value = mock_flow

            mock_cred_svc = AsyncMock()
            mock_cred_svc.get.return_value = mock_cred
            mock_cred_svc_cls.return_value = mock_cred_svc

            test_app = _build_test_app(test_engine)
            with TestClient(test_app, raise_server_exceptions=False) as client:
                client.get("/auth/gmail/initiate", follow_redirects=False)

        _, kwargs = mock_flow.authorization_url.call_args
        assert kwargs.get("login_hint") == "alice@example.com"

    def test_login_hint_absent_when_no_credential(self, test_engine):
        """authorization_url is NOT called with login_hint when no credential is stored."""
        with (
            patch("src.api.auth.settings") as mock_settings,
            patch("src.api.auth._build_flow") as mock_build_flow,
            patch("src.api.auth.GmailCredentialService") as mock_cred_svc_cls,
        ):
            mock_settings.gmail_client_id = "test-client-id"
            mock_settings.gmail_client_secret = "test-client-secret"
            mock_settings.secret_key = "test-secret-key-32-chars-long!!!!"
            mock_settings.gmail_redirect_uri = ""

            mock_flow = MagicMock()
            mock_flow.authorization_url.return_value = (
                "https://accounts.google.com/o/oauth2/auth?client_id=test",
                "state-value",
            )
            mock_build_flow.return_value = mock_flow

            mock_cred_svc = AsyncMock()
            mock_cred_svc.get.return_value = None
            mock_cred_svc_cls.return_value = mock_cred_svc

            test_app = _build_test_app(test_engine)
            with TestClient(test_app, raise_server_exceptions=False) as client:
                client.get("/auth/gmail/initiate", follow_redirects=False)

        _, kwargs = mock_flow.authorization_url.call_args
        assert "login_hint" not in kwargs

    def test_login_hint_absent_for_sentinel_email(self, test_engine):
        """login_hint is NOT passed when account_email is the env-migration sentinel (FR-004)."""
        mock_cred = MagicMock()
        mock_cred.account_email = "migrated-from-env"

        with (
            patch("src.api.auth.settings") as mock_settings,
            patch("src.api.auth._build_flow") as mock_build_flow,
            patch("src.api.auth.GmailCredentialService") as mock_cred_svc_cls,
        ):
            mock_settings.gmail_client_id = "test-client-id"
            mock_settings.gmail_client_secret = "test-client-secret"
            mock_settings.secret_key = "test-secret-key-32-chars-long!!!!"
            mock_settings.gmail_redirect_uri = ""

            mock_flow = MagicMock()
            mock_flow.authorization_url.return_value = (
                "https://accounts.google.com/o/oauth2/auth?client_id=test",
                "state-value",
            )
            mock_build_flow.return_value = mock_flow

            mock_cred_svc = AsyncMock()
            mock_cred_svc.get.return_value = mock_cred
            mock_cred_svc_cls.return_value = mock_cred_svc

            test_app = _build_test_app(test_engine)
            with TestClient(test_app, raise_server_exceptions=False) as client:
                client.get("/auth/gmail/initiate", follow_redirects=False)

        _, kwargs = mock_flow.authorization_url.call_args
        assert "login_hint" not in kwargs


# ---------------------------------------------------------------------------
# T009 — GET /auth/gmail/callback
# ---------------------------------------------------------------------------


class TestGmailCallback:
    def test_400_when_no_cookie(self, client):
        """Returns 400 when oauth_state cookie is absent."""
        resp = client.get(
            "/auth/gmail/callback?code=abc&state=xyz",
            follow_redirects=False,
        )
        assert resp.status_code == 400

    def test_400_on_expired_signature(self, test_engine):
        """Returns 400 when itsdangerous raises SignatureExpired."""
        from itsdangerous import SignatureExpired

        with patch("src.api.auth._get_serializer") as mock_ser_factory:
            mock_ser = MagicMock()
            mock_ser.loads.side_effect = SignatureExpired("expired")
            mock_ser_factory.return_value = mock_ser

            test_app = _build_test_app(test_engine)
            with TestClient(test_app, raise_server_exceptions=False) as client:
                client.cookies.set("oauth_state", "some-signed-state")
                resp = client.get(
                    "/auth/gmail/callback?code=abc&state=xyz",
                    follow_redirects=False,
                )
        assert resp.status_code == 400

    def test_400_on_state_mismatch(self, test_engine):
        """Returns 400 when state cookie doesn't match query param."""
        with patch("src.api.auth._get_serializer") as mock_ser_factory:
            mock_ser = MagicMock()
            mock_ser.loads.return_value = "correct-state"
            mock_ser_factory.return_value = mock_ser

            test_app = _build_test_app(test_engine)
            with TestClient(test_app, raise_server_exceptions=False) as client:
                client.cookies.set("oauth_state", "signed-correct-state")
                resp = client.get(
                    "/auth/gmail/callback?code=abc&state=WRONG-state",
                    follow_redirects=False,
                )
        assert resp.status_code == 400

    def test_redirects_to_cancelled_on_google_error(self, test_engine):
        """Redirects to /config?gmail_error=cancelled when Google returns error."""
        state = "my-state-value"

        with patch("src.api.auth._get_serializer") as mock_ser_factory:
            mock_ser = MagicMock()
            mock_ser.loads.return_value = state
            mock_ser_factory.return_value = mock_ser

            test_app = _build_test_app(test_engine)
            with TestClient(test_app, raise_server_exceptions=False) as client:
                client.cookies.set("oauth_state", "signed-state")
                resp = client.get(
                    f"/auth/gmail/callback?error=access_denied&state={state}",
                    follow_redirects=False,
                )
        assert resp.status_code == 302
        assert "gmail_error=cancelled" in resp.headers["location"]


# ---------------------------------------------------------------------------
# T018 — POST /auth/gmail/disconnect
# ---------------------------------------------------------------------------


class TestGmailDisconnect:
    def test_htmx_returns_200_with_html_fragment(self, test_engine):
        """HTMX path: HX-Request: true → 200 with HTML fragment."""
        with patch("src.api.auth.settings") as mock_settings:
            mock_settings.gmail_client_id = "id"
            mock_settings.gmail_client_secret = "secret"

            test_app = _build_test_app(test_engine)
            with TestClient(test_app, raise_server_exceptions=False) as client:
                resp = client.post(
                    "/auth/gmail/disconnect",
                    headers={"HX-Request": "true"},
                )

        assert resp.status_code == 200
        assert "gmail-connection-section" in resp.text

    def test_non_htmx_redirects_to_config(self, test_engine):
        """Non-HTMX path: no HX-Request header → 302 to /config?gmail_disconnected=1."""
        with patch("src.api.auth.settings") as mock_settings:
            mock_settings.gmail_client_id = "id"
            mock_settings.gmail_client_secret = "secret"

            test_app = _build_test_app(test_engine)
            with TestClient(test_app, raise_server_exceptions=False) as client:
                resp = client.post(
                    "/auth/gmail/disconnect",
                    follow_redirects=False,
                )

        assert resp.status_code == 302
        assert "gmail_disconnected=1" in resp.headers["location"]


# ---------------------------------------------------------------------------
# H3 — Callback success path (FR-010 / SC-004 verifier)
# ---------------------------------------------------------------------------


class TestGmailCallbackSuccess:
    def test_success_stores_token_redirects_and_no_token_in_logs(self, test_engine):
        """Success path: valid state, code → token stored, redirect, no token in logs.

        This is the primary SC-004 verifier: asserts that the plaintext refresh_token
        value ('secret-refresh-token') never appears in any structured log event.
        """
        import structlog.testing

        state = "valid-state-value"
        fake_refresh_token = "secret-refresh-token"

        mock_creds = MagicMock()
        mock_creds.refresh_token = fake_refresh_token
        mock_creds.token = "access-token"

        mock_profile = {"emailAddress": "repair@cafe.example.com"}
        mock_gmail_svc = MagicMock()
        mock_gmail_svc.users.return_value.getProfile.return_value.execute.return_value = mock_profile

        with (
            patch("src.api.auth._get_serializer") as mock_ser_factory,
            patch("src.api.auth._build_flow") as mock_build_flow,
            patch("src.api.auth.build") as mock_build,
        ):
            mock_ser = MagicMock()
            mock_ser.loads.return_value = state
            mock_ser_factory.return_value = mock_ser

            mock_flow = MagicMock()
            mock_flow.fetch_token = MagicMock()
            mock_flow.credentials = mock_creds
            mock_build_flow.return_value = mock_flow
            mock_build.return_value = mock_gmail_svc

            test_app = _build_test_app(test_engine)
            with TestClient(test_app, raise_server_exceptions=False) as client:
                with structlog.testing.capture_logs() as captured:
                    client.cookies.set("oauth_state", "signed-state")
                    resp = client.get(
                        f"/auth/gmail/callback?code=auth-code&state={state}",
                        follow_redirects=False,
                    )

        assert resp.status_code == 302
        assert "gmail_connected=1" in resp.headers["location"]

        # SC-004: verify no log record contains the plaintext token value
        all_log_values = str(captured)
        assert fake_refresh_token not in all_log_values, (
            f"Plaintext refresh token found in log output — FR-010 violation!\n{all_log_values}"
        )

        # Verify success event was logged with masked email
        success_events = [e for e in captured if e.get("event") == "gmail_callback_success"]
        assert len(success_events) == 1
        assert success_events[0].get("token_stored") is True
        assert fake_refresh_token not in str(success_events[0].get("account_email", ""))


# ---------------------------------------------------------------------------
# M1 — no_refresh_token error path
# ---------------------------------------------------------------------------


class TestGmailCallbackNoRefreshToken:
    def test_redirects_on_no_refresh_token(self, test_engine):
        """Callback with creds.refresh_token = None → /config?gmail_error=no_refresh_token."""
        state = "valid-state-value"

        mock_creds = MagicMock()
        mock_creds.refresh_token = None

        with (
            patch("src.api.auth._get_serializer") as mock_ser_factory,
            patch("src.api.auth._build_flow") as mock_build_flow,
        ):
            mock_ser = MagicMock()
            mock_ser.loads.return_value = state
            mock_ser_factory.return_value = mock_ser

            mock_flow = MagicMock()
            mock_flow.fetch_token = MagicMock()
            mock_flow.credentials = mock_creds
            mock_build_flow.return_value = mock_flow

            test_app = _build_test_app(test_engine)
            with TestClient(test_app, raise_server_exceptions=False) as client:
                client.cookies.set("oauth_state", "signed-state")
                resp = client.get(
                    f"/auth/gmail/callback?code=auth-code&state={state}",
                    follow_redirects=False,
                )

        assert resp.status_code == 302
        assert "gmail_error=no_refresh_token" in resp.headers["location"]


# ---------------------------------------------------------------------------
# M2 — Concurrent-tab CSRF cookie collision (expected secure behavior)
# ---------------------------------------------------------------------------


class TestConcurrentTabCsrf:
    def test_first_tab_callback_returns_400_after_second_initiate(self, test_engine):
        """Concurrent-tab CSRF: second /initiate overwrites cookie → first callback gets 400.

        This is the CORRECT, SECURE outcome. Tab 1's flow is abandoned; the operator
        retries. The second tab's callback (carrying the current cookie) succeeds normally.
        """
        # Tab 1 initiates → gets state_1 cookie
        # Tab 2 initiates → overwrites cookie with state_2
        # Tab 1 callback arrives with state_1 in query param but state_2 in cookie → 400

        state_1 = "state-from-tab-1"
        state_2 = "state-from-tab-2"

        with patch("src.api.auth._get_serializer") as mock_ser_factory:
            # Serializer returns state_2 (the value currently in the shared cookie)
            mock_ser = MagicMock()
            mock_ser.loads.return_value = state_2  # cookie contains Tab 2's state
            mock_ser_factory.return_value = mock_ser

            test_app = _build_test_app(test_engine)
            with TestClient(test_app, raise_server_exceptions=False) as client:
                # Set cookie to Tab 2's signed state (simulates Tab 2 having initiated last)
                client.cookies.set("oauth_state", "signed-state-2")
                # Tab 1's callback arrives with Tab 1's state in query param → mismatch
                resp = client.get(
                    f"/auth/gmail/callback?code=some-code&state={state_1}",
                    follow_redirects=False,
                )

        # Correct secure outcome: CSRF mismatch → 400, no token stored
        assert resp.status_code == 400

