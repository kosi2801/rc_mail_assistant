# Contract: Mail Endpoints

**Feature**: 002-gmail-mail-sync  
**Date**: 2026-02-28

> This contract documents the new endpoints introduced by the Gmail Mail Sync feature and the
> extensions made to the existing `/config` contract from feature 001.
>
> All HTML endpoints use the HTMX + Jinja2 pattern established in feature 001. HTML fragment
> endpoints return no `<html>`, `<head>`, or `<body>` wrapper. All responses are HTTP 200 unless
> stated otherwise.

---

## `GET /mail`

Full mail list page. Displays all stored `IncomingEmail` records in reverse chronological order.

### Request

No parameters, no authentication required.

### Response

**HTTP 200 OK** (`Content-Type: text/html`)

Full HTML page containing:
- Mail list with one row per `IncomingEmail`: sender name, subject, received date
- **"Sync Mail" button** — triggers `POST /mail/sync` via HTMX; disabled and shows
  "Syncing…" spinner while a sync is in progress (FR-022)
- **Last sync status** — date/time, outcome, counts from the most recent `MailSyncRun` record
- **Empty-state message** when no emails are stored (FR-013):
  > *"No emails have been synced yet. Click "Sync Mail" to fetch your first batch."*

**Ordering**: `received_at DESC` (newest first, FR-011).

---

## `GET /mail/{email_id}`

Full email detail page. Displays the complete stored record for one `IncomingEmail`.

### Path parameter

| Parameter | Type | Description |
|---|---|---|
| `email_id` | integer | `IncomingEmail.id` (internal surrogate key) |

### Response

**HTTP 200 OK** (`Content-Type: text/html`)

Full HTML page containing:
- Sender name, sender email address
- Subject line
- Received date and time (human-readable, local timezone)
- Synced date and time
- Full plain-text body (FR-012); `[TRUNCATED]` marker visible to operator when present (FR-021)
- **Delete button** — triggers `DELETE /mail/{email_id}` via HTMX; shows a confirmation
  dialog before submission (FR-020)
- Back-link to `GET /mail`

**HTTP 404** when no `IncomingEmail` with the given `id` exists.

---

## `POST /mail/sync`

Triggers a manual Gmail sync operation. Idempotent with respect to email deduplication
(re-running produces no duplicate records). Returns an HTML fragment for HTMX inline swap
into the sync result area on `GET /mail`.

### Request

No body, no parameters.

### Response — sync completed successfully

**HTTP 200 OK** (`Content-Type: text/html`)

HTML fragment containing:
- Outcome badge: **"✓ success"** (green)
- New emails stored: `N new email(s) fetched`
- Duplicates skipped: `N duplicate(s) skipped`
- Timestamp of completed sync

### Response — sync completed with partial success

**HTTP 200 OK** (`Content-Type: text/html`)

HTML fragment containing:
- Outcome badge: **"⚠ partial"** (amber)
- New emails stored before error
- Error detail (e.g., "Rate limit exceeded after 200 messages; retry later")

### Response — sync failed

**HTTP 200 OK** (`Content-Type: text/html`)

HTML fragment containing:
- Outcome badge: **"✗ failed"** (red)
- Zero new emails
- Error detail (e.g., "Gmail credentials are invalid or expired. Please update GMAIL_REFRESH_TOKEN.")

### Response — sync already running

**HTTP 200 OK** (`Content-Type: text/html`)

HTML fragment containing:
- Status message: **"⟳ Sync already in progress"** (blue)
- No new `MailSyncRun` record is created for this case

### Behaviour notes

- A `MailSyncRun` record is created at the start of every sync (before any API call) so that
  a crashed or interrupted sync leaves an auditable trace.
- The `MailSyncCursor` is updated only after a `success` outcome; `partial` and `failed`
  outcomes do not advance the cursor.
- The "Sync Mail" button is disabled (`disabled` attribute) and its label replaced with a
  spinner + "Syncing…" text while this endpoint is processing (FR-022). HTMX polls
  `GET /mail/sync/status` during the operation to update the UI.

---

## `GET /mail/sync/status`

HTMX polling endpoint. Returns a lightweight HTML fragment indicating whether a sync is
currently in progress. Used to update the "Sync Mail" button state and last-sync metadata on
`GET /mail` without a full page reload.

