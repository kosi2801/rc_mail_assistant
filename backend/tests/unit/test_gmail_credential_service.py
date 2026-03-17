"""Unit tests for GmailCredentialService (T008, T017, T024).

Tests:
  T008: get(), upsert(), decrypt_token(), get_connection_status()
        (UNCONFIGURED, OK, TOKEN_ERROR branches)
  T017: delete() — row deleted, idempotent; TOKEN_ERROR via InvalidToken mock
  T024: maybe_migrate_from_env() — all three cases
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import InvalidToken


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_service(session=None):
    """Build a GmailCredentialService with a mock session."""
    from src.services.gmail_credential_service import GmailCredentialService

    if session is None:
        session = AsyncMock()
    return GmailCredentialService(session)


def _make_record(email: str = "test@example.com", token: str = "encrypted-token"):
    """Build a fake GmailCredential ORM-like object."""
    rec = MagicMock()
    rec.account_email = email
    rec.encrypted_refresh_token = token
    return rec


def _make_execute_result(return_value=None):
    """Build a MagicMock that simulates AsyncSession.execute() result.

    scalar_one_or_none() is synchronous, so the result must be a MagicMock (not AsyncMock).
    """
    result = MagicMock()
    result.scalar_one_or_none.return_value = return_value
    return result


# ---------------------------------------------------------------------------
# T008 — get()
# ---------------------------------------------------------------------------


class TestGet:
    async def test_returns_none_when_no_row(self):
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_make_execute_result(None))

        svc = _make_service(session)
        assert await svc.get() is None

    async def test_returns_record_when_row_exists(self):
        session = AsyncMock()
        record = _make_record()
        session.execute = AsyncMock(return_value=_make_execute_result(record))

        svc = _make_service(session)
        assert await svc.get() is record


# ---------------------------------------------------------------------------
# T008 — upsert()
# ---------------------------------------------------------------------------


class TestUpsert:
    async def test_upsert_executes_and_commits(self):
        session = AsyncMock()
        session.execute = AsyncMock()
        session.commit = AsyncMock()

        svc = _make_service(session)
        await svc.upsert(plaintext_token="my-refresh-token", account_email="user@example.com")

        session.execute.assert_called_once()
        session.commit.assert_called_once()

    async def test_upsert_raises_on_empty_token(self):
        svc = _make_service()
        with pytest.raises(ValueError, match="plaintext_token"):
            await svc.upsert(plaintext_token="", account_email="user@example.com")

    async def test_upsert_raises_on_empty_email(self):
        svc = _make_service()
        with pytest.raises(ValueError, match="account_email"):
            await svc.upsert(plaintext_token="token", account_email="")

    async def test_upsert_encrypts_token(self):
        """Token passed to execute should not contain the plaintext string."""
        session = AsyncMock()
        executed_args = []

        async def capture_execute(stmt):
            executed_args.append(stmt)
            return AsyncMock()

        session.execute = capture_execute
        session.commit = AsyncMock()

        svc = _make_service(session)
        plaintext = "super-secret-refresh-token"
        await svc.upsert(plaintext_token=plaintext, account_email="a@b.com")

        # The raw plaintext must not appear in the compiled statement repr
        stmt_repr = str(executed_args[0])
        assert plaintext not in stmt_repr


# ---------------------------------------------------------------------------
# T008 — decrypt_token()
# ---------------------------------------------------------------------------


class TestDecryptToken:
    async def test_decrypt_roundtrip(self):
        """upsert then decrypt should return the original plaintext."""
        from src.services.gmail_credential_service import GmailCredentialService, _fernet

        plaintext = "test-refresh-token-abc123"
        ciphertext = _fernet.encrypt(plaintext.encode()).decode("ascii")
        record = _make_record(token=ciphertext)

        session = AsyncMock()
        svc = GmailCredentialService(session)
        result = await svc.decrypt_token(record)
        assert result == plaintext

    async def test_decrypt_raises_invalid_token_on_bad_ciphertext(self):
        from src.services.gmail_credential_service import GmailCredentialService

        record = _make_record(token="not-valid-fernet-ciphertext====")
        session = AsyncMock()
        svc = GmailCredentialService(session)

        with pytest.raises(InvalidToken):
            await svc.decrypt_token(record)


# ---------------------------------------------------------------------------
# T008 — get_connection_status()
# ---------------------------------------------------------------------------


class TestGetConnectionStatus:
    async def test_unconfigured_when_no_client_id(self):
        from src.services.mail_service import ConnectorStatus

        with patch("src.services.gmail_credential_service.settings") as mock_settings:
            mock_settings.gmail_client_id = ""
            mock_settings.gmail_client_secret = "secret"

            session = AsyncMock()
            from src.services.gmail_credential_service import GmailCredentialService

            svc = GmailCredentialService(session)
            status = await svc.get_connection_status()
        assert status == ConnectorStatus.UNCONFIGURED

    async def test_unconfigured_when_no_client_secret(self):
        from src.services.mail_service import ConnectorStatus

        with patch("src.services.gmail_credential_service.settings") as mock_settings:
            mock_settings.gmail_client_id = "client-id"
            mock_settings.gmail_client_secret = ""

            session = AsyncMock()
            from src.services.gmail_credential_service import GmailCredentialService

            svc = GmailCredentialService(session)
            status = await svc.get_connection_status()
        assert status == ConnectorStatus.UNCONFIGURED

    async def test_unconfigured_when_no_db_row(self):
        from src.services.mail_service import ConnectorStatus

        with patch("src.services.gmail_credential_service.settings") as mock_settings:
            mock_settings.gmail_client_id = "client-id"
            mock_settings.gmail_client_secret = "secret"

            session = AsyncMock()
            session.execute = AsyncMock(return_value=_make_execute_result(None))

            from src.services.gmail_credential_service import GmailCredentialService

            svc = GmailCredentialService(session)
            status = await svc.get_connection_status()
        assert status == ConnectorStatus.UNCONFIGURED

    async def test_ok_when_row_present_and_decrypts(self):
        from src.services.gmail_credential_service import GmailCredentialService, _fernet
        from src.services.mail_service import ConnectorStatus

        ciphertext = _fernet.encrypt(b"refresh-token").decode("ascii")
        record = _make_record(token=ciphertext)

        with patch("src.services.gmail_credential_service.settings") as mock_settings:
            mock_settings.gmail_client_id = "client-id"
            mock_settings.gmail_client_secret = "secret"

            session = AsyncMock()
            session.execute = AsyncMock(return_value=_make_execute_result(record))

            svc = GmailCredentialService(session)
            status = await svc.get_connection_status()
        assert status == ConnectorStatus.OK

    async def test_token_error_when_invalid_ciphertext(self):
        from src.services.gmail_credential_service import GmailCredentialService
        from src.services.mail_service import ConnectorStatus

        record = _make_record(token="invalid-ciphertext")

        with patch("src.services.gmail_credential_service.settings") as mock_settings:
            mock_settings.gmail_client_id = "client-id"
            mock_settings.gmail_client_secret = "secret"

            session = AsyncMock()
            session.execute = AsyncMock(return_value=_make_execute_result(record))

            svc = GmailCredentialService(session)
            status = await svc.get_connection_status()
        assert status == ConnectorStatus.TOKEN_ERROR


# ---------------------------------------------------------------------------
# T017 — delete()
# ---------------------------------------------------------------------------


class TestDelete:
    async def test_delete_executes_and_commits(self):
        session = AsyncMock()
        delete_result = MagicMock()
        delete_result.rowcount = 1
        session.execute = AsyncMock(return_value=delete_result)
        session.commit = AsyncMock()

        svc = _make_service(session)
        await svc.delete()

        session.execute.assert_called_once()
        session.commit.assert_called_once()

    async def test_delete_is_idempotent_when_no_row(self):
        """No error raised even when rowcount = 0."""
        session = AsyncMock()
        delete_result = MagicMock()
        delete_result.rowcount = 0
        session.execute = AsyncMock(return_value=delete_result)
        session.commit = AsyncMock()

        svc = _make_service(session)
        # Should not raise
        await svc.delete()
        session.commit.assert_called_once()


# ---------------------------------------------------------------------------
# T024 — maybe_migrate_from_env()
# ---------------------------------------------------------------------------


class TestMaybeMigrateFromEnv:
    async def test_noop_when_env_absent(self):
        """Case 3: env var absent → no DB operations."""
        with patch("src.services.gmail_credential_service.settings") as mock_settings:
            mock_settings.gmail_refresh_token = ""
            mock_settings.gmail_client_id = "id"
            mock_settings.gmail_client_secret = "secret"
            mock_settings.secret_key = "test-secret-key"

            session = AsyncMock()
            from src.services.gmail_credential_service import GmailCredentialService

            svc = GmailCredentialService(session)
            await svc.maybe_migrate_from_env()

        session.execute.assert_not_called()

    async def test_upsert_called_when_env_present_no_row(self):
        """Case 1: env var present + no DB row → upsert called + deprecation warning logged."""
        import structlog.testing

        with patch("src.services.gmail_credential_service.settings") as mock_settings:
            mock_settings.gmail_refresh_token = "env-refresh-token"
            mock_settings.gmail_client_id = "id"
            mock_settings.gmail_client_secret = "secret"
            mock_settings.secret_key = "test-secret-key"

            session = AsyncMock()
            # get() returns None (no row), upsert execute also returns MagicMock
            session.execute = AsyncMock(side_effect=[
                _make_execute_result(None),  # get() call
                MagicMock(),                  # upsert() INSERT ... ON CONFLICT call
            ])
            session.commit = AsyncMock()

            from src.services.gmail_credential_service import GmailCredentialService

            svc = GmailCredentialService(session)
            with structlog.testing.capture_logs() as captured:
                await svc.maybe_migrate_from_env()

        # Should have called execute twice (get + upsert) and commit once
        assert session.execute.call_count == 2
        session.commit.assert_called_once()

        # Assert deprecation warning event was emitted (T024 requirement)
        warning_events = [
            e for e in captured if e.get("event") == "gmail_token_migrated_from_env"
        ]
        assert len(warning_events) == 1, (
            f"Expected 'gmail_token_migrated_from_env' warning; got: {captured}"
        )
        # FR-010: token value must not appear in the log message
        assert "env-refresh-token" not in str(warning_events[0])

    async def test_no_upsert_when_env_present_row_exists(self):
        """Case 2: env var present + row exists → no upsert, only get()."""
        with patch("src.services.gmail_credential_service.settings") as mock_settings:
            mock_settings.gmail_refresh_token = "env-refresh-token"
            mock_settings.gmail_client_id = "id"
            mock_settings.gmail_client_secret = "secret"
            mock_settings.secret_key = "test-secret-key"

            session = AsyncMock()
            # get() returns existing record
            existing_record = _make_record()
            session.execute = AsyncMock(return_value=_make_execute_result(existing_record))
            session.commit = AsyncMock()

            from src.services.gmail_credential_service import GmailCredentialService

            svc = GmailCredentialService(session)
            await svc.maybe_migrate_from_env()

        # Only one execute (the get) — no upsert
        assert session.execute.call_count == 1
        session.commit.assert_not_called()


# ---------------------------------------------------------------------------
# mask_email() helper
# ---------------------------------------------------------------------------


class TestMaskEmail:
    def test_standard_email(self):
        from src.services.gmail_credential_service import mask_email

        result = mask_email("alice@example.com")
        assert result.endswith("@example.com")
        assert result.startswith("al")
        assert "***" in result
        # Original email not in result
        assert "alice" not in result

    def test_sentinel_returns_display_string(self):
        from src.services.gmail_credential_service import mask_email

        result = mask_email("migrated-from-env")
        assert "unknown" in result.lower() or "re-authorize" in result.lower()

    def test_empty_returns_empty(self):
        from src.services.gmail_credential_service import mask_email

        assert mask_email("") == ""
