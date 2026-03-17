# Feature Specification: Gmail OAuth Token Secure Storage

**Feature Branch**: `003-gmail-oauth-token-db`
**Created**: 2025-03-17
**Status**: Draft
**Input**: User description: "Rework Gmail OAuth token storage — move GMAIL_REFRESH_TOKEN from .env to database, add token retrieval/refresh button in Mail Settings configuration page"

## Clarifications

### Session 2026-03-16

- Q: How should the OAuth Authorization Code flow be initiated and what callback URL pattern should be used? → A: Standard redirect — `GET /auth/gmail/initiate` issues a 302 to Google's consent screen; Google redirects back to `GET /auth/gmail/callback` (fixed path). The operator registers `http://<host>/auth/gmail/callback` in Google Cloud Console.
- Q: Should the refresh token be encrypted at the application layer or rely solely on deployment-environment encryption? → A: Application-layer encryption using existing `SECRET_KEY` + `cryptography` (Fernet) — token encrypted before INSERT, decrypted on SELECT.
- Q: What is the scope of FR-008's documentation cleanup? → A: Remove `GMAIL_REFRESH_TOKEN` from `.env.example` entirely; replace the README's OAuth Playground section with instructions to use the in-app Connect Gmail button — keep Google Cloud project and OAuth client setup steps.
- Q: How should the OAuth `state` parameter be stored between `/initiate` and `/callback` for CSRF validation? → A: Signed `HttpOnly` cookie set at `/initiate`, validated and cleared at `/callback` — 10-minute expiry, no new DB table required.
- Q: What should happen if `SECRET_KEY` is rotated after a token is stored, making the stored ciphertext unreadable? → A: Treat as "Token Error / Reconnection Required" — catch the decryption error, surface the standard re-authorize prompt (same recovery path as US2), no migration utility needed.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Connect Gmail from the Configuration Page (Priority: P1)

A Repair Café coordinator sets up the application for the first time (or after a reset). They
open the Configuration page, navigate to the Mail Settings section, and see a "Connect Gmail"
button. Clicking it opens Google's account authorization screen in their browser. After
granting access, they are returned to the Configuration page with a confirmation that Gmail
is now connected. From that point on, mail sync works without any changes to the `.env` file.

**Why this priority**: This is the entire purpose of the feature. Everything else — refresh,
status display, transparent operation — depends on this initial authorization flow working end
to end. An operator who cannot connect Gmail cannot use any mail feature.

**Independent Test**: Can be fully tested on a fresh instance with no `GMAIL_REFRESH_TOKEN` in
`.env`, by clicking "Connect Gmail" on the Config page, completing the Google OAuth consent
screen, and verifying that: (a) the token is stored in the database, (b) the status indicator
changes to "Connected", and (c) triggering a mail sync fetches emails successfully — all
without ever editing a config file.

**Acceptance Scenarios**:

1. **Given** no Gmail token is stored and the Config page is open, **When** the operator
   clicks "Connect Gmail", **Then** their browser is directed to Google's OAuth consent screen
   listing the required mail access permissions.

2. **Given** the operator completes the Google consent screen, **When** Google redirects back
   to the application, **Then** the application stores the token in the database and shows a
   success confirmation on the Config page with the connected account's email address visible.

3. **Given** Gmail is successfully connected, **When** the operator triggers a mail sync,
   **Then** the sync completes using the database-stored token and no `GMAIL_REFRESH_TOKEN` is
   required in `.env`.

4. **Given** the operator cancels the Google consent screen, **When** they are returned to the
   Config page, **Then** the Gmail status remains "Not Connected" and a clear message explains
   that authorization was cancelled.

---

### User Story 2 — Re-authorize or Disconnect Gmail (Priority: P2)

A coordinator whose Gmail connection has become invalid (e.g., the token was revoked from
Google Account settings, or credentials were rotated) returns to the Configuration page. They
see that the Gmail status shows an error or expired state. They can click "Re-authorize" to
go through the OAuth flow again and restore the connection, or click "Disconnect" to remove
the stored token entirely and start fresh.

**Why this priority**: Once connected, tokens can and do expire or get revoked. Without a
recovery path, the operator would be stuck with broken mail sync and no way to fix it from
the UI. This story makes the feature operationally complete.

**Independent Test**: Can be fully tested by inserting an intentionally invalid token record
into the database, loading the Config page, verifying the error status is shown, clicking
"Re-authorize", completing the OAuth flow, and confirming that a subsequent mail sync
succeeds.

**Acceptance Scenarios**:

1. **Given** a token is stored but has been revoked or has expired, **When** the operator
   opens the Config page, **Then** the Mail Settings section displays a "Token Error" or
   "Reconnection Required" status with a prompt to re-authorize.

