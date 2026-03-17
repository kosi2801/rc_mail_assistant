# Data Model: Gmail OAuth Token Secure Storage

**Feature**: `003-gmail-oauth-token-db` | **Phase**: 1 (Design) | **Date**: 2025-06-26
**Source**: [spec.md](./spec.md) § Key Entities + Requirements FR-003, FR-006, FR-007, FR-012
**Research**: [research.md](./research.md) R-001, R-006, R-007, R-010

---

## Overview

This feature introduces one new database table (`gmail_credentials`) and one new
ORM model (`GmailCredential`). No existing tables are modified. All existing models
(`IncomingEmail`, `MailSyncCursor`, `MailSyncRun`, `Setting`) are unchanged.

---

## New Entity: `GmailCredential`

### Purpose

Singleton record representing the active Gmail OAuth authorization. Holds the
Fernet-encrypted refresh token and the associated account email for display.
At most one row exists at any time (enforced by fixed `id = 1`).

### Table: `gmail_credentials`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | `INTEGER` | `PRIMARY KEY` (no autoincrement) | Always `1`; singleton enforced at PK level |
| `encrypted_refresh_token` | `TEXT` | `NOT NULL` | Fernet ciphertext of the OAuth refresh token; variable length (~200–400 chars base64) |
| `account_email` | `VARCHAR(255)` | `NOT NULL` | Email address returned by Google at authorization; used for display (masked) only |
| `connected_at` | `TIMESTAMP WITH TIME ZONE` | `NOT NULL`, `DEFAULT now()` | Timestamp of first successful authorization |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | `NOT NULL`, `DEFAULT now()` | Timestamp of most recent upsert (connect or re-authorize) |

### ORM Model (SQLAlchemy 2.0 `mapped_column`)

```python
# backend/src/models/gmail_credential.py
"""ORM model for the Gmail OAuth credential singleton (data-model.md)."""
from datetime import datetime

from sqlalchemy import Integer, String, Text, TIMESTAMP, func
from sqlalchemy.orm import Mapped, mapped_column

from src.base_model import Base


class GmailCredential(Base):
    """Singleton record (id=1) for the stored Gmail OAuth refresh token."""

    __tablename__ = "gmail_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # always 1
    encrypted_refresh_token: Mapped[str] = mapped_column(Text, nullable=False)
    account_email: Mapped[str] = mapped_column(String(255), nullable=False)
    connected_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
```

### Validation Rules

| Rule | Where Enforced |
|------|---------------|
| `id` must always be `1` | Service layer (`GmailCredentialService.upsert`) |
| `encrypted_refresh_token` must be non-empty | Service layer (before insert) |
| `account_email` must be non-empty string | Service layer (before insert) |
| Ciphertext column must be `TEXT` (not `VARCHAR`) | Schema — accommodates variable Fernet output |
| No foreign keys | Standalone singleton; no relational links needed |

### State Machine

```
                            ┌──────────────────────────────────────────┐
                            │            (no row in DB)                │
                            │         Status: UNCONFIGURED             │
                            └──────┬───────────────────────────────────┘
                                   │ operator clicks "Connect Gmail"
                                   │ GET /auth/gmail/initiate
                                   ▼
                      ┌────────────────────────┐
                      │   OAuth flow in Google │
                      │   (redirect round-trip)│
                      └────────────┬───────────┘
                                   │ successful callback + DB upsert
                                   ▼
                  ┌────────────────────────────────────────┐
                  │          (row id=1 present)            │
                  │         Status: CONNECTED              │
                  └──┬──────────────────────────┬──────────┘
                     │ operator clicks Disconnect│ SECRET_KEY rotated,
                     │ DELETE WHERE id=1         │ token revoked, or
                     │                           │ Fernet InvalidToken
                     ▼                           ▼
          ┌──────────────────┐    ┌────────────────────────────────┐
          │  (no row in DB)  │    │     (row id=1 still present)   │
          │  UNCONFIGURED    │    │  Status: TOKEN_ERROR           │
          └──────────────────┘    │  (decryption / refresh failed) │
                                  └───────────┬────────────────────┘
                                              │ operator clicks Re-authorize
                                              │ (same OAuth flow as Connect)
                                              │ upsert replaces old record
                                              ▼
                                   ┌──────────────────┐
                                   │   CONNECTED      │
                                   └──────────────────┘
```

