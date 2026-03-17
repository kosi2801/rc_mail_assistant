"""Mail service — interface layer, orchestration, and stubs (no GmailAdapter import)."""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------


@dataclass
class EmailMessage:
    """Plain-text representation of a fetched email (already ≤ 100 KB)."""

    gmail_message_id: str
    gmail_thread_id: str
    sender_name: str
    sender_email: str
    subject: str
    received_at: datetime
    body_plain_text: str  # already plain text, already ≤ 100 KB


class ConnectorStatus(str, Enum):
    OK = "ok"
    UNCONFIGURED = "unconfigured"
    ERROR = "error"
    TOKEN_ERROR = "token_error"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class SyncAlreadyRunningError(Exception):
    """Raised when run_sync() is called while a sync is already in progress."""


class MailCredentialsError(Exception):
    """Raised when Gmail credentials are missing or invalid."""


# ---------------------------------------------------------------------------
# Abstract adapter interface
# ---------------------------------------------------------------------------


class MailAdapter(ABC):
    """Abstract interface — no dependency on any concrete implementation."""

    @abstractmethod
    async def fetch_new_emails(
        self,
        since: datetime | None,
        mail_filter: str = "in:inbox",
        max_retries: int = 3,
    ) -> list[EmailMessage]:
        """Fetch emails received ≥ since matching the configured filter.

        Args:
            since: Lower-bound datetime (UTC). ``None`` = first-sync, no date lower bound.
            mail_filter: Gmail search query (default: ``"in:inbox"``).
            max_retries: Maximum retry attempts for retriable API errors (default: 3).

        Returns:
            List of EmailMessage objects.
        """

    @abstractmethod
    async def get_status(self) -> ConnectorStatus:
        """Credential presence check — no outbound API call (FR-016)."""


# ---------------------------------------------------------------------------
# NullMailAdapter — no-op stub used when GmailAdapter instantiation fails
# ---------------------------------------------------------------------------


class NullMailAdapter(MailAdapter):
    """Concrete stub stored on app.state.mail_adapter when GmailAdapter init fails.

    The app starts successfully but every sync attempt surfaces a descriptive
    credential error, enabling the coordinator to fix the .env without a redeploy.
    """

    async def fetch_new_emails(
        self,
        since: datetime | None,
        mail_filter: str = "in:inbox",
        max_retries: int = 3,
    ) -> list[EmailMessage]:
        raise MailCredentialsError(
            "Gmail credentials could not be loaded. "
            "Check GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, and GMAIL_REFRESH_TOKEN in .env."
        )

    async def get_status(self) -> ConnectorStatus:
        return ConnectorStatus.UNCONFIGURED


# ---------------------------------------------------------------------------
# Orchestration (added by T009)
# ---------------------------------------------------------------------------

# Module-level lock — ensures only one sync runs at a time (research §10)
_sync_lock = asyncio.Lock()


def is_sync_running() -> bool:
    """Return True if a sync is currently in progress."""
    return _sync_lock.locked()


