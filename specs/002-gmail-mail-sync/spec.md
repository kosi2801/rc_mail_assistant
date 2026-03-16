# Feature Specification: Gmail Mail Connector

**Feature Branch**: `002-gmail-mail-sync`  
**Created**: 2026-02-25  
**Status**: Draft  
**Input**: User description: "Gmail mail connector — fetching visit request emails, storing them as plain text in the database"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Sync Visit Request Emails (Priority: P1)

A Repair Café coordinator wants to see all incoming visit requests that have arrived in the
Gmail inbox since the last sync. They click a "Sync Mail" button on the dashboard or mail
page, the system connects to Gmail, retrieves all new emails matching the configured
visit-request filter, and stores them in the application database as plain text. The
coordinator sees a summary of how many new emails were fetched, without having to leave the
application or open Gmail directly.

**Why this priority**: This is the core of the feature — all future capabilities (AI drafting,
response tracking) depend on emails being fetched and persisted. Nothing else in this feature
is possible without it.

**Independent Test**: Can be fully tested by clicking "Sync Mail" on a running instance
connected to a Gmail account containing at least one unsynced email, then verifying the email
appears in the database with the correct sender, subject, date, and plain-text body — with no
duplicate entries after a second sync.

**Acceptance Scenarios**:

1. **Given** Gmail credentials are configured and there are new emails in the inbox matching
   the visit-request filter, **When** the coordinator triggers "Sync Mail", **Then** the system
   fetches all new emails, stores each as a database record with sender, subject, received
   date, and plain-text body, and reports the count of newly stored emails.

2. **Given** a sync has already been performed, **When** the coordinator triggers "Sync Mail"
   again without any new emails arriving, **Then** the system reports zero new emails and no
   duplicate records are created in the database.

3. **Given** an email has already been stored, **When** the same Gmail message arrives in a
   subsequent sync, **Then** the system skips it without error, and the database still contains
   exactly one record for that message.

4. **Given** an email body is formatted as HTML, **When** it is stored, **Then** the stored
   body contains only the readable plain-text content — no HTML tags, CSS, or markup.

---

### User Story 2 - Browse Stored Visit Request Emails (Priority: P2)

A coordinator or volunteer opens the mail list page to review all stored visit request emails.
They can see each email's sender name, subject, and received date in a list. Clicking an
email shows the full plain-text body. This gives them a complete picture of incoming requests
without needing to leave the application or access Gmail.

**Why this priority**: Verifying that sync worked correctly and browsing the backlog of
requests is the second most important workflow. It delivers standalone value — a coordinator
can triage requests even before AI drafting is available.

**Independent Test**: Can be fully tested by populating the database with at least three
stored emails (via sync or direct test data), loading the mail list page, verifying all
entries appear with correct metadata, and confirming the body displays correctly when an
email is selected.

**Acceptance Scenarios**:

1. **Given** the database contains stored emails, **When** the coordinator opens the mail list
   page, **Then** all emails are displayed in reverse chronological order, each showing sender,
   subject, and received date.

2. **Given** the mail list is displayed, **When** the coordinator selects an email, **Then**
   the full plain-text body is shown without any HTML markup.

3. **Given** no emails have been synced yet, **When** the coordinator opens the mail list
   page, **Then** an informative empty-state message is displayed with a prompt to run the
   first sync.

---

### User Story 3 - Automatic Background Polling (Priority: P3)

A coordinator wants the application to stay up to date with new visit requests without having
to press "Sync Mail" manually every time. They configure a polling interval (e.g., every
15 minutes) on the configuration page, and the system automatically fetches new emails in the
background on that schedule. New emails appear in the list without any manual action.

**Why this priority**: Automation is a convenience enhancement. The manual sync (P1) and
browse (P2) stories already deliver a fully functional product; background polling reduces
friction for regular use but is not blocking.

**Independent Test**: Can be fully tested by configuring a short polling interval, waiting for
the interval to elapse, and confirming that a new email (sent to the Gmail inbox during the
wait) appears in the mail list without a manual sync being triggered.

**Acceptance Scenarios**:

1. **Given** a polling interval is configured, **When** that interval elapses, **Then** the
   system automatically performs a sync and any new emails appear in the mail list.

2. **Given** automatic polling is enabled, **When** the sync fails (e.g., Gmail unreachable),
   **Then** the failure is logged and surfaced in the UI health status — polling resumes on
   the next interval without crashing the application.

3. **Given** a polling interval is set to "disabled", **When** the application is running,
   **Then** no automatic sync occurs and the "Sync Mail" button remains the only trigger.

