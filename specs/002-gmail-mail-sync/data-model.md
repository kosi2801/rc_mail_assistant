# Data Model: Gmail Mail Sync

**Feature**: 002-gmail-mail-sync  
**Date**: 2026-02-28

---

## Entities

### IncomingEmail

Represents a single fetched visit-request email. Uniquely identified by the Gmail message ID.
Content is immutable after initial fetch. Individual records may be hard-deleted by the operator
via the UI; no `deleted_at` or `expires_at` field is used and no automatic expiry occurs.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | `INTEGER` | PK, auto-increment | Internal surrogate key |
| `gmail_message_id` | `VARCHAR(255)` | UNIQUE, NOT NULL, indexed | Deduplication key (FR-004) |
| `gmail_thread_id` | `VARCHAR(255)` | NOT NULL | Stored for future threading support |
| `sender_name` | `VARCHAR(255)` | NOT NULL | Display name from `From:` header; empty string if absent |
| `sender_email` | `VARCHAR(255)` | NOT NULL | Email address from `From:` header |
| `subject` | `TEXT` | NOT NULL | Subject line; empty string if absent |
| `received_at` | `TIMESTAMP WITH TIME ZONE` | NOT NULL | `internalDate` from Gmail (ms epoch → UTC datetime) |
| `body` | `TEXT` | NOT NULL | Plain-text body; ≤ 100,000 bytes; ends with `[TRUNCATED]` if capped (FR-021) |
| `synced_at` | `TIMESTAMP WITH TIME ZONE` | NOT NULL, default `now()` | Timestamp of first sync into the application |

**Uniqueness rule**: `gmail_message_id` is unique — re-syncing the same message MUST NOT
create a second row (enforced by `INSERT … ON CONFLICT (gmail_message_id) DO NOTHING`, FR-004).

**Body invariant**: The `body` field MUST contain only plain text. No HTML tags, attributes,
or markup are permitted. If the original email body was HTML-only, it MUST have been converted
via `html2text` before storage (FR-005). If the converted text exceeds 100,000 bytes, it is
truncated at the byte boundary and suffixed with `[TRUNCATED]` (FR-021).

**Immutability rule**: No in-place field updates occur after the initial insert. If the Gmail
message is edited or deleted in Gmail after syncing, the stored record is unaffected.

**Default ordering**: Queries for the mail list page order by `received_at DESC`.

---

### MailSyncCursor

Singleton record (always `id = 1`) that tracks the persistent sync state. Stores the lower-bound
timestamp for the next fetch window. The operator can manually override `last_synced_at` from the
UI to trigger re-ingestion from an earlier point (FR-018).

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | `INTEGER` | PK, always `1` | Singleton — only one row ever exists |
| `last_synced_at` | `TIMESTAMP WITH TIME ZONE` | NULLABLE | `NULL` = never synced (first-sync case); set to current UTC time after each successful sync |
| `overlap_minutes` | `INTEGER` | NOT NULL, default `5` | Subtracted from `last_synced_at` when computing the `after:` query parameter (FR-017) |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | NOT NULL, default `now()` | Auto-updated on every write |

**Fetch window computation**:
```
fetch_since = last_synced_at - overlap_minutes
→ Gmail query: after:<unix_epoch_of_fetch_since>
```

**First-sync case**: When `last_synced_at IS NULL`, no `after:` filter is applied; the full
mailbox matching the `mail_filter` setting is fetched. After a successful first sync,
`last_synced_at` is set to the current UTC time.

**Upsert pattern**: Only the single row (`id = 1`) is written. Initialised lazily on first sync
if not already present.

---

### MailSyncRun

Represents a single sync operation — manual or scheduled. Every sync MUST produce a
`MailSyncRun` record. This makes sync history fully auditable and allows operators to diagnose
past failures.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | `INTEGER` | PK, auto-increment | |
| `started_at` | `TIMESTAMP WITH TIME ZONE` | NOT NULL | UTC time when the sync was initiated |
| `finished_at` | `TIMESTAMP WITH TIME ZONE` | NULLABLE | `NULL` while the sync is in progress |
| `outcome` | `VARCHAR(20)` | NULLABLE | `NULL` while in-progress; `success` / `partial` / `failed` on completion |
| `new_count` | `INTEGER` | NOT NULL, default `0` | Number of new emails stored in this run |
| `skipped_count` | `INTEGER` | NOT NULL, default `0` | Number of duplicate emails skipped (already present) |
| `error_message` | `TEXT` | NULLABLE | Human-readable error detail; `NULL` on `success` |
| `triggered_by` | `VARCHAR(20)` | NOT NULL, default `'manual'` | `manual` or `scheduler` |

**Outcome semantics**:

