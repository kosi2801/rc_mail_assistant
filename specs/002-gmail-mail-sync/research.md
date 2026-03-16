# Research: Gmail Mail Sync

**Feature**: 002-gmail-mail-sync  
**Date**: 2026-02-28  
**Branch**: `002-gmail-mail-sync`

---

## 1. Gmail API OAuth2 Credentials Construction

**Decision**: Build `google.oauth2.credentials.Credentials` directly from the three env vars
(`GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`). No interactive OAuth flow
at runtime; no `client_secrets.json`.

**Rationale**: The `google.oauth2.credentials.Credentials` constructor accepts all required
fields at object-creation time. When `token` (access token) is omitted or expired, `google-auth`
auto-refreshes on the first API call via the `google.auth.transport.requests.Request` transport.
Eager refresh at startup (`creds.refresh(Request())`) surfaces invalid credentials immediately
rather than at first sync time.

**Required packages** (new additions to `pyproject.toml`):
```
google-api-python-client>=2.0
google-auth>=2.0
google-auth-httplib2>=0.1
html2text>=2024.2
apscheduler>=3.10,<4.0
```

**Key implementation pattern**:
```python
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

def build_credentials() -> Credentials:
    creds = Credentials(
        token=None,
        refresh_token=settings.gmail_refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.gmail_client_id,
        client_secret=settings.gmail_client_secret,
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
    )
    creds.refresh(Request())   # eager refresh — fail fast on bad creds
    return creds
```

**Token lifecycle**: Access tokens expire after 3,600 s. `google-auth` refreshes them
transparently before each request. If the refresh token itself is revoked (unused >6 months
for consumer accounts, or user revoked access), a `google.auth.exceptions.RefreshError` is
raised — this must be caught in the adapter and surfaced as a descriptive error via
`MailSyncRun`.

**Alternatives considered**:
- `google_auth_oauthlib.flow`: Only needed for interactive browser-based consent; irrelevant here.
- Service account credentials: For server-to-server auth against a GSuite domain; not applicable
  for personal Gmail owned by a real user account.

---

## 2. Gmail API Service in a FastAPI Async Context

**Decision**: Build the service object once via `googleapiclient.discovery.build()` at
adapter initialisation time; wrap every blocking API call in
`asyncio.get_event_loop().run_in_executor(None, lambda: ...)` to avoid blocking the event loop.

**Rationale**: `google-api-python-client` uses `httplib2` (blocking I/O) internally. Direct
calls inside `async def` handlers stall the entire uvicorn event loop. Wrapping in
`run_in_executor` runs them in the default thread-pool, keeping the loop free. `cache_discovery=False`
disables the file-based discovery cache that raises `FileNotFoundError` in containerised
environments.

**Key implementation pattern**:
```python
from googleapiclient.discovery import build
import asyncio

class GmailAdapter(MailAdapter):
    def __init__(self, credentials: Credentials) -> None:
        self._svc = build("gmail", "v1", credentials=credentials, cache_discovery=False)

    async def _run(self, fn):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, fn)
```

**Alternatives considered**:
- GAPIC async clients (`google-cloud-*`): Not available for Gmail; Gmail is REST-only.
- `httpx` + manual OAuth: Far more custom code with no benefit; rejects `google-auth` library.

---

## 3. Incremental Email Fetch Strategy

**Decision**: Use `q='after:<unix_epoch>'` in `messages.list()` combined with the configurable
overlap window (default 5 minutes subtracted from `last_synced_at`). Deduplication via
`gmail_message_id` UNIQUE constraint handles re-fetched messages in the overlap window.

**Rationale**:

| Approach | Pros | Cons |
|---|---|---|
| `q='after:TIMESTAMP'` (chosen) | Simple, stateless, overlap trivial | Returns IDs only — one `get()` call per message |
| `history.list(startHistoryId=...)` | Efficient delta; one API call for all changes | `historyId` expires after ~7 days inactivity — real risk given weekly Repair Café cadence |

Gmail's `after:` filter accepts Unix epoch seconds (unambiguous regardless of server timezone)
or `YYYY/MM/DD` dates. Epoch seconds are preferred.

**Pagination**: `messages.list()` returns up to 500 IDs per page; paginate via `nextPageToken`
until exhausted before fetching individual message bodies.

**Alternatives considered**:
- `historyId` approach: More efficient but fragile — token expiry requires a fallback to
  full re-fetch anyway, adding implementation complexity for marginal gain at Repair Café scale.