### Response — sync in progress

**HTTP 200 OK** (`Content-Type: text/html`)

HTML fragment with the button in its disabled / "Syncing…" state.

### Response — no sync in progress

**HTTP 200 OK** (`Content-Type: text/html`)

HTML fragment with:
- "Sync Mail" button in its normal (enabled) state
- Last `MailSyncRun` outcome summary (timestamp, outcome, counts)

---

## `DELETE /mail/{email_id}`

Permanently hard-deletes a single `IncomingEmail` record. Does NOT affect the corresponding
message in Gmail. A confirmation prompt MUST be shown in the UI before the HTMX request is
dispatched (FR-020).

### Path parameter

| Parameter | Type | Description |
|---|---|---|
| `email_id` | integer | `IncomingEmail.id` |

### Response

**HTTP 200 OK** (`Content-Type: text/html`)

Empty HTML fragment (HTMX swaps out the deleted email row from the DOM).

**HTTP 404** when no `IncomingEmail` with the given `id` exists.

---

## `POST /mail/cursor`

Operator-initiated reset of the `MailSyncCursor`. Setting `last_synced_at` to an earlier
timestamp causes the next sync to re-fetch all emails from that point forward. Emails already
stored will be skipped via deduplication (FR-018).

### Request body (form-encoded or JSON)

| Field | Type | Required | Description |
|---|---|---|---|
| `last_synced_at` | ISO 8601 datetime string | Yes | New cursor value (e.g., `"2026-01-01T00:00:00Z"`); set to `""` or `null` to reset to "never synced" state |

### Response

**HTTP 200 OK** (`Content-Type: text/html`)

HTML fragment confirming the cursor was updated:
- New cursor value displayed in human-readable format
- Note: "The next sync will fetch emails from this date forward."

**HTTP 422** when `last_synced_at` cannot be parsed as a valid datetime.

---

## Extensions to `GET /config` and `POST /config`

The existing config contract (feature 001) is extended with four new settings keys.

### Extended `GET /config` response

```json
{
  "llm_endpoint":                "http://ollama:11434",
  "llm_model":                   "llama3.2",
  "event_date":                  "2026-03-15",
  "event_location":              "Wijkcentrum De Brug, Amsterdam",
  "event_offerings":             "electronics,clothing,bikes",
  "mail_filter":                 "in:inbox",
  "mail_poll_interval_minutes":  "0",
  "mail_sync_max_retries":       "3",
  "mail_overlap_minutes":        "5"
}
```

New keys return `null` if not yet stored in the `settings` table (same behaviour as existing keys).

### Extended `POST /config` accepted fields

| Field | Type | Description |
|---|---|---|
| `mail_filter` | string | Gmail search query (e.g., `in:inbox`, `subject:Aanmelding`) |
| `mail_poll_interval_minutes` | string (integer ≥ 0) | `"0"` = disabled; any positive integer enables background polling. Changing this value reschedules or removes the APScheduler job at runtime (FR-014). |
| `mail_sync_max_retries` | string (integer ≥ 1) | Maximum Gmail API retry attempts per sync run |
| `mail_overlap_minutes` | string (integer ≥ 0) | Minutes of overlap with the previous sync to guard against clock skew (default: `"5"`). Read by `run_sync()` at the start of each sync. |

Unknown keys continue to be rejected with HTTP 422 (existing behaviour).

---

## Health Endpoint — No Change

The `GET /health` endpoint and the `mail` check behaviour are **unchanged** from the feature 001
contract. The `mail` check remains a credential-presence check only:

- `"ok"` — all three `GMAIL_*` env vars are present and non-empty
- `"unconfigured"` — one or more `GMAIL_*` env vars are absent or empty

No outbound Gmail API call is made by the health endpoint (FR-016). Live Gmail connectivity
status (success, error, partial) is surfaced exclusively via the most recent `MailSyncRun`
outcome displayed on the mail page.

---

## `POST /config/test/mail` — No Change

The existing mail connection test endpoint continues to perform a credentials-presence check
only. It does not perform a live Gmail API call. Behaviour is unchanged from the feature 001
contract.