| Value | Meaning |
|---|---|
| `success` | All matching emails were fetched and stored without error; `error_message` is `NULL` |
| `partial` | At least one email was stored before an error halted the sync; `error_message` describes the failure |
| `failed` | No emails were stored and an error occurred; `error_message` describes the failure |
| *(in-progress)* | `finished_at` is `NULL` and `outcome` is `NULL` — sync is currently running |

**Durability rule**: A `MailSyncRun` row is created at the start of every sync (before any
Gmail API call) so that a crashed sync leaves a trace. `finished_at` and `outcome` are updated
atomically on completion.

---

## Settings Table Extensions

The existing `settings` table (introduced in feature 001) gains the following new known keys.
No schema change is required — these are new rows in the existing key-value table.

| Key | Description | Default Value | Notes |
|---|---|---|---|
| `mail_filter` | Gmail search query for qualifying emails | `in:inbox` | Operator-editable on the config page; empty = `in:inbox` (FR-002) |
| `mail_overlap_minutes` | Minutes of overlap window subtracted from cursor on incremental sync | `5` | Read by `run_sync()` at sync time; avoids missing emails near the cursor boundary (FR-017) |
| `mail_poll_interval_minutes` | Background polling interval in minutes; `0` = disabled | `0` | Operator-editable on the config page; changing this value reschedules the APScheduler job at runtime (FR-014) |
| `mail_sync_max_retries` | Maximum Gmail API retry attempts per sync on rate-limit / 5xx | `3` | Used by `tenacity` retry decorator in `GmailAdapter` (FR-010) |

---

## Code Interfaces (Not Persisted)

### MailAdapter *(abstract base class)*

Defines the contract all mail-connector implementations must satisfy (FR-019, Constitution IV).
Lives in `backend/src/services/mail_service.py`.

```python
from abc import ABC, abstractmethod
from datetime import datetime
from dataclasses import dataclass
from enum import Enum

@dataclass
class EmailMessage:
    gmail_message_id: str
    gmail_thread_id: str
    sender_name: str
    sender_email: str
    subject: str
    received_at: datetime
    body_plain_text: str  # already plain text, already truncated

class ConnectorStatus(str, Enum):
    OK = "ok"
    UNCONFIGURED = "unconfigured"
    ERROR = "error"

class MailAdapter(ABC):
    @abstractmethod
    async def fetch_new_emails(
        self,
        since: datetime | None,
        mail_filter: str = "in:inbox",
        max_retries: int = 3,
    ) -> list[EmailMessage]:
        """Fetch emails received on or after `since` matching the configured filter.
        If `since` is None, fetch all matching emails (first-sync case).
        `mail_filter` and `max_retries` are passed explicitly by the orchestration layer."""

    @abstractmethod
    async def get_status(self) -> ConnectorStatus:
        """Return the current connector health without making a full sync API call."""
```

**Constraint**: All sync-orchestration code in `mail_service.py` MUST depend only on `MailAdapter`.
`GmailAdapter` (in `backend/src/adapters/gmail_adapter.py`) MUST NOT be imported directly by
any orchestration or API layer.

### GmailAdapter *(concrete implementation)*

Implements `MailAdapter` using `google-api-python-client` (Gmail REST API v1). Lives in
`backend/src/adapters/gmail_adapter.py`.

Key responsibilities:
- Build `google.oauth2.credentials.Credentials` from `settings` env vars
- Wrap all blocking `googleapiclient` calls in `asyncio.run_in_executor`
- Apply configurable `mail_filter` (from `settings` table) as the Gmail `q=` parameter
- Traverse MIME tree to extract plain-text body (`text/plain` → `text/html` via `html2text`)
- Enforce 100 KB body limit with `[TRUNCATED]` suffix
- Apply `tenacity` retry decorator on HTTP `429` / `5xx` responses
- Raise `google.auth.exceptions.RefreshError` transparently (caught by orchestration layer)

---

## Migrations

| Migration file | Description |
|---|---|
| `0002_create_mail_tables.py` | Creates `incoming_emails`, `mail_sync_cursor`, and `mail_sync_runs` tables |

All migrations are managed by **Alembic** and run automatically at application startup via the
FastAPI lifespan handler (same pattern as feature 001). Migrations are idempotent — safe to
re-run on restart.

---

## Relationships

```
MailSyncCursor (1)
    ← referenced by sync orchestration to compute fetch window
    ← updated at end of each successful MailSyncRun

MailSyncRun (many)
    ← one record per sync operation (manual or scheduled)
    ← each run may insert 0..N IncomingEmail rows

IncomingEmail (many)
    ← deduplication enforced via UNIQUE(gmail_message_id)
    ← no foreign key to MailSyncRun (emails are standalone records)

settings (existing)
    ← extended with mail_filter, mail_poll_interval_minutes, mail_sync_max_retries
```

There are no foreign-key relationships between `incoming_emails` and `mail_sync_runs` — emails
are standalone records not tied to the run that first inserted them. This simplifies deletion
(hard-delete of an email has no cascade effects).
