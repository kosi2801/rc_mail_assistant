"""GmailCredentialService — encrypt/decrypt/upsert/delete OAuth token lifecycle.

Implements data-model.md §Service Layer Interface and research.md R-001, R-006,
R-007, R-010. Exception I.1 of constitution.md v1.2.0 applies to this module.

Security contract (FR-010):
  - Plaintext refresh tokens MUST NEVER appear in logs or return values
  - Fernet ciphertext IS safe to store in the database
  - The Fernet key is derived once per process from SECRET_KEY; never persisted
"""
from __future__ import annotations

import base64
import hashlib
import re
from datetime import datetime, timezone

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.logging_config import get_logger
from src.models.gmail_credential import GmailCredential
from src.services.mail_service import ConnectorStatus

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Module-level Fernet instance (derived once per process from SECRET_KEY)
# ---------------------------------------------------------------------------

_SENTINEL_EMAIL = "migrated-from-env"
_SENTINEL_DISPLAY = "(account unknown — please re-authorize)"


def _make_fernet() -> Fernet:
    """Derive a Fernet key from SECRET_KEY and return a Fernet instance.

    Key derivation: SHA-256(SECRET_KEY.encode("utf-8")) → URL-safe base64
    This produces a 32-byte (256-bit) key, but Fernet uses only the first 16
    bytes for AES-128-CBC; the remainder feeds HMAC-SHA256 for authentication.
    """
    raw_key = hashlib.sha256(settings.secret_key.encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(raw_key)
    return Fernet(key)


_fernet = _make_fernet()


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def mask_email(email: str) -> str:
    """Return a display-safe masked version of an email address.

    Examples:
        "alice@example.com" → "al***@example.com"
        "migrated-from-env" → "(account unknown — please re-authorize)"
        ""                  → ""
    """
    if not email:
        return ""
    if email == _SENTINEL_EMAIL:
        return _SENTINEL_DISPLAY
    # Standard masking: show first 2 chars of local part, mask rest
    match = re.match(r"^(.{1,2})(.*)(@.+)$", email)
    if match:
        visible, hidden, domain = match.groups()
        return f"{visible}{'*' * max(len(hidden), 3)}{domain}"
    # Fallback for unusual formats
    return email[:2] + "***"


# ---------------------------------------------------------------------------
# Service class
# ---------------------------------------------------------------------------


class GmailCredentialService:
    """Manages the encrypted Gmail OAuth credential lifecycle.

    All DB operations use the AsyncSession injected at construction.
    The Fernet instance is module-level (created once per process).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self) -> GmailCredential | None:
        """Return the current credential row (id=1), or None if not connected."""
        result = await self._session.execute(
            select(GmailCredential).where(GmailCredential.id == 1)
        )
        return result.scalar_one_or_none()

    async def upsert(self, plaintext_token: str, account_email: str) -> None:
        """Fernet-encrypt the token and upsert the id=1 singleton row.

        Args:
            plaintext_token: Raw OAuth refresh token (never stored or logged).
            account_email: Google account email (stored plaintext; display only).

        Raises:
            ValueError: If plaintext_token or account_email is empty.
        """
        if not plaintext_token:
            raise ValueError("plaintext_token must not be empty")
        if not account_email:
            raise ValueError("account_email must not be empty")

        # Encrypt — only the ciphertext touches the DB
        ciphertext = _fernet.encrypt(plaintext_token.encode("utf-8")).decode("ascii")

        now = datetime.now(tz=timezone.utc)
        stmt = (
            pg_insert(GmailCredential)
            .values(
                id=1,
                encrypted_refresh_token=ciphertext,
                account_email=account_email,
                connected_at=now,
                updated_at=now,
            )
            .on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "encrypted_refresh_token": ciphertext,
                    "account_email": account_email,
                    "updated_at": now,
                },
            )
        )
        await self._session.execute(stmt)
        await self._session.commit()
        logger.info("gmail_credential_upserted", account_email=mask_email(account_email))

    async def delete(self) -> None:
        """Remove the credential row (Disconnect action).

        Idempotent — no-op if no row exists.
        """
        result = await self._session.execute(
            delete(GmailCredential).where(GmailCredential.id == 1)
        )
        await self._session.commit()
        rows_deleted = result.rowcount
        logger.info("gmail_disconnected", rows_deleted=rows_deleted)

    async def decrypt_token(self, record: GmailCredential) -> str:
        """Decrypt and return the plaintext refresh token.

        Args:
            record: A GmailCredential ORM instance (id=1).

        Returns:
            Plaintext OAuth refresh token string.

        Raises:
            cryptography.fernet.InvalidToken: If SECRET_KEY has been rotated
                or the ciphertext is corrupted.
        """
        plaintext = _fernet.decrypt(
            record.encrypted_refresh_token.encode("ascii")
        )
        return plaintext.decode("utf-8")

    async def get_connection_status(self) -> ConnectorStatus:
        """Return current status without raising — safe to call from template context.

        Status derivation (data-model.md §Status Machine):
          - No row           → UNCONFIGURED
          - No client creds  → UNCONFIGURED
          - Row + OK decrypt → OK
          - Row + InvalidToken → TOKEN_ERROR
        """
        if not settings.gmail_client_id or not settings.gmail_client_secret:
            return ConnectorStatus.UNCONFIGURED

        record = await self.get()
        if record is None:
            return ConnectorStatus.UNCONFIGURED

        try:
            await self.decrypt_token(record)
        except InvalidToken:
            logger.warning("gmail_decrypt_failed", reason="InvalidToken")
            return ConnectorStatus.TOKEN_ERROR

        return ConnectorStatus.OK

    async def maybe_migrate_from_env(self) -> None:
        """FR-009: import GMAIL_REFRESH_TOKEN from env if set and no row exists.

        Cases:
          1. Env var present + no DB row → upsert with sentinel email, log deprecation warning
          2. Env var present + row exists → log advisory to remove redundant env var
          3. Env var absent → no-op
        """
        env_token = settings.gmail_refresh_token
        if not env_token:
            return  # Case 3: env absent — complete no-op

        record = await self.get()

        if record is None:
            # Case 1: import env token into DB
            await self.upsert(
                plaintext_token=env_token,
                account_email=_SENTINEL_EMAIL,
            )
            logger.warning(
                "gmail_token_migrated_from_env",
                message=(
                    "GMAIL_REFRESH_TOKEN has been imported into the database. "
                    "Remove it from .env at your convenience."
                ),
            )
        else:
            # Case 2: DB row already exists — advise operator to clean up env
            logger.warning(
                "gmail_env_token_redundant",
                message=(
                    "GMAIL_REFRESH_TOKEN is set in .env but a credential already exists "
                    "in the database. The env var is ignored. "
                    "Remove GMAIL_REFRESH_TOKEN from .env to suppress this warning."
                ),
            )