2. **Given** the error status is shown, **When** the operator clicks "Re-authorize" and
   completes the OAuth flow, **Then** the old token record is replaced with the new one and
   the status returns to "Connected".

3. **Given** a valid token is stored, **When** the operator clicks "Disconnect", **Then** the
   token is removed from the database, the status changes to "Not Connected", and subsequent
   mail sync attempts display a clear "Not authorized" message instead of silently failing.

4. **Given** Gmail is not connected, **When** the operator attempts to trigger a mail sync,
   **Then** the mail sync page shows a human-readable error directing them to connect Gmail
   from the Configuration page.

---

### User Story 3 — Transparent Operation After Token Migration (Priority: P3)

An operator who previously used `GMAIL_REFRESH_TOKEN` in their `.env` file upgrades the
application to this version. Without any required action on their part, the application
detects the legacy token in `.env`, imports it into the database automatically on first
startup after upgrade, removes the dependency on the env var going forward, and logs a
deprecation notice advising them to remove the unused variable from `.env` at their
convenience.

**Why this priority**: This story protects existing operators from a breaking change. However,
it delivers no new capability — it only smooths the upgrade path. Operators on a fresh install
are unaffected.

**Independent Test**: Can be fully tested by starting the upgraded application with
`GMAIL_REFRESH_TOKEN` still set in `.env`, verifying the deprecation warning appears in logs,
confirming the token is now stored in the database, and then removing the env var and
restarting — confirming mail sync still works.

**Acceptance Scenarios**:

1. **Given** `GMAIL_REFRESH_TOKEN` is present in `.env` and no token is stored in the
   database, **When** the application starts, **Then** it imports the token into the database,
   logs a structured deprecation warning with instructions to remove the env var, and
   continues without error.

2. **Given** `GMAIL_REFRESH_TOKEN` is present in `.env` AND a token is already stored in the
   database, **When** the application starts, **Then** the database value is used and the env
   var is ignored; a warning is logged advising removal of the redundant env var.

3. **Given** the token has been migrated to the database, **When** the operator removes
   `GMAIL_REFRESH_TOKEN` from `.env` and restarts, **Then** the application starts cleanly,
   uses the database token, and no errors are raised.

---

### Edge Cases

- **`SECRET_KEY` rotation**: If `SECRET_KEY` changes after a token is stored, Fernet
  decryption will fail. This MUST be caught and treated identically to a revoked token:
  the status is set to "Token Error / Reconnection Required" and the operator re-authorizes
  via the standard US2 flow. A log entry MUST note the decryption failure cause.

- **OAuth callback unreachable**: The operator's browser cannot reach the application's
  callback URL (e.g., accessing the app via an IP the browser can't route back to).
  The application must detect the authorization failure and display a recoverable error
  rather than hanging or showing an unhandled exception.

- **Database unavailable during token storage**: If the database connection drops between the
  OAuth callback and the token write, the operator must receive an error message and be able
  to retry the authorization without clearing existing state.

- **Simultaneous authorization attempts**: If two browser tabs initiate the OAuth flow
  concurrently, the second `/auth/gmail/initiate` request overwrites the `oauth_state`
  cookie set by the first. Tab 1's subsequent callback will fail CSRF validation (state
  mismatch → `400`). This is the correct, secure outcome — Tab 1's flow is abandoned
  and the operator can retry. The database upsert (`ON CONFLICT DO UPDATE`) ensures
  the second tab's successful callback does not produce duplicate rows.

- **Token stored but `GMAIL_CLIENT_ID`/`GMAIL_CLIENT_SECRET` missing**: If the OAuth app
  credentials are absent from `.env`, all authorization actions must fail gracefully with
  an instructional error (not a crash), and the button must be disabled or labeled to
  indicate that app credentials are required first.

- **Very long token values**: OAuth tokens can be several hundred characters; the storage
  mechanism must not truncate them.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The Mail Settings section of the Configuration page MUST display a "Connect
  Gmail" button when no valid token is stored in the database.

- **FR-002**: Clicking "Connect Gmail" MUST initiate the Gmail OAuth 2.0 Authorization Code
  flow via `GET /auth/gmail/initiate`, which issues a 302 redirect to Google's consent screen.
  A `state` parameter MUST be generated, stored in a signed `HttpOnly` cookie (`SameSite=Lax`,
  10-minute expiry) set at `/initiate`, and validated at `/callback` to prevent CSRF attacks.
  The operator must register `http://<host>/auth/gmail/callback` as an authorised redirect URI
  in Google Cloud Console.

- **FR-003**: After the operator authorizes access, Google redirects to `GET
  /auth/gmail/callback`. The application MUST exchange the authorization code for tokens,
  validate the `state` parameter, store the refresh token in the application database, and
  redirect the operator back to the Configuration page with a success notification.