---

## 4. Rate Limiting and Retry Strategy

**Decision**: Exponential backoff with jitter on HTTP `429` and `5xx` responses; max retries
configurable via the `mail_sync_max_retries` setting (default 3). Use the existing `tenacity`
dependency (already in `pyproject.toml`) to keep the retry logic declarative.

**Rationale**: Gmail API quota for personal accounts is ~1 billion units/day with a 250 QPS
burst limit. The practical constraint is `messages.get(format="full")` costing 25 quota units
each — 200 messages = 5,000 units; well within limits. `tenacity` is already a project
dependency (used for DB startup retry), making it the zero-cost choice.

**Quota units** (key operations):

| Operation | Units |
|---|---|
| `messages.list` (per page) | 5 |
| `messages.get(format="full")` | 25 |

**Key pattern**:
```python
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

@retry(
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(settings.mail_sync_max_retries),
    retry=retry_if_exception(lambda e: isinstance(e, HttpError) and e.resp.status in (429, 500, 503)),
)
def _execute(request):
    return request.execute()
```

**Alternatives considered**:
- Hand-rolled `for` loop with `time.sleep`: verbose, no jitter, easy to get wrong — rejected in
  favour of `tenacity` (already a project dependency).

---

## 5. Token Refresh on Expiry

**Decision**: Rely on `google-auth`'s transparent refresh mechanism for access token rotation.
Catch `google.auth.exceptions.RefreshError` explicitly to surface invalid/revoked refresh
tokens as a descriptive sync failure.

**Rationale**: `google-api-python-client` wraps every HTTP call via `AuthorizedHttp`, which
calls `credentials.refresh()` automatically when `credentials.expired` is `True`. This means
routine access-token expiry (1 hour) is fully transparent. Refresh token revocation raises
`RefreshError` — this cannot be auto-recovered and requires operator action to re-authorise.

**Refresh token revocation scenarios** (operators must be aware):
- Token unused for 6+ months (consumer accounts)
- User manually revokes access in Google Account settings
- OAuth app in "testing" mode and token is >7 days old

**Error surface path**: `RefreshError` → caught in `GmailAdapter.fetch_new_emails()` →
propagated as `MailSyncRun.outcome = "failed"` with human-readable `error_message` →
displayed in UI.

---

## 6. Full Message Body Extraction

**Decision**: Use `messages.get(format="full")` to retrieve the complete MIME tree. Traverse
`payload.parts` recursively, preferring `text/plain` parts; fall back to `text/html` parts
stripped via `html2text`. Body is decoded from URL-safe base64 (padding `+=` added before
decode).

**MIME tree structure** (typical email):
```
payload
├── mimeType: "multipart/mixed"
└── parts[]
    ├── mimeType: "multipart/alternative"
    │   └── parts[]
    │       ├── mimeType: "text/plain"  ← preferred
    │       └── mimeType: "text/html"  ← fallback
    └── mimeType: "application/pdf"    ← skip (attachment)
```

**Key base64 detail**: Gmail encodes body data as URL-safe base64 *without* padding. Always
append `"=="` before decoding: `base64.urlsafe_b64decode(data + "==")`.

**Alternatives considered**:
- `format="raw"` + stdlib `email.message_from_bytes`: More correct for edge-case charset
  handling, but transfers ~3× more data per message. Deferred as a future improvement if
  charset bugs emerge.

---

## 7. HTML-to-Plain-Text Conversion

**Decision**: `html2text` library with the following configuration:

```python
import html2text

def html_to_plain_text(html: str) -> str:
    h = html2text.HTML2Text()
    h.ignore_links = True        # drop [text](url) — tracking/CTA noise
    h.ignore_images = True       # drop tracking pixels
    h.ignore_emphasis = True     # drop *bold* / _italic_ markers
    h.body_width = 0             # no hard line-wraps at 79 chars
    h.skip_internal_links = True # drop #anchor-only hrefs
    return h.handle(html).strip()
```

**Rationale**: Zero additional transitive dependencies (single lightweight package).
Handles common email HTML structure (`<br>`, `<p>`, `<table>`, inline styles) with configurable
output. The `ignore_*` toggles produce clean stored text suitable for both human reading and
future LLM context.

**Alternatives considered**:

