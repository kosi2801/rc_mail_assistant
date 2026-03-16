# Tasks: Gmail Mail Sync

**Feature Branch**: `002-gmail-mail-sync`  
**Input**: Design artifacts from `specs/002-gmail-mail-sync/` — spec.md, plan.md, data-model.md,
contracts/mail.md, research.md, quickstart.md  
**Output path**: `specs/002-gmail-mail-sync/tasks.md`  
**Generated**: 2026-02-28

---

## Format: `[ID] [P?] [US#?] Description with file path`

- **[P]**: Task is parallelisable — operates on a different file than its phase siblings, no
  incomplete task dependencies
- **[US#]**: User story label — maps to US1/US2/US3 from spec.md
- **Setup and Foundational phases**: no story label (cross-cutting infrastructure)
- Every task includes an exact file path

---

## Phase 1: Setup

**Purpose**: Extend the existing feature-001 project with the new package and dependencies
required by the Gmail mail sync feature. No application logic yet.

- [X] T001 Add new dependencies to `backend/pyproject.toml`: `google-api-python-client>=2.0`, `google-auth>=2.0`, `google-auth-httplib2>=0.1`, `html2text>=2024.2`, `apscheduler>=3.10,<4.0`, `tenacity>=8.3`
- [X] T002 [P] Create `backend/src/adapters/__init__.py` as empty package init file (establishes the new `src/adapters/` package required by plan.md Constitution IV)

**Checkpoint**: Dependencies declared; `pip install -e .` succeeds; `src/adapters/` package importable.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core models, interface definition, migration, and config API extension that ALL user
stories depend on. No user story work may begin until this phase is complete.

**⚠️ CRITICAL**: T003 → T005 are sequential. T004, T006, T007 are independent and can run in
parallel with each other (but must wait for T001/T002).

- [X] T003 Create `backend/src/models/mail.py` with three SQLAlchemy 2.x async ORM models:
  **`IncomingEmail`** (`id` PK, `gmail_message_id` VARCHAR(255) UNIQUE NOT NULL indexed,
  `gmail_thread_id` VARCHAR(255) NOT NULL, `sender_name` VARCHAR(255) NOT NULL,
  `sender_email` VARCHAR(255) NOT NULL, `subject` TEXT NOT NULL, `received_at`
  TIMESTAMP WITH TIME ZONE NOT NULL, `body` TEXT NOT NULL, `synced_at` TIMESTAMP WITH TIME ZONE
  NOT NULL server_default=now()); **`MailSyncCursor`** (`id` PK always 1 — singleton,
  `last_synced_at` TIMESTAMP WITH TIME ZONE NULLABLE, `overlap_minutes` INTEGER NOT NULL
  default 5, `updated_at` TIMESTAMP WITH TIME ZONE NOT NULL server_default=now()
  onupdate=now()); **`MailSyncRun`** (`id` PK, `started_at` TIMESTAMP WITH TIME ZONE NOT NULL,
  `finished_at` TIMESTAMP WITH TIME ZONE NULLABLE, `outcome` VARCHAR(20) NULLABLE —
  `success`/`partial`/`failed`, `new_count` INTEGER NOT NULL default 0, `skipped_count` INTEGER
  NOT NULL default 0, `error_message` TEXT NULLABLE, `triggered_by` VARCHAR(20) NOT NULL
  default `'manual'`). Import all three into `backend/src/models/__init__.py` so Alembic
  autogenerate detects them.

- [X] T004 [P] Extend `backend/src/models/settings.py` — add `"mail_filter"`,
  `"mail_poll_interval_minutes"`, `"mail_sync_max_retries"`, and `"mail_overlap_minutes"` to
  the `KNOWN_KEYS` frozenset. These four keys are validated by `config_service.upsert` on every
  POST /config call; no other code change is needed in this file.

- [X] T005 Create `backend/migrations/versions/0002_create_mail_tables.py` as an Alembic migration
  (revision id `0002`, down_revision points to the feature-001 head revision found in
  `backend/migrations/versions/`). `upgrade()` must: create `incoming_emails` table with all
  columns from T003 and a UNIQUE index on `gmail_message_id`; create `mail_sync_cursor` table;
  create `mail_sync_runs` table. `downgrade()` must drop all three tables in reverse order.
  Migration is idempotent — the FastAPI lifespan runs `alembic upgrade head` on every restart.

- [X] T006 [P] Create `backend/src/services/mail_service.py` — interface layer only (no
  orchestration). Define: `@dataclass EmailMessage` with fields `gmail_message_id: str`,
  `gmail_thread_id: str`, `sender_name: str`, `sender_email: str`, `subject: str`,
  `received_at: datetime`, `body_plain_text: str` (already plain text, already ≤ 100 KB);
  `class ConnectorStatus(str, Enum)` with values `OK = "ok"`, `UNCONFIGURED = "unconfigured"`,
  `ERROR = "error"`; `class MailAdapter(ABC)` with two abstract async methods:
  `fetch_new_emails(self, since: datetime | None) -> list[EmailMessage]` (fetch emails received
  ≥ `since` matching the configured filter; `since=None` = first-sync, no date lower bound)
  and `get_status(self) -> ConnectorStatus` (credential presence check, no outbound API call).
  Also define `class SyncAlreadyRunningError(Exception): pass` and
  `class MailCredentialsError(Exception): pass` for use by the orchestration layer.
  Also define `class NullMailAdapter(MailAdapter)` — a concrete no-op stub whose
  `fetch_new_emails` always raises `MailCredentialsError("Gmail credentials could not be
  loaded. Check GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, and GMAIL_REFRESH_TOKEN in .env.")` and
  whose `get_status()` always returns `ConnectorStatus.UNCONFIGURED`. This stub is stored as
  `app.state.mail_adapter` when `GmailAdapter` instantiation fails at startup (see T013), so
  the app starts but every sync attempt surfaces a descriptive credential error.
  No imports from `GmailAdapter` — the interface must never depend on any concrete
  implementation.

- [X] T007 [P] Extend `backend/src/api/config.py` — add `mail_filter: str | None = Form(None)`,
  `mail_poll_interval_minutes: str | None = Form(None)`, `mail_sync_max_retries: str | None = Form(None)`,
  and `mail_overlap_minutes: str | None = Form(None)` parameters to the `save_config()` handler.
  Add these four keys to the `raw` dict and the existing `updates` filter (skip None and "").
  No scheduler integration yet — that is added in T023.

**Checkpoint**: All three ORM models importable; `alembic upgrade head` creates all three tables;
`POST /config` with `mail_filter=in:inbox` returns 200; `MailAdapter` ABC importable.

---

## Phase 3: User Story 1 — Sync Visit Request Emails (P1) 🎯 MVP

**Goal**: A coordinator clicks "Sync Mail", the system connects to Gmail via OAuth, fetches all
new emails matching the configured filter, stores each as a plain-text `IncomingEmail` record
(deduped by `gmail_message_id`), and reports new/skipped counts and any errors.

**Independent Test** (from spec.md): Click "Sync Mail" on a running instance connected to a Gmail
account with at least one unsynced email. Verify the email appears in the DB with correct sender,
subject, date, and plain-text body. Run sync a second time — verify zero new records and no
duplicates.

**Acceptance**: FR-001, FR-002, FR-003, FR-004, FR-005, FR-006, FR-007, FR-008, FR-009, FR-010,
FR-017, FR-018, FR-019, FR-021, FR-022

- [X] T008 [US1] Create `backend/src/adapters/gmail_adapter.py` — full `GmailAdapter(MailAdapter)`
  implementation. **Credential construction** (research §1): `build_credentials()` builds
  `google.oauth2.credentials.Credentials` from `settings.gmail_client_id`,
  `settings.gmail_client_secret`, `settings.gmail_refresh_token`; calls `creds.refresh(Request())`
  eagerly to fail fast on bad creds. **Service construction** (research §2): `__init__` calls
  `build("gmail", "v1", credentials=creds, cache_discovery=False)` and stores the service as
  `self._svc`; all blocking API calls are wrapped with
  `await loop.run_in_executor(None, lambda: ...)` using `asyncio.get_event_loop()`.
  **`fetch_new_emails(since)`** (research §3): reads `mail_filter` setting from DB (default
  `"in:inbox"`); if `since` is not None, reads `mail_overlap_minutes` setting from DB (default
  `5`, coerced to int) and subtracts that duration from `since`, then appends
  `after:<unix_epoch>` to the query; calls `messages.list(userId="me",
  q=<filter>)` and paginates via `nextPageToken` until exhausted; for each message ID calls
  `messages.get(userId="me", id=..., format="full")` and passes the result to
  `_extract_email(msg_data)`; returns list of `EmailMessage`. **`_extract_email()`** (research
  §6): reads `internalDate` (ms epoch → UTC datetime); parses `From:` header into sender name
  and address; reads `Subject:` header (empty string if absent); recursively traverses
  `payload.parts` preferring `text/plain`, falling back to `text/html` via `_html_to_text()`;
  decodes URL-safe base64 body with padding fix (`data + "=="`); applies 100 KB truncation:
  if `len(body.encode()) > 100_000` slice at byte boundary and append `" [TRUNCATED]"`
  (FR-021). **`_html_to_text()`** (research §7): `html2text.HTML2Text()` with
  `ignore_links=True`, `ignore_images=True`, `ignore_emphasis=True`, `body_width=0`,
  `skip_internal_links=True`; returns `.handle(html).strip()`. **Retry decorator** (research §4):
  apply `@retry(wait=wait_exponential(multiplier=1, min=2, max=30),
  stop=stop_after_attempt(settings_max_retries), retry=retry_if_exception(...))` from `tenacity`
  on the inner `_execute(request)` helper — retries on `HttpError` with `.resp.status` in
  `(429, 500, 503)`. Parse `mail_sync_max_retries` as
  `int(settings_row.get("mail_sync_max_retries") or "3")` — catch `ValueError` and fallback to
  `3` (U5: all settings are stored as strings; coerce to int at point of use). **`get_status()`**: returns `ConnectorStatus.UNCONFIGURED` if any
  `GMAIL_*` env var is absent; `ConnectorStatus.OK` otherwise (no outbound call — FR-016).
  **Error handling**: catch `google.auth.exceptions.RefreshError` and re-raise as a typed
  exception (caught by the orchestration layer in T009).

- [X] T009 [US1] Extend `backend/src/services/mail_service.py` — add sync orchestration. Add
  module-level `_sync_lock = asyncio.Lock()`. Add `is_sync_running() -> bool` that returns
  `_sync_lock.locked()`. Add `async def run_sync(adapter: MailAdapter, session: AsyncSession,
  triggered_by: str = "manual") -> MailSyncRun` with the following steps: (1) if
  `_sync_lock.locked()` raise `SyncAlreadyRunningError`; (2) acquire `_sync_lock`; (3) create
  `MailSyncRun(started_at=utcnow(), triggered_by=triggered_by)` and flush to DB so the row
  exists even if the process crashes; (4) fetch `MailSyncCursor` row (id=1); compute `since =
  cursor.last_synced_at - timedelta(minutes=overlap_minutes)` (where `overlap_minutes` =
  `int(settings.get("mail_overlap_minutes") or "5")`) if cursor exists and
  `last_synced_at` is not None, else `since = None`; (5) call
  `emails = await adapter.fetch_new_emails(since=since)` inside try/except; (6) for each
  `EmailMessage` execute `INSERT INTO incoming_emails … ON CONFLICT (gmail_message_id) DO
  NOTHING` via SQLAlchemy core; accumulate `new_count` (rowcount==1) and `skipped_count`
  (rowcount==0); commit after each batch of 50 to preserve partial progress (FR-010); (7) on
  full success: upsert `MailSyncCursor(id=1, last_synced_at=utcnow())`, set run
  `outcome="success"`, `finished_at=utcnow()`, commit; (8) on `RefreshError`, `google.auth.exceptions.TransportError`, or `MailCredentialsError`: set `outcome="failed"`, `error_message=str(e)`,
  `finished_at=utcnow()`, commit — cursor NOT updated; (9) on `HttpError` after retries
  exhausted: if `new_count > 0` set `outcome="partial"` else `outcome="failed"`, set
  `error_message`, `finished_at=utcnow()`, commit — cursor NOT updated; (10) release lock and
  return the `MailSyncRun` record.

- [X] T010 [P] [US1] Create `backend/src/templates/mail_sync_result.html` — HTMX fragment (no
  `<html>`/`<body>` wrapper). Renders the sync outcome inline in the mail list page. Four
  variants driven by `run.outcome`: **success** — green badge "✓ success", "N new email(s)
  fetched", "N duplicate(s) skipped", timestamp of `run.finished_at`; **partial** — amber
  badge "⚠ partial", emails stored count, error detail from `run.error_message`; **failed** —
  red badge "✗ failed", "0 new emails", error detail; **in_progress** (outcome is `None`) —
  blue badge "⟳ Sync already in progress". The template MUST use
  `{% if run.outcome is none %}…in_progress…{% elif run.outcome == "success" %}…{% endif %}`
  branching so that `run` is always a `MailSyncRun` ORM object (or a sentinel with
  `outcome=None`) — never `None` itself. When returning the in-progress fragment (T012), pass
  a lightweight sentinel: `{"outcome": None, "new_count": 0, "skipped_count": 0,
  "error_message": None, "finished_at": None}` as `run`.

- [X] T011 [P] [US1] Create `backend/src/templates/mail_sync_status.html` — HTMX polling
  fragment returned by `GET /mail/sync/status`. Two states: **syncing** (`is_syncing=True`) —
  renders the "Sync Mail" button as `<button disabled …>⟳ Syncing…</button>` with a spinner
  indicator (FR-022); **idle** (`is_syncing=False`) — renders the "Sync Mail" button as
  enabled with its normal label, plus the last-run summary (timestamp, outcome badge, counts)
  from `last_run` context variable (None if no run exists). The fragment must be swappable via
  HTMX `hx-swap="outerHTML"` on the button's container div.

- [X] T012 [US1] Create `backend/src/api/mail.py` — initial file with two endpoints.
  **`POST /mail/sync`**: depends `session: AsyncSession`, `request: Request`; check
  `is_sync_running()` — if True return `mail_sync_result.html` fragment with `in_progress`
  state (no new `MailSyncRun`); otherwise call `await run_sync(adapter, session)` where
  `adapter = request.app.state.mail_adapter`; return `TemplateResponse("mail_sync_result.html",
  {"request": request, "run": run})` as `HTMLResponse`. **`GET /mail/sync/status`**: return
  `TemplateResponse("mail_sync_status.html", {"request": request, "is_syncing":
  is_sync_running(), "last_run": last_run})` where `last_run` is queried as the most recent
  `MailSyncRun` row ordered by `started_at DESC` limit 1. Both endpoints use
  `response_class=HTMLResponse`. Add module-level `router = APIRouter(tags=["mail"])`.

- [X] T013 [US1] Extend `backend/src/main.py` — wire mail adapter and register router. In the
  lifespan `asynccontextmanager`: after `startup_db_ok`, import `GmailAdapter` from
  `src.adapters.gmail_adapter`, instantiate it with credentials built from `settings`, store as
  `app.state.mail_adapter`; if instantiation raises `RefreshError` or `MailCredentialsError` log a warning and store a
  `NullMailAdapter` stub (so the app starts but sync fails with a descriptive error). After the
  yield (shutdown): no cleanup needed for the adapter. Outside lifespan: import and register
  `from src.api import mail as mail_router` and call
  `app.include_router(mail_router.router)`. Keep all existing routers and exception handlers
  unchanged.

- [X] T014 [P] [US1] Extend `backend/src/templates/base.html` — add a "Mail" navigation link to
  the sidebar/nav bar pointing to `/mail`. Follow the same style/class pattern as the existing
  "Config" and "Health" links. The link should be visually active when the current path starts
  with `/mail`.

- [X] T015 [P] [US1] [SC-003] Create `backend/tests/unit/test_gmail_adapter.py` — unit tests for
  `GmailAdapter` internals (no real Gmail API calls; mock `googleapiclient`). Test cases:
  (1) `_extract_email` with multipart/alternative payload returns `text/plain` part verbatim;
  (2) `_extract_email` with HTML-only payload returns `html2text`-converted plain text with no
  tags; (3) `_extract_email` with empty body returns empty string (not an error);
  (4) body exactly at 100,000 bytes is stored without truncation; body at 100,001 bytes is
  truncated at 100,000 bytes and ends with `" [TRUNCATED]"`;
  (5) URL-safe base64 without padding is decoded correctly when `"=="` is appended;
  (6) `_html_to_text` strips `<a href>` link URLs (ignore_links=True) and tracking pixel
  `<img>` tags.

- [X] T016 [P] [US1] [SC-002] Create `backend/tests/unit/test_mail_service.py` — unit tests for
  `run_sync()` orchestration using a `MailAdapter` stub (subclass with known return values).
  Test cases: (1) successful sync with 3 new emails creates 3 `IncomingEmail` rows,
  `MailSyncRun.outcome == "success"`, cursor updated to ≈ utcnow();
  (2) sync with 2 new + 1 duplicate stores 2 rows, skipped_count==1, outcome=="success";
  (3) adapter raises `RefreshError` → run outcome=="failed", error_message set, cursor
  unchanged; (4) `is_sync_running()` returns True while `_sync_lock` is held; calling
  `run_sync()` concurrently raises `SyncAlreadyRunningError`; (5) adapter raises `HttpError`
  after all retries with `new_count==0` → outcome=="failed"; with `new_count>0` →
  outcome=="partial"; cursor not updated in either case.

**Checkpoint**: `POST /mail/sync` with valid Gmail creds fetches emails and stores them;
second sync reports 0 new + N skipped; `GET /mail/sync/status` reflects live lock state;
`pytest tests/unit/test_gmail_adapter.py tests/unit/test_mail_service.py` all pass.

---

## Phase 4: User Story 2 — Browse Stored Visit Request Emails (P2)

**Goal**: A coordinator opens `/mail`, sees all stored emails newest-first with sender, subject,
and date. Clicking a row shows the full plain-text body. An empty-state message is shown when
no emails exist. Emails can be permanently deleted with a confirmation prompt. The sync cursor
can be manually reset.

**Independent Test** (from spec.md): Seed ≥ 3 `IncomingEmail` rows directly into the DB.
Load `/mail` — all rows appear in reverse chronological order with correct metadata. Click a row —
full body displays with no HTML. Delete one row with confirmation — row disappears, 404 on
re-access.

**Acceptance**: FR-011, FR-012, FR-013, FR-018, FR-020, FR-021

- [X] T017 [P] [US2] Create `backend/src/templates/mail_list.html` — full HTML page (extends
  `base.html`). Contents: (1) page heading "Mail"; (2) "Sync Mail" button container — initially
  rendered by `GET /mail/sync/status` fragment; use `hx-get="/mail/sync/status"
  hx-trigger="load, every 3s" hx-swap="outerHTML"` on the container so the button state
  self-updates while a sync is in progress (FR-022); (3) last-sync summary section — outcome
  badge, counts, timestamp from `last_run` context (omit section if `last_run` is None);
  (4) **empty-state**: when `emails` list is empty, display the message: *"No emails have been
  synced yet. Click "Sync Mail" to fetch your first batch."* (FR-013); (5) **email table**:
  one row per `IncomingEmail` — `sender_name`, `subject`, `received_at` (formatted as
  `YYYY-MM-DD HH:mm`); each row is a link to `GET /mail/{email.id}`; table is ordered newest
  first (rendered from the `emails` context list which is already `ORDER BY received_at DESC`);
  (6) **Advanced section** — collapsible `<details><summary>Advanced</summary>` block containing
  a "Reset sync cursor" form: a datetime-local input `name="last_synced_at"` pre-populated with
  `cursor.last_synced_at` (ISO 8601 format, empty if None) plus an "empty = full re-sync"
  hint, and a "Reset cursor" submit button that POSTs to `POST /mail/cursor` via HTMX with a
  confirmation note: *"The next sync will fetch emails from this date forward."* (FR-018).

- [X] T018 [P] [US2] Create `backend/src/templates/mail_detail.html` — full HTML page (extends
  `base.html`). Contents: (1) breadcrumb "← Back to mail list" linking to `/mail`; (2) metadata
  block: sender name, sender email address, subject, received date/time (human-readable local
  format), synced date/time; (3) body block: `<pre>{{ email.body }}</pre>` — preformatted plain
  text; if body ends with `" [TRUNCATED]"` render a visible amber notice: *"This email body was
  truncated at 100 KB."* (FR-021); (4) delete section: `<button hx-delete="/mail/{{ email.id }}"
  hx-confirm="Permanently delete this email? This cannot be undone."
  hx-target="closest section" hx-swap="outerHTML">Delete</button>` — HTMX delete with
  browser confirm dialog (FR-020); on success the server returns an empty 200 fragment and
  the section is removed from the DOM.

- [X] T019 [US2] Extend `backend/src/api/mail.py` — add four endpoints to the existing
  `router`. **`GET /mail`**: query `SELECT * FROM incoming_emails ORDER BY received_at DESC`
  (no pagination limit per plan.md assumptions); query most recent `MailSyncRun` row; return
  `TemplateResponse("mail_list.html", {"request": request, "emails": emails, "last_run":
  last_run})`. **`GET /mail/{email_id}`**: query `IncomingEmail` by PK; raise `HTTPException(404)`
  if not found; return `TemplateResponse("mail_detail.html", {"request": request, "email":
  email})`. **`DELETE /mail/{email_id}`**: query `IncomingEmail` by PK; raise
  `HTTPException(404)` if not found; execute hard delete (`session.delete(email)` +
  `session.commit()`); return empty `HTMLResponse("")` with status 200 (HTMX swaps out the
  deleted element). **`POST /mail/cursor`**: accept form field `last_synced_at: str` (ISO 8601
  or empty string for reset); if empty/null, upsert `MailSyncCursor(id=1,
  last_synced_at=None)`; otherwise parse datetime (raise `HTTPException(422)` on parse
  failure); upsert cursor row; return `HTMLResponse` fragment confirming new cursor value with
  the note *"The next sync will fetch emails from this date forward."*

- [X] T020 [P] [US2] [SC-007] Create `backend/tests/integration/test_mail_api.py` — full round-trip
  integration tests via FastAPI `TestClient` against a real async DB (use the existing
  `pytest-asyncio` + test DB setup from feature 001 if present, or create an in-process
  SQLite async engine via `aiosqlite` for isolation). Test cases: (1) seed 3 `IncomingEmail`
  rows with distinct `received_at` values; `GET /mail` returns HTTP 200, HTML contains all 3
  sender names in newest-first order; (2) `GET /mail` with no rows returns 200 and empty-state
  message; (3) `GET /mail/{id}` returns 200 with correct body text; (4) `GET /mail/99999`
  returns 404; (5) `DELETE /mail/{id}` returns 200; subsequent `GET /mail/{id}` returns 404;
  (6) `POST /mail/cursor` with `last_synced_at="2026-01-01T00:00:00Z"` returns 200 and
  confirmation text; (7) `POST /mail/cursor` with invalid datetime returns 422;
  (8) `GET /health` with all `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`
  env vars set → response JSON contains `"mail": "ok"` and no outbound Gmail API call is made
  (assert `httpx`/`requests` mock not called — FR-016 regression); (9) `GET /health` with one
  `GMAIL_*` env var unset → response JSON contains `"mail": "unconfigured"` (FR-016 regression).

**Checkpoint**: `/mail` renders correctly with seeded data; empty-state shown with no data;
detail page shows full body and delete works; cursor reset returns confirmation;
`pytest tests/integration/test_mail_api.py` passes.

---

## Phase 5: User Story 3 — Automatic Background Polling (P3)

**Goal**: A coordinator sets a polling interval on the config page (e.g., 15 minutes). The system
automatically triggers a sync at that interval without any manual action. Changing the interval
takes effect immediately without restart. Setting interval to 0 disables polling. Polling failures
are logged and do not crash the app.

**Independent Test** (from spec.md): Configure `mail_poll_interval_minutes = 1` on the config page.
Wait 60+ seconds. Confirm a new email sent to the Gmail inbox during the wait appears in the mail
list without a manual sync. Check that the most recent `MailSyncRun` has `triggered_by =
"scheduler"`.

**Acceptance**: FR-014, FR-015

- [X] T021 [US3] Create `backend/src/services/scheduler_service.py` — APScheduler service.
  Import `AsyncIOScheduler` and `IntervalTrigger` from `apscheduler.schedulers.asyncio` and
  `apscheduler.triggers.interval`. Define `_scheduled_sync_fn: Callable | None = None` module
  variable (set at startup with the bound `run_sync` coroutine). Define
  `async def _scheduled_sync_job()` that calls `_scheduled_sync_fn()` inside try/except,
  catching all exceptions, logging them via `logger.error("scheduler_sync_failed", ...)`, and
  never re-raising (FR-015 — polling resumes on next interval). Define
  `async def start(scheduler: AsyncIOScheduler, poll_minutes: int, sync_fn: Callable) -> None`
  that sets `_scheduled_sync_fn = sync_fn`, starts the scheduler, and if `poll_minutes > 0`
  calls `scheduler.add_job(_scheduled_sync_job, IntervalTrigger(minutes=poll_minutes),
  id="gmail_sync", max_instances=1, coalesce=True)`.
  Define `def update_poll_interval(scheduler: AsyncIOScheduler, minutes: int) -> None` that:
  if `minutes == 0` and job exists → `scheduler.remove_job("gmail_sync")`; if `minutes > 0`
  and job exists → `scheduler.reschedule_job("gmail_sync",
  trigger=IntervalTrigger(minutes=minutes))`; if `minutes > 0` and job absent →
  `scheduler.add_job(...)` with same parameters. Define `async def shutdown(scheduler:
  AsyncIOScheduler) -> None` that calls `scheduler.shutdown(wait=False)`.

- [X] T022 [US3] Extend `backend/src/main.py` lifespan — integrate `AsyncIOScheduler`. After
  `startup_migrations_ok`: (1) import `scheduler_service` from `src.services.scheduler_service`;
  (2) create `scheduler = AsyncIOScheduler()`; (3) read `mail_poll_interval_minutes` from the
  `settings` table via a DB query (default to `0` if absent); (4) define the bound sync
  coroutine: `async def _sync_fn(): await run_sync(app.state.mail_adapter, session_factory(), triggered_by="scheduler")`
  and pass it as `sync_fn` to `scheduler_service.start`; (5) call `await
  scheduler_service.start(scheduler, poll_minutes, _sync_fn)`; (6) store
  `app.state.scheduler = scheduler`; log `startup_scheduler_ok`. In the lifespan cleanup
  (after yield): call `await scheduler_service.shutdown(app.state.scheduler)`.

- [X] T023 [US3] Extend `backend/src/api/config.py` — add scheduler reschedule on poll-interval
  save. After `await config_service.upsert(session, updates)` succeeds, check whether
  `"mail_poll_interval_minutes"` is in `updates`; if so, parse the value as int (default 0
  on parse failure), then call `scheduler_service.update_poll_interval(request.app.state.scheduler,
  minutes)`. Import `scheduler_service` from `src.services.scheduler_service`. Add `request:
  Request` as a parameter to `save_config()`. No other behaviour changes — unknown keys still
  rejected with 422, existing fields unchanged.

- [X] T024 [US3] Extend `backend/src/templates/config.html` — add a "Mail Settings" section.
  Render it after the existing LLM settings section. Include: (1) **Mail filter** — text input
  `name="mail_filter"` pre-populated with `config.get("mail_filter", "in:inbox")`; help text:
  *"Gmail search query to select visit-request emails (e.g. `subject:Aanmelding`)."*;
  (2) **Mail poll interval** — number input `name="mail_poll_interval_minutes"` pre-populated
  with `config.get("mail_poll_interval_minutes", "0")`; help text: *"Automatic sync interval in
  minutes. Set to 0 to disable background polling."*; (3) **Max retries** — number input
  `name="mail_sync_max_retries"` pre-populated with `config.get("mail_sync_max_retries", "3")`;
  help text: *"Maximum Gmail API retry attempts per sync on rate-limit or server errors."*;
  (4) **Overlap window** — number input `name="mail_overlap_minutes"` pre-populated with
  `config.get("mail_overlap_minutes", "5")`; help text: *"Minutes of overlap with previous sync
  to guard against clock skew (default: 5)."*;
  (5) a "Save mail settings" submit button that POSTs the form with HTMX. All four inputs use
  the same form-submit pattern as existing settings in the template.

- [X] T025 [P] [US3] Create `backend/tests/unit/test_scheduler_service.py` — unit tests for
  `scheduler_service` using an in-memory `AsyncIOScheduler` (no real timers). Test cases:
  (1) `start(scheduler, poll_minutes=15, sync_fn=...)` adds job `"gmail_sync"` with
  `IntervalTrigger(minutes=15)`, `max_instances=1`, `coalesce=True`;
  (2) `start(scheduler, poll_minutes=0, sync_fn=...)` starts scheduler but adds NO job;
  (3) `update_poll_interval(scheduler, 30)` when job exists reschedules it to 30 minutes;
  (4) `update_poll_interval(scheduler, 0)` removes the `"gmail_sync"` job;
  (5) `update_poll_interval(scheduler, 10)` when no job exists adds it;
  (6) `_scheduled_sync_job()` catching an exception does NOT re-raise (polling resilience —
  FR-015).

**Checkpoint**: Setting `mail_poll_interval_minutes=1` on the config page reconfigures the
scheduler without restart; a `MailSyncRun` row with `triggered_by="scheduler"` is created
after one interval; changing to `0` stops further scheduled runs;
`pytest tests/unit/test_scheduler_service.py` passes.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Validate edge-case handling specified in spec.md; run end-to-end quickstart
validation.

- [X] T026 [P] Review and harden edge-case handling in `backend/src/adapters/gmail_adapter.py`
  and `backend/src/services/mail_service.py`: (1) verify that a `HttpError 429` mid-sync (after
  some emails are already committed) produces a `MailSyncRun` with `outcome="partial"` and
  `new_count > 0` — cursor NOT advanced; (2) verify that a `HttpError 429` before any emails
  are committed produces `outcome="failed"` — cursor NOT advanced; (3) verify that the app
  handles `messages.list()` paginating across thousands of results without memory exhaustion
  (process in pages, not all IDs at once); (4) verify that `POST /mail/sync` while a sync is
  already in progress returns the in-progress fragment without creating a duplicate
  `MailSyncRun` row.

- [X] T027 [P] Review and harden body-processing edge cases in
  `backend/src/adapters/gmail_adapter.py`: (1) email with no `parts` (inline body in
  `payload.body.data`) — verify `_extract_email` falls back to `payload.body.data`; (2)
  HTML-only email (no `text/plain` part) — verify `html2text` conversion produces readable
  plain text with no tags; (3) email with empty body data (`""` or absent `data` key) — verify
  `body_plain_text` is stored as `""` without raising an exception; (4) email with `Subject:`
  header absent — verify `subject` defaults to `""`.

- [X] T028 Run the `specs/002-gmail-mail-sync/quickstart.md` first-sync validation flow on a
  deployed instance with real `GMAIL_*` credentials: complete Steps 1–6 in order; verify
  (a) `GET /health` shows `mail: ok`; (b) first sync stores emails and reports correct counts
  in the UI; (c) second sync reports zero new emails; (d) `GET /mail` shows all fetched emails
  newest-first; (e) clicking an email shows the plain-text body with no HTML tags; (f) deleting
  an email removes it from the list; (g) enabling polling with `mail_poll_interval_minutes=1`
  results in an automatic sync within ~70 seconds.
  **Timing SLA checkpoints** (SC-001, SC-004, SC-006 — manual hardware validation only; not verifiable in CI): (h) time a sync of ≥200 emails
  end-to-end and assert it completes in under 60 seconds on the Pi 5; (i) inject a
  credential failure (set `GMAIL_CLIENT_SECRET` to an invalid value), trigger a sync, and
  assert the error message appears in the UI within 10 seconds; (j) time the full first-sync
  user journey from pressing "Sync Mail" to seeing emails in the list and assert under 2
  minutes on a fresh deployment.

---

## Dependencies & Execution Order

### Phase Dependencies

```
Phase 1 (Setup)
  └─► Phase 2 (Foundational)       — T001/T002 must be complete
        └─► Phase 3 (US1 — P1)     — all of Phase 2 must be complete
              ├─► Phase 4 (US2 — P2)   — extends mail.py from T012; independently testable
              ├─► Phase 5 (US3 — P3)   — calls run_sync from T009; can run in parallel with US2
              └─► [Phase 4 and Phase 5 are independent of each other; both feed into Phase 6]
                    └─► Phase 6 (Polish)
```

### Task-Level Dependencies

| Task | Depends on | Reason |
|------|-----------|--------|
| T002 | T001 | Package needs pyproject updated first |
| T003 | T001 | SQLAlchemy models need library available |
| T004 | T001 | Needs project importable |
| T005 | T003 | Migration references model classes and table names |
| T006 | T001 | ABC uses `dataclasses` and `enum` from stdlib; `MailAdapter` import must not pull `GmailAdapter` |
| T007 | T004 | KNOWN_KEYS must include new keys before form handler adds them |
| T008 | T001, T002, T006 | `GmailAdapter` implements `MailAdapter`; needs adapter package and new libs |
| T009 | T003, T006 | Orchestration needs ORM models and MailAdapter/EmailMessage types |
| T010 | — | Template only; no code dependencies |
| T011 | — | Template only; no code dependencies |
| T012 | T009, T010, T011 | API endpoints call `run_sync` and render templates |
| T013 | T008, T012 | `main.py` instantiates `GmailAdapter` and registers `mail_router` |
| T014 | — | base.html edit is independent |
| T015 | T008 | Tests the module created in T008 |
| T016 | T009 | Tests the module extended in T009 |
| T017 | — | Template only; references context variables, not imports |
| T018 | — | Template only |
| T019 | T012, T017, T018 | Extends the file created in T012; renders templates from T017/T018 |
| T020 | T019 | Integration test against endpoints created in T012 + T019 |
| T021 | T009 | Scheduler wraps `run_sync`; needs `SyncAlreadyRunningError` from T009 |
| T022 | T013, T021 | Extends `main.py` lifespan modified in T013; uses `scheduler_service` from T021 |
| T023 | T007, T021 | Extends config handler modified in T007; calls `update_poll_interval` from T021 |
| T024 | — | Template-only extension; rendered variables come from existing config context |
| T025 | T021 | Tests the module created in T021 |
| T026 | T009, T008 | Review of completed orchestration and adapter logic |
| T027 | T008 | Review of completed adapter logic |
| T028 | T026, T027 | End-to-end validation after all polish tasks |

### User Story Independence

- **US1 (P1)**: Independent after Foundational. Delivers a fully functional manual sync with
  DB storage and UI result display. No dependency on US2 or US3.
- **US2 (P2)**: Depends on US1 being done (extends `mail.py` created in T012) but is
  independently testable once its phase is complete. Can be seeded directly to verify without
  triggering a real Gmail sync.
- **US3 (P3)**: Depends on US1 (scheduler calls `run_sync`). Can be developed in parallel
  with US2 if two developers are available (different files: `scheduler_service.py`,
  `main.py` lifespan extension, `config.py` extension, `config.html`).

---

## Parallel Execution Examples

### Phase 2 — Foundational (3-way parallel after T001/T002)

```
After T001 + T002 complete:

  Track A:  T003 → T005   (mail.py models → Alembic migration)
  Track B:  T004           (extend settings KNOWN_KEYS — independent single-file edit)
  Track C:  T006           (mail_service.py ABC — independent new file)
  Track D:  T007           (config.py Form params — independent single-file edit)
```

### Phase 3 — US1 (2-way parallel after Foundational)

```
After all Phase 2 tasks complete:

  Track A:  T008           (gmail_adapter.py — new file, no local deps)
  Track B:  T009           (mail_service.py orchestration — extends existing file)
  Track C:  T010, T011     (templates — no code deps; T010 and T011 in parallel)
  Track D:  T014           (base.html nav — independent edit)

  Then (after T008, T009, T010, T011):
  Track A:  T012           (mail.py initial endpoints)

  Then (after T012):
  Track A:  T013           (main.py wiring)

  Parallel with T008/T009/T010/T011:
  Track E:  T015           (unit tests gmail_adapter — can be written as T008 progresses)
  Track F:  T016           (unit tests mail_service — can be written as T009 progresses)
```

### Phase 4 — US2 (3-way parallel after US1)

```
After Phase 3 complete:

  Track A:  T017           (mail_list.html — new file)
  Track B:  T018           (mail_detail.html — new file)

  Then (after T012, T017, T018):
  Track A:  T019           (extend mail.py with browse/delete/cursor endpoints)

  Parallel with T019:
  Track B:  T020           (integration tests — can be written alongside T019)
```

### Phase 5 — US3 (partially parallel with US2)

```
Parallel with US2 (different files):

  Track A:  T021           (scheduler_service.py — new file)
  Track B:  T024           (config.html template extension — independent)
  Track C:  T025           (unit tests scheduler — can be written as T021 progresses)

  Then (after T021 + T013):
  Track A:  T022           (main.py lifespan extension — sequential after T013)

  Then (after T022 + T007):
  Track A:  T023           (config.py reschedule logic — sequential after T007 + T021)
```

### Phase 6 — Polish (2-way parallel)

```
  Track A:  T026           (edge-case review — orchestration + adapter)
  Track B:  T027           (body-processing edge cases — adapter only)

  Then (after T026 + T027):
            T028           (quickstart validation — sequential, needs all code complete)
```

---

## Implementation Strategy

### MVP First: User Story 1 Only (Phases 1–3)

Deliver a working manual sync before implementing browse or polling:

1. **Phase 1** (Setup): update `pyproject.toml`, create `adapters/` package — ~30 min
2. **Phase 2** (Foundational): models, migration, interface, config API — ~2 h
3. **Phase 3** (US1): Gmail adapter, orchestration, sync endpoints, nav link — ~4 h
4. **STOP and VALIDATE**: use `quickstart.md` Steps 3–6 with real credentials; verify
   `POST /mail/sync` stores emails; run sync twice to confirm zero duplicates
5. Deploy / demo — P1 MVP is complete and independently verifiable

### Incremental Delivery

```
Phases 1–3  → US1 complete: manual sync, dedup, result display
               ↓ Deploy / demo (SC-001 through SC-004 measurable here)
Phase 4     → US2 complete: mail list, detail view, delete, cursor reset
               ↓ Deploy / demo (SC-005, SC-006, SC-007 measurable here)
Phase 5     → US3 complete: background polling, runtime reconfiguration
               ↓ Deploy / demo (FR-014, FR-015 end-to-end verified)
Phase 6     → Polish: edge-case hardening, quickstart validation
```

Each increment is independently deployable and testable without the next phase being complete.

### Parallel Team Strategy (if 2+ developers)

1. Both developers complete Phase 1 + Phase 2 together (~2.5 h)
2. Once Foundational phase is done:
   - **Developer A**: Phase 3 (US1) — T008 → T009 → T012 → T013 (core sync path)
   - **Developer B**: Phase 3 parallel work — T010, T011, T014, T015, T016 (templates + tests)
3. Once US1 is complete:
   - **Developer A**: Phase 5 (US3) — T021 → T022 → T023 (scheduler)
   - **Developer B**: Phase 4 (US2) — T017, T018 → T019 → T020 (browse UI)
4. Polish (Phase 6): review together

---

## Summary

| Metric | Value |
|--------|-------|
| **Total tasks** | 28 (T001–T028) |
| **Phase 1 (Setup)** | 2 tasks |
| **Phase 2 (Foundational)** | 5 tasks |
| **Phase 3 (US1 — P1 MVP)** | 9 tasks |
| **Phase 4 (US2 — P2)** | 4 tasks |
| **Phase 5 (US3 — P3)** | 5 tasks |
| **Phase 6 (Polish)** | 3 tasks |
| **Parallelisable tasks [P]** | 16 tasks (T002, T004, T006, T007, T010, T011, T014, T015, T016, T017, T018, T020, T024, T025, T026, T027) |
| **New files created** | 15 files |
| **Existing files extended** | 6 files (`pyproject.toml`, `models/settings.py`, `api/config.py`, `main.py` ×2, `templates/base.html`, `templates/config.html`) |
| **Test files** | 4 (`test_gmail_adapter.py`, `test_mail_service.py`, `test_scheduler_service.py`, `test_mail_api.py`) |
| **Parallel opportunities identified** | 5 parallel windows (see examples above) |
| **MVP scope** | Phases 1–3 (US1 only — 16 tasks) |

### Independent Test Criteria per Story

| Story | Independent test |
|-------|-----------------|
| **US1 (P1)** | `POST /mail/sync` with real Gmail creds stores emails; second sync reports 0 new, 0 duplicates in DB |
| **US2 (P2)** | Seed 3 rows via DB; `GET /mail` shows all in correct order; detail page shows body; delete removes row |
| **US3 (P3)** | Set poll interval = 1 min; wait 70 s; new email appears in list without manual trigger; `MailSyncRun.triggered_by = "scheduler"` |