async def run_sync(
    adapter: MailAdapter,
    session,  # AsyncSession — avoid hard import cycle; type checked at runtime
    triggered_by: str = "manual",
):
    """Orchestrate a full mail sync.

    Steps:
    1. Guard against concurrent execution.
    2. Acquire lock and create MailSyncRun audit row (flush immediately).
    3. Determine ``since`` from MailSyncCursor (id=1).
    4. Fetch emails from the adapter.
    5. Bulk-insert with ON CONFLICT DO NOTHING; commit every 50 rows.
    6. On success: upsert cursor, set outcome="success", commit.
    7. On error: set outcome accordingly, do NOT advance cursor, commit.
    8. Release lock and return the MailSyncRun record.
    """
    from datetime import timezone, timedelta

    import google.auth.exceptions
    from googleapiclient.errors import HttpError
    from sqlalchemy import select
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from src.models.mail import IncomingEmail, MailSyncCursor, MailSyncRun

    if _sync_lock.locked():
        raise SyncAlreadyRunningError("A sync is already in progress.")

    async with _sync_lock:
        from src.logging_config import get_logger

        logger = get_logger(__name__)

        utcnow = lambda: datetime.now(tz=timezone.utc)  # noqa: E731

        # --- Step 3: Create audit row ---
        run = MailSyncRun(started_at=utcnow(), triggered_by=triggered_by)
        session.add(run)
        await session.flush()  # persist so it survives a crash

        # --- Step 4: Compute since ---
        result = await session.execute(
            select(MailSyncCursor).where(MailSyncCursor.id == 1)
        )
        cursor = result.scalar_one_or_none()

        # Read overlap_minutes from settings table (authoritative source — FR-017, U3 fix)
        from src.models.settings import Setting  # noqa: PLC0415

        async def _get_setting(key: str, default: str) -> str:
            row = (await session.execute(select(Setting).where(Setting.key == key))).scalar_one_or_none()
            return row.value if row and row.value else default

        try:
            overlap_minutes = int(await _get_setting("mail_overlap_minutes", "5"))
        except ValueError:
            overlap_minutes = 5

        mail_filter = await _get_setting("mail_filter", "in:inbox")
        try:
            max_retries = int(await _get_setting("mail_sync_max_retries", "3"))
        except ValueError:
            max_retries = 3

        since: datetime | None = None
        if cursor is not None and cursor.last_synced_at is not None:
            since = cursor.last_synced_at - timedelta(minutes=overlap_minutes)

        # --- Step 5: Fetch ---
        try:
            emails = await adapter.fetch_new_emails(
                since=since,
                mail_filter=mail_filter,
                max_retries=max_retries,
            )
        except (
            google.auth.exceptions.RefreshError,
            google.auth.exceptions.TransportError,
            MailCredentialsError,
        ) as exc:
            run.outcome = "failed"
            run.error_message = str(exc)
            run.finished_at = utcnow()
            await session.commit()
            logger.error("mail_sync_failed", outcome="failed", error=str(exc))
            return run
        except HttpError as exc:
            run.outcome = "failed"
            run.error_message = str(exc)
            run.finished_at = utcnow()
            await session.commit()
            logger.error("mail_sync_failed", outcome="failed", error=str(exc))
            return run

        # --- Step 6: Persist with dedup ---
        new_count = 0
        skipped_count = 0
        batch: list[EmailMessage] = []
        all_emails = list(emails)

        try:
            for i, email in enumerate(all_emails):
                stmt = (
                    pg_insert(IncomingEmail)
                    .values(
                        gmail_message_id=email.gmail_message_id,
                        gmail_thread_id=email.gmail_thread_id,
                        sender_name=email.sender_name,
                        sender_email=email.sender_email,
                        subject=email.subject,
                        received_at=email.received_at,
                        body=email.body_plain_text,
                    )
                    .on_conflict_do_nothing(index_elements=["gmail_message_id"])
                )
                result = await session.execute(stmt)
                if result.rowcount == 1:
                    new_count += 1
                else:
                    skipped_count += 1

                # Commit every 50 to preserve partial progress (FR-010)
                if (i + 1) % 50 == 0:
                    await session.commit()

            # Final commit for remaining rows
            await session.commit()

        except HttpError as exc:
            run.outcome = "partial" if new_count > 0 else "failed"
            run.new_count = new_count
            run.skipped_count = skipped_count
            run.error_message = str(exc)
            run.finished_at = utcnow()
            await session.commit()
            logger.error(
                "mail_sync_http_error",
                outcome=run.outcome,
                new_count=new_count,
                error=str(exc),
            )
            return run

        # --- Step 7: Update cursor on full success ---
        cursor_row = await session.execute(
            select(MailSyncCursor).where(MailSyncCursor.id == 1)
        )
        existing_cursor = cursor_row.scalar_one_or_none()
        if existing_cursor is None:
            session.add(MailSyncCursor(id=1, last_synced_at=utcnow(), overlap_minutes=5))
        else:
            existing_cursor.last_synced_at = utcnow()
            existing_cursor.updated_at = utcnow()

        run.outcome = "success"
        run.new_count = new_count
        run.skipped_count = skipped_count
        run.finished_at = utcnow()
        await session.commit()

        logger.info(
            "mail_sync_complete",
            outcome="success",
            new_count=new_count,
            skipped_count=skipped_count,
        )
        return run