---

### Edge Cases

- What happens when the Gmail API returns a rate-limit error mid-sync? The system must back
  off gracefully, preserve already-fetched records, and surface the partial result to the
  operator.
- What happens when Gmail credentials are expired or revoked? The sync must fail
  descriptively, guiding the operator to refresh credentials — without crashing or affecting
  non-mail features.
- What happens when an email has no plain-text body (HTML-only or empty)? The system must
  extract the best available text representation or store an empty body rather than failing.
- What happens when an email is extremely large (e.g., large inline content)? The system MUST
  truncate the plain-text body at 100,000 bytes (100 KB) and append `[TRUNCATED]` to the
  stored body field. This prevents memory exhaustion and enforces a predictable storage
  footprint. The truncation is applied after HTML-to-plain-text conversion (FR-005).
- What happens when the Gmail mailbox has no emails matching the filter? The sync completes
  successfully with zero results.
- What happens when the database is temporarily unavailable during a sync? Fetched emails
  that cannot be committed must not be silently lost; the error must be surfaced.
- What happens when two concurrent syncs are triggered simultaneously? The system must
  prevent duplicate concurrent sync operations (e.g., debounce or lock).
- What happens when the operator sets the sync cursor to a very early date, resulting in
  thousands of emails to fetch? The sync must handle the volume gracefully, progressing
  incrementally, and the UI must reflect that a long-running sync is in progress.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST connect to Gmail using the OAuth credentials stored in `.env`
  (`GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`) to retrieve emails.

- **FR-002**: The system MUST apply a configurable Gmail search filter (stored as a setting in
  the database, editable from the config page) to determine which emails qualify as visit
  requests. The filter defaults to `in:inbox` if not configured.

- **FR-003**: For each qualifying email, the system MUST store the following in the database:
  Gmail message ID, Gmail thread ID, sender name, sender email address, subject line,
  received date and time, and the email body as plain text.

- **FR-004**: The system MUST use the Gmail message ID as a unique key to prevent duplicate
  records. Re-syncing the same message MUST NOT create a second database record.

- **FR-005**: When an email body is in HTML format, the system MUST convert it to plain text
  before storage. No HTML tags or markup MUST appear in the stored body field.

- **FR-006**: The system MUST expose a "Sync Mail" action that an operator can trigger
  manually from the web UI at any time.

- **FR-007**: After each sync, the system MUST display the outcome to the operator: the number
  of newly stored emails, the number of duplicates skipped, and any errors encountered — all
  within 10 seconds of the sync completing.

- **FR-008**: The system MUST prevent two concurrent sync operations from running
  simultaneously. A second trigger while a sync is in progress MUST be ignored or queued, not
  executed in parallel.

- **FR-009**: When Gmail credentials are invalid, expired, or absent, the system MUST surface
  a descriptive error message in the UI and record the failure in a `MailSyncRun` record —
  without affecting non-mail features.

- **FR-010**: The system MUST handle Gmail API rate-limit responses by backing off and
  retrying up to a configurable number of times before reporting a failure. Already-fetched
  and committed records MUST be preserved.

- **FR-011**: The mail list page MUST display all stored emails in reverse chronological
  order, showing at minimum: sender name, subject, and received date per entry.

- **FR-012**: Selecting an email from the mail list MUST display the full plain-text body.

- **FR-013**: When no emails have been synced yet, the mail list page MUST display an
  informative empty-state message with a prompt to run the first sync.

- **FR-014**: The system MUST support a configurable automatic polling interval (in minutes,
  default: disabled) stored as a setting. When enabled, the system automatically performs a
  sync at the configured interval without requiring a manual trigger. The scheduler MUST be
  implemented using **APScheduler's in-process `AsyncIOScheduler`** (no external message
  broker; `BackgroundScheduler` was rejected because it requires `run_coroutine_threadsafe`
  bridging — see `research.md §8`). The interval MUST be reconfigurable at runtime via the
  config page — changing the value MUST reschedule the job without requiring an application
  restart.

- **FR-015**: When automatic polling fails, the system MUST log the error and update the
  health status — polling MUST resume on the next scheduled interval without crashing the
  application.

- **FR-016**: The existing health-check endpoint's `mail` check MUST remain a
  credential-presence check only (`ok` if all `GMAIL_*` env vars are present and non-empty,
  `unconfigured` otherwise) — no outbound Gmail API call is made, consistent with the
  contract established in feature 001. Live Gmail connectivity status (success, error,
  partial) is surfaced exclusively via the most recent `MailSyncRun` outcome displayed
  in the UI — not via the health endpoint.