- **FR-004**: The Mail Settings section MUST display the current Gmail connection status
  at all times: one of **Connected** (with masked account identifier), **Not Connected**,
  or **Token Error / Reconnection Required**.

- **FR-005**: When a token is already stored, the Mail Settings section MUST provide a
  "Re-authorize" action and a "Disconnect" action as alternatives to the "Connect Gmail"
  button.

- **FR-006**: The "Disconnect" action MUST remove the stored token from the database and
  return the status to "Not Connected".

- **FR-007**: All Gmail mail sync and connection-test operations MUST read the OAuth
  refresh token exclusively from the database; the `GMAIL_REFRESH_TOKEN` environment
  variable MUST no longer be required or read during normal operation.

- **FR-008**: `GMAIL_REFRESH_TOKEN` MUST be removed from `.env.example`. The README's
  "Obtain a refresh token via OAuth Playground" section MUST be replaced with instructions to
  use the in-app "Connect Gmail" button. The Google Cloud project and OAuth client setup steps
  (covering `GMAIL_CLIENT_ID` and `GMAIL_CLIENT_SECRET`) MUST remain in the README.

- **FR-009**: On application startup, if `GMAIL_REFRESH_TOKEN` is detected in the
  environment and no token exists in the database, the system MUST automatically import
  the env var value into the database, log a structured deprecation warning, and continue
  without error (migration path for existing operators).

- **FR-010**: The stored refresh token MUST NOT appear in application logs, structured
  log output, API responses, or any browser-visible content. Only a masked account
  identifier (e.g., partial email address) and connection status may be surfaced to
  the operator.

- **FR-011**: When the stored token is invalid, expired, or cannot be decrypted (e.g., due
  to `SECRET_KEY` rotation), the system MUST catch the error, set the connection status to
  "Token Error / Reconnection Required", log the failure cause, and return a clear, actionable
  error message directing the operator to re-authorize from the Configuration page, rather
  than failing silently.

- **FR-012**: The refresh token MUST be encrypted using Fernet symmetric encryption (from the
  `cryptography` package) before being written to the database, using a key derived from the
  application's `SECRET_KEY` environment variable. It MUST be decrypted in memory only at the
  point of use (e.g., building OAuth credentials for a sync). The ciphertext column MUST be
  typed `TEXT` to accommodate variable-length encrypted values.

### Key Entities

- **Gmail Credential Record**: Represents the stored OAuth authorization for a single Gmail
  account. Key attributes: connection status, the account email address (for display), the
  authorization timestamp, and the Fernet-encrypted refresh token (ciphertext stored as TEXT;
  decrypted in memory only at point of use). Only one credential record is active at a time.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator with no `GMAIL_REFRESH_TOKEN` in `.env` can fully authorize Gmail
  and reach a "Connected" status within 3 minutes of clicking "Connect Gmail" for the first
  time.

- **SC-002**: Gmail connection status (Connected / Not Connected / Token Error) is visible
  on the Configuration page at all times without requiring any additional action from the
  operator.

- **SC-003**: Mail sync continues to work without modification or redeployment after the
  token is migrated from `.env` to the database for an existing installation.

- **SC-004**: Zero OAuth token values appear in application logs, browser network responses,
  or any user-visible field — verifiable by searching structured log output and inspecting
  API responses after a successful authorization.

- **SC-005**: An operator who has lost Gmail access (revoked or expired token) can restore a
  working mail sync connection entirely from the Configuration page UI, with no file editing
  required.

## Assumptions

- `GMAIL_CLIENT_ID` and `GMAIL_CLIENT_SECRET` remain in `.env` as before; only the
  user-specific refresh token moves to the database. These are OAuth app credentials, not
  user session data, and are stable across authorizations.

- The operator's browser can reach the application's local network address for the OAuth
  callback redirect. Configuration of the allowed redirect URI in Google Cloud Console
  remains the operator's responsibility (as it is today).

- The application supports exactly one Gmail account connection at a time. Multi-account
  support is out of scope.

- Token refresh (automatically obtaining a new access token from a valid refresh token) is
  handled transparently by the existing Gmail adapter without changes to this feature's
  stored credential.

- Database-at-rest encryption is provided by the deployment environment (local network
  perimeter, Docker volume). Application-level Fernet encryption of the stored token (using
  `SECRET_KEY`) is **in scope** for this feature and directly addresses the Constitution §I
  concern.

## Out of Scope

- Multi-account Gmail connections
- Automatic token refresh triggered by the UI (token refresh is handled silently during
  mail sync operations as it is today)
- Any change to how `GMAIL_CLIENT_ID` or `GMAIL_CLIENT_SECRET` are managed
- Email sending or outbound OAuth scopes
- Any cloud-hosted OAuth proxy or relay