| Library | Verdict |
|---|---|
| `html2text` ✅ | Zero deps, email-aware, configurable |
| `bs4 + get_text()` | No structural awareness — loses paragraph breaks; useful as a post-processor |
| `markdownify` | Preserves Markdown syntax (links, headers) — adds noise to stored bodies |

**Note**: `beautifulsoup4` is NOT a transitive dependency of `google-api-python-client`; it
must be added explicitly if chosen. `html2text` has no dependencies beyond the Python stdlib.

---

## 8. APScheduler Version and Scheduler Choice

**Decision**: APScheduler **3.x** (stable, latest `3.11.x`). Use `AsyncIOScheduler` rather than
`BackgroundScheduler`, because it runs coroutines natively on the event loop, eliminating the
thread/async bridge problem.

**Rationale**: APScheduler 4.x is still in alpha (`4.0.0a6`); avoid for production. The spec
requires `BackgroundScheduler` by name (FR-014), but `AsyncIOScheduler` is functionally
identical for this use case and strictly better in a FastAPI/uvicorn context — it submits
coroutines directly to the running event loop instead of requiring a `run_coroutine_threadsafe`
bridge via a captured loop reference. The substitution is transparent to all sync orchestration
logic and satisfies all FR-014 requirements.

**Import path**:
```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
```

**Alternatives considered**:
- `BackgroundScheduler` (thread-based): Works but requires capturing the event loop reference
  at startup and `asyncio.run_coroutine_threadsafe()` in the job wrapper — more fragile with
  no benefits over `AsyncIOScheduler` in this context.
- Celery + Redis: Heavy dependency; violates Minimal Footprint (Constitution III). Rejected.

---

## 9. APScheduler Startup/Shutdown Pattern

**Decision**: Start `AsyncIOScheduler` inside the FastAPI `asynccontextmanager` lifespan;
shut it down on exit. Store the instance on `app.state.scheduler` for runtime reconfiguration
from route handlers.

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... existing startup (env validation, DB connect, migrations) ...

    scheduler = AsyncIOScheduler()
    # Only add job if polling is enabled in settings
    poll_minutes = await _get_poll_interval(session)
    if poll_minutes > 0:
        scheduler.add_job(
            _scheduled_sync,
            IntervalTrigger(minutes=poll_minutes),
            id="gmail_sync",
            max_instances=1,
            coalesce=True,
        )
    scheduler.start()
    app.state.scheduler = scheduler

    yield

    scheduler.shutdown(wait=False)
```

---

## 10. Preventing Concurrent Sync Execution

**Decision**: Two-layer guard: APScheduler `max_instances=1` (skips overlapping job triggers)
plus an `asyncio.Lock` in the sync orchestration layer (prevents concurrent manual + scheduled
syncs from running simultaneously).

**Rationale**: `max_instances=1` only prevents two *scheduled* instances from overlapping.
It cannot block a manual `POST /mail/sync` from running concurrently with a scheduled sync,
because the manual path bypasses APScheduler entirely. The `asyncio.Lock` closes this gap.

```python
_sync_lock = asyncio.Lock()

async def run_sync() -> MailSyncRun:
    if _sync_lock.locked():
        raise SyncAlreadyRunningError("A sync operation is already in progress.")
    async with _sync_lock:
        # ... sync logic
```

**UI gate (FR-022)**: The "Sync Mail" button is disabled via HTMX while a sync is in progress,
providing a second layer of UX-level prevention. The lock remains the authoritative server-side
guard.

---

## 11. Runtime Interval Reconfiguration

**Decision**: Use `scheduler.reschedule_job("gmail_sync", trigger=IntervalTrigger(minutes=n))`
for interval changes; add/remove the job when switching between enabled and disabled states.
Both operations are safe to call from async route handlers.

```python
async def update_poll_interval(minutes: int, scheduler: AsyncIOScheduler):
    if minutes == 0:
        if scheduler.get_job("gmail_sync"):
            scheduler.remove_job("gmail_sync")
    else:
        if scheduler.get_job("gmail_sync"):
            scheduler.reschedule_job(
                "gmail_sync", trigger=IntervalTrigger(minutes=minutes)
            )
        else:
            scheduler.add_job(
                _scheduled_sync,
                IntervalTrigger(minutes=minutes),
                id="gmail_sync",
                max_instances=1,
                coalesce=True,
            )
```

No application restart is required. The next trigger time is recalculated immediately on
`reschedule_job()`.