- **FR-019**: The mail connector MUST be encapsulated behind a `MailAdapter` interface (analogous to `LLMAdapter` from feature 001). The interface MUST expose at minimum: `fetch_new_emails(since: datetime | None, mail_filter: str = "in:inbox", max_retries: int = 3) -> list[EmailMessage]` (`since=None` = first sync, no date lower bound applied; `mail_filter` and `max_retries` are read from the settings table by the orchestration layer and passed explicitly) and `get_status() -> ConnectorStatus`. The concrete `GmailAdapter` implementation MUST use `google-api-python-client` (Gmail REST API v1). All sync-orchestration code MUST depend only on the `MailAdapter` abstraction — never on `GmailAdapter` directly — so that future adapters (IMAP, Exchange, etc.) can be substituted without modifying orchestration logic.

- **FR-017**: Each sync operation MUST only fetch emails received on or after the timestamp
  of the last successful sync, minus a configurable overlap window (default: 5 minutes).
  The overlap window prevents edge-case gaps caused by clock skew or delivery delays between
  syncs. Already-stored emails within the overlap window MUST be skipped via deduplication
  (FR-004), not stored twice.

- **FR-018**: The system MUST allow an operator to manually set the "last synced at"
  timestamp from the web UI. Setting an earlier timestamp causes the next sync to re-fetch
  all emails from that point forward. This enables recovery from failed syncs or deliberate
  re-ingestion of a historical window.

- **FR-020**: The operator MUST be able to permanently delete individual `IncomingEmail`
  records from the mail list page. Deletion is a hard delete — no `deleted_at` or
  `expires_at` field is used, and no automatic expiry occurs. A confirmation prompt MUST be
  shown before the record is removed. Deleting a stored email does NOT affect the
  corresponding message in Gmail.

- **FR-021**: Before storing an email body, the system MUST enforce a 100 KB hard limit on
  the plain-text body. If the converted plain-text body exceeds 100,000 bytes, it MUST be
  truncated at the 100,000-byte boundary and the literal string `[TRUNCATED]` appended as the
  final content of the stored body field. Truncation is applied after HTML-to-plain-text
  conversion (FR-005). The truncation MUST be visible to the operator when viewing the email
  body in the UI.

- **FR-022**: While a sync operation is in progress, the "Sync Mail" trigger button MUST be
  disabled and its label changed to a spinner with "Syncing…" text. The button MUST return
  to its normal state and the mail list updated once the sync completes (or fails).

### Key Entities

- **MailAdapter** *(interface)*: See FR-019 for the full interface contract. The concrete **GmailAdapter** implements this interface; future adapters (e.g., IMAP, Exchange) implement the same interface without requiring changes to sync orchestration.

- **IncomingEmail**: Represents a single fetched visit request email. Uniquely identified by
  its Gmail message ID. Stores sender identity (name and address), subject, received
  timestamp, plain-text body (capped at 100,000 bytes; bodies exceeding this limit are
  truncated and suffixed with `[TRUNCATED]`), the Gmail thread ID (for future threading
  support), and the timestamp when it was first synced into the application. Content is
  immutable once stored — no in-place field updates after initial fetch. Individual records
  may be permanently deleted by the operator via the UI (hard delete; no `deleted_at` or
  `expires_at` field; no automatic expiry). Deletion does NOT affect the corresponding
  message in Gmail.

- **MailSyncCursor**: Represents the persistent sync state for the mail connector. Stores the
  timestamp of the last successful sync (used as the lower bound for the next fetch window)
  and the configurable overlap window duration. The operator can manually override the
  cursor timestamp from the UI to trigger re-ingestion from an earlier point.

- **MailSyncRun**: Represents a single sync operation. Stores the start time, end time,
  outcome (`success` = all emails fetched and stored without error; `partial` = at least
  one email was stored before an error halted the sync; `failed` = no emails were stored
  and an error occurred), count of new emails stored, count of duplicates skipped, and any
  error message. Every sync — manual or automated — MUST produce a MailSyncRun record.
  This makes sync history fully auditable and allows operators to diagnose past failures.

## Assumptions

- The Gmail account used is the same one configured during the core infrastructure setup; no
  new credential setup is required for this feature beyond what the config page already
  manages.
- The Gmail connector (`GmailAdapter`) uses `google-api-python-client` targeting Gmail REST
  API v1. The adapter is registered as the active `MailAdapter` implementation at application
  startup via dependency injection or a factory — consistent with the `LLMAdapter` pattern
  from feature 001.