**Status derivation logic** (in `GmailCredentialService.get_connection_status`):

| Condition | `ConnectorStatus` returned |
|-----------|---------------------------|
| No row in `gmail_credentials` | `UNCONFIGURED` |
| Row present, decryption succeeds, no pending error flag | `OK` |
| Row present, `Fernet.InvalidToken` raised | `TOKEN_ERROR` |
| Row present, Google `RefreshError` on token use | `TOKEN_ERROR` |
| `GMAIL_CLIENT_ID` or `GMAIL_CLIENT_SECRET` missing | `UNCONFIGURED` |

---

## Migration

### File: `backend/migrations/versions/0003_create_gmail_credentials.py`

```python
"""create gmail_credentials table

Revision ID: 0003
Revises: 0002
Create Date: 2025-06-26 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gmail_credentials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("encrypted_refresh_token", sa.Text(), nullable=False),
        sa.Column("account_email", sa.String(255), nullable=False),
        sa.Column(
            "connected_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("gmail_credentials")
```

---

## Service Layer Interface: `GmailCredentialService`

Defined in `backend/src/services/gmail_credential_service.py`.
This section documents the public contract; implementation details are in tasks.md.

```python
class GmailCredentialService:
    """Manages the encrypted Gmail OAuth credential lifecycle."""

    def __init__(self, session: AsyncSession) -> None: ...

    async def get(self) -> GmailCredential | None:
        """Return the current credential row, or None if not connected."""

    async def upsert(self, plaintext_token: str, account_email: str) -> None:
        """Fernet-encrypt the token and upsert id=1 row."""

    async def delete(self) -> None:
        """Remove the credential row (Disconnect action)."""

    async def decrypt_token(self, record: GmailCredential) -> str:
        """Decrypt and return the plaintext refresh token.

        Raises:
            cryptography.fernet.InvalidToken: if SECRET_KEY has been rotated
                or the ciphertext is corrupted.
        """

    async def get_connection_status(self) -> ConnectorStatus:
        """Return current status without raising — safe to call from template context."""

    async def maybe_migrate_from_env(self) -> None:
        """FR-009: import GMAIL_REFRESH_TOKEN from env if set and no row exists."""
```

**Encryption helper** (module-level, derived once per process):

```python
# backend/src/services/gmail_credential_service.py
import base64, hashlib
from cryptography.fernet import Fernet
from src.config import settings

def _make_fernet() -> Fernet:
    key = base64.urlsafe_b64encode(
        hashlib.sha256(settings.secret_key.encode("utf-8")).digest()
    )
    return Fernet(key)

_fernet = _make_fernet()
```

---

## Existing Models: No Changes

| Model | Table | Change |
|-------|-------|--------|
| `IncomingEmail` | `incoming_emails` | None |
| `MailSyncCursor` | `mail_sync_cursor` | None |
| `MailSyncRun` | `mail_sync_runs` | None |
| `Setting` | `settings` | None — `KNOWN_KEYS` unchanged |

---

## `config.py` Settings Change

Remove the `gmail_refresh_token` field from `Settings` (it will no longer be
read after startup migration):

```python
# REMOVE from backend/src/config.py:
gmail_refresh_token: str = ""

# KEEP:
gmail_client_id: str = ""
gmail_client_secret: str = ""
```

The `gmail_refresh_token` field must remain **temporarily** during the startup
migration window (FR-009 reads `settings.gmail_refresh_token`). After
`maybe_migrate_from_env()` runs, the value is no longer needed. The field should
be kept with a deprecation comment in `config.py` and removed in a follow-up
feature once the migration period ends. The `.env.example` entry is removed
immediately (FR-008).
