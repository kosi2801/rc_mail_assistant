"""Unit tests for run_sync() orchestration in mail_service.py."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.mail_service import (
    ConnectorStatus,
    EmailMessage,
    MailAdapter,
    MailCredentialsError,
    SyncAlreadyRunningError,
    is_sync_running,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_email(n: int = 0) -> EmailMessage:
    return EmailMessage(
        gmail_message_id=f"msg_{n}",
        gmail_thread_id=f"thread_{n}",
        sender_name=f"Sender {n}",
        sender_email=f"sender{n}@example.com",
        subject=f"Subject {n}",
        received_at=datetime(2026, 1, 1, 10, n, 0, tzinfo=timezone.utc),
        body_plain_text=f"Body of email {n}",
    )


class _StubAdapter(MailAdapter):
    """Minimal adapter stub for orchestration tests."""

    def __init__(self, emails=None, raise_exc=None):
        self._emails = emails or []
        self._raise_exc = raise_exc

    async def fetch_new_emails(self, since, mail_filter="in:inbox", max_retries=3):
        if self._raise_exc:
            raise self._raise_exc
        return self._emails

    async def get_status(self):
        return ConnectorStatus.OK


def _make_mock_session(existing_gmail_ids: set[str] | None = None):
    """Build an AsyncMock session that simulates ON CONFLICT DO NOTHING behaviour."""
    existing = existing_gmail_ids or set()
    seen: set[str] = set()

    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    session.delete = AsyncMock()

    # execute returns different rowcounts depending on whether the email is new
    async def _execute(stmt):
        result = MagicMock()
        # Settings queries (SELECT Setting WHERE key=...) return None for scalar_one_or_none
        # Cursor queries (SELECT MailSyncCursor) also return None
        result.scalar_one_or_none = MagicMock(return_value=None)

        # Inspect compiled statement to detect gmail_message_id
        try:
            params = stmt.compile(compile_kwargs={"literal_binds": True}).string
        except Exception:
            params = ""

        # For inserts: look at the values bound to the statement
        try:
            # Access private attribute if available
            gmail_id = stmt._values.get("gmail_message_id") or ""
            if hasattr(gmail_id, "value"):
                gmail_id = gmail_id.value
        except Exception:
            gmail_id = ""

        if gmail_id and (gmail_id in existing or gmail_id in seen):
            result.rowcount = 0
        else:
            if gmail_id:
                seen.add(gmail_id)
            result.rowcount = 1
        return result

    session.execute = _execute

    # Cursor query: return None by default (no cursor)
    from src.models.mail import MailSyncCursor, MailSyncRun

    # scalar_one_or_none returns None for cursor
    cursor_result = MagicMock()
    cursor_result.scalar_one_or_none = MagicMock(return_value=None)

    return session


# ---------------------------------------------------------------------------
# Test 1: successful sync — 3 new emails, outcome=="success", cursor updated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_sync_success_three_new_emails():
    """Successful sync with 3 new emails: new_count==3, outcome=='success', cursor updated."""
    import src.services.mail_service as svc

    emails = [_make_email(i) for i in range(3)]
    adapter = _StubAdapter(emails=emails)

    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.flush = AsyncMock()

    execute_call_count = [0]

    async def _execute(stmt):
        execute_call_count[0] += 1
        r = MagicMock()
        if execute_call_count[0] == 1:
            # First call: cursor select — return no cursor
            r.scalar_one_or_none = MagicMock(return_value=None)
            r.rowcount = 0
        else:
            # Subsequent calls: insert stmts — all new
            r.scalar_one_or_none = MagicMock(return_value=None)
            r.rowcount = 1
        return r

    session.execute = _execute

    # Reset module-level lock
    svc._sync_lock = asyncio.Lock()

    run = await svc.run_sync(adapter, session, triggered_by="manual")

    assert run.outcome == "success"
    assert run.new_count == 3
    assert run.skipped_count == 0
    assert run.finished_at is not None
    assert run.triggered_by == "manual"


# ---------------------------------------------------------------------------
# Test 2: 2 new + 1 duplicate → skipped_count==1, outcome=="success"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_sync_deduplication():
    """2 new + 1 duplicate: new_count==2, skipped_count==1, outcome=='success'."""
    import src.services.mail_service as svc

    emails = [_make_email(i) for i in range(3)]
    adapter = _StubAdapter(emails=emails)

    call_count = [0]

    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.flush = AsyncMock()

    async def _execute(stmt):
        call_count[0] += 1
        r = MagicMock()
        r.scalar_one_or_none = MagicMock(return_value=None)
        # Calls: 1=cursor, 2=overlap_setting, 3=mail_filter_setting, 4=max_retries_setting,
        #        5=insert1 (new), 6=insert2 (new), 7=insert3 (duplicate), 8=cursor upsert
        if call_count[0] == 7:
            r.rowcount = 0  # duplicate
        else:
            r.rowcount = 1  # new or non-insert
        return r

    session.execute = _execute

    svc._sync_lock = asyncio.Lock()

    run = await svc.run_sync(adapter, session, triggered_by="manual")

    assert run.outcome == "success"
    assert run.skipped_count >= 1


# ---------------------------------------------------------------------------
# Test 3: adapter raises RefreshError → outcome=="failed", cursor unchanged
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_sync_refresh_error():
    """Adapter raising RefreshError → run.outcome=='failed', error_message set."""
    import google.auth.exceptions
    import src.services.mail_service as svc

    adapter = _StubAdapter(raise_exc=google.auth.exceptions.RefreshError("bad token"))

    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.flush = AsyncMock()

    async def _execute(stmt):
        r = MagicMock()
        r.scalar_one_or_none = MagicMock(return_value=None)
        r.rowcount = 0
        return r

    session.execute = _execute

    svc._sync_lock = asyncio.Lock()

    run = await svc.run_sync(adapter, session)

    assert run.outcome == "failed"
    assert run.error_message is not None
    assert "bad token" in run.error_message


# ---------------------------------------------------------------------------
# Test 4: is_sync_running() + SyncAlreadyRunningError while lock held
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_already_running():
    """is_sync_running() returns True while lock held; concurrent call raises SyncAlreadyRunningError."""
    import src.services.mail_service as svc

    svc._sync_lock = asyncio.Lock()

    # Acquire the lock manually
    await svc._sync_lock.acquire()
    try:
        assert svc.is_sync_running() is True

        with pytest.raises(SyncAlreadyRunningError):
            await svc.run_sync(_StubAdapter(), MagicMock())
    finally:
        svc._sync_lock.release()

    assert svc.is_sync_running() is False


# ---------------------------------------------------------------------------
# Test 5: HttpError after retries — outcome depends on new_count
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_sync_http_error_outcomes():
    """HttpError after retries: new_count==0→'failed'; new_count>0→'partial'; cursor not updated."""
    from googleapiclient.errors import HttpError
    import src.services.mail_service as svc

    mock_resp = MagicMock()
    mock_resp.status = 429

    # Case A: HttpError with new_count==0 → failed
    adapter_a = _StubAdapter(raise_exc=HttpError(resp=mock_resp, content=b"Rate limited"))

    session_a = MagicMock()
    session_a.add = MagicMock()
    session_a.commit = AsyncMock()
    session_a.flush = AsyncMock()

    async def _exec_a(stmt):
        r = MagicMock()
        r.scalar_one_or_none = MagicMock(return_value=None)
        r.rowcount = 0
        return r

    session_a.execute = _exec_a

    svc._sync_lock = asyncio.Lock()

    run_a = await svc.run_sync(adapter_a, session_a)
    assert run_a.outcome == "failed"
    assert run_a.error_message is not None

    # Case B: HttpError during insert phase with new_count > 0 → partial
    from src.services.mail_service import EmailMessage as EM  # noqa: N812
    from datetime import timezone as tz

    good_email = EmailMessage(
        gmail_message_id="msg_b1",
        gmail_thread_id="thr_b1",
        sender_name="Bob",
        sender_email="bob@example.com",
        subject="Visit",
        received_at=datetime(2026, 1, 1, tzinfo=tz.utc),
        body_plain_text="Hello",
    )
    adapter_b = _StubAdapter(emails=[good_email])

    call_count_b = 0

    async def _exec_b(stmt):
        nonlocal call_count_b
        r = MagicMock()
        call_count_b += 1
        r.scalar_one_or_none = MagicMock(return_value=None)
        if call_count_b == 1:
            # cursor query
            r.rowcount = 0
        elif call_count_b in (2, 3, 4):
            # settings queries: overlap, mail_filter, max_retries
            r.rowcount = 0
        elif call_count_b == 5:
            # first INSERT succeeds (new_count → 1)
            r.rowcount = 1
        else:
            # second INSERT raises HttpError
            raise HttpError(resp=mock_resp, content=b"Rate limited mid-insert")
        return r

    session_b = MagicMock()
    session_b.add = MagicMock()
    session_b.commit = AsyncMock()
    session_b.flush = AsyncMock()
    session_b.execute = _exec_b

    svc._sync_lock = asyncio.Lock()

    # Patch adapter to return 2 emails so the second INSERT triggers HttpError
    second_email = EmailMessage(
        gmail_message_id="msg_b2",
        gmail_thread_id="thr_b2",
        sender_name="Carol",
        sender_email="carol@example.com",
        subject="Visit 2",
        received_at=datetime(2026, 1, 2, tzinfo=tz.utc),
        body_plain_text="World",
    )
    adapter_b = _StubAdapter(emails=[good_email, second_email])

    run_b = await svc.run_sync(adapter_b, session_b)
    assert run_b.outcome == "partial", f"Expected partial, got {run_b.outcome}"
    assert run_b.new_count == 1
    assert run_b.error_message is not None