- The Gmail search filter is expected to be straightforward (e.g., `in:inbox`,
  `subject:Aanmelding`, or a label name). Advanced Gmail query syntax is supported but not
  required by the UI — the operator enters it as a text string.
- Emails are treated as immutable once stored — field content is never updated in-place after
  the initial fetch. Operators may permanently delete individual records via the UI (FR-020),
  but no in-place edits are supported. If an email is edited or deleted in Gmail after
  syncing, the stored record is unaffected. Reconciliation with Gmail is out of scope
  for this feature.
- Email attachments are not stored in this feature. Only the plain-text body is persisted.
  Attachment handling (download, preview, reference) is a future feature.
- The mail list page displays all stored emails with no pagination limit for this feature.
  Pagination or search within stored emails is a future enhancement.
- A Repair Café event cycle produces a manageable number of visit request emails (typically
  10–200 per event), so performance requirements are modest.
- The OAuth token refresh is handled automatically when the access token expires; the
  operator does not need to manually re-authenticate for routine refresh cycles.
- On the very first sync (no cursor exists), the system fetches all emails matching the
  filter with no date lower bound, then records the current time as the sync cursor.
- Background polling is implemented via **APScheduler's in-process `AsyncIOScheduler`**
  (`BackgroundScheduler` was rejected — see FR-014 and `research.md §8`).
  No external message broker (e.g., Redis, Celery) is required. The scheduler runs inside
  the same process as the web application and is restarted on application startup.

## Clarifications

### Session 2026-02-28

- Q: Should `MailSyncRun` be implemented now as a required entity, or deferred as optional? → A: Implement MailSyncRun now (start/end time, outcome, counts, error message per sync).
- Q: Which Gmail integration approach should be used — Gmail REST API v1, IMAP/SMTP, or a provider-agnostic abstraction from the start? → A: Use Gmail REST API v1 (via `google-api-python-client`) for the first implementation. The connector MUST be placed behind a `MailAdapter` interface — analogous to `LLMAdapter` from feature 001 — so it can be swapped for IMAP or other providers with minimal effort.
- Q: Which background-polling scheduler mechanism should be used? → A: APScheduler in-process AsyncIOScheduler (BackgroundScheduler rejected — requires run_coroutine_threadsafe bridge); no message broker needed; interval configurable at runtime via the config page.
- Q: What is the retention policy for stored IncomingEmail records — should they expire automatically or be kept indefinitely? → A: No automatic expiry. Records kept indefinitely. Operator can delete individual emails via the UI. No deleted_at / expires_at field in the schema.
- Q: What is the maximum body size for a stored email, and how should oversized bodies be handled? → A: 100 KB hard limit (100,000 bytes). Bodies exceeding this limit MUST be truncated at 100,000 bytes and the `[TRUNCATED]` marker appended to the stored body field.
- Q: Should the health-check endpoint's mail check be extended to reflect live Gmail connectivity, or remain credential-presence only? → A: Keep credential-presence only (no outbound API call). Live Gmail status is surfaced via the last MailSyncRun outcome in the UI. Feature 001 health contract is unchanged.
- Q: When is a MailSyncRun outcome "partial" vs "failed"? → A: partial = at least 1 email was stored before an error halted the sync. failed = no emails stored and an error occurred.
- Q: What UI feedback is shown while a sync is in progress? → A: Disable the "Sync Mail" button and replace its label with a spinner + "Syncing…" text. Restore normal state on completion or failure.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A manual sync of up to 200 emails completes and all records appear in the mail
  list within 60 seconds on a Raspberry Pi 5.

- **SC-002**: Zero duplicate email records exist in the database after running the same sync
  operation multiple times in succession.

- **SC-003**: 100% of stored email bodies contain only plain text — no HTML tags, attributes,
  or markup are present in any stored body field.

- **SC-004**: A sync failure (e.g., expired credentials, network unavailable) surfaces a
  descriptive error message in the UI within 10 seconds of the failure occurring.

- **SC-005**: The health-check endpoint correctly reflects the mail credential status
  (`ok` when all `GMAIL_*` env vars are present, `unconfigured` otherwise). The most recent
  `MailSyncRun` outcome is visible in the UI within one page refresh of a sync completing.

- **SC-006**: An operator can complete a first-time sync — from pressing "Sync Mail" to
  seeing the fetched emails in the mail list — in under 2 minutes on a fresh deployment with
  valid credentials.

- **SC-007**: After the operator manually resets the sync cursor to an earlier timestamp,
  the next sync fetches all emails from that point forward, with no emails in that range
  missing from the database (allowing for deduplication of already-stored messages).
