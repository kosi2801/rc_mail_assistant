# Contract: Gmail OAuth & Connection Management Endpoints

**Feature**: `003-gmail-oauth-token-db` | **Phase**: 1 (Design) | **Date**: 2025-06-26
**Source**: [spec.md](../spec.md) FR-002, FR-003, FR-005, FR-006, FR-010
**Research**: [research.md](../research.md) R-002, R-003, R-004, R-010

This document defines the full HTTP contract for every endpoint added or modified
by this feature. Existing endpoints (`/mail/*`, `/health/*`, `/config` form fields)
that are **not** changed by this feature are omitted.

---

## New Endpoints

### 1. `GET /auth/gmail/initiate`

Starts the OAuth 2.0 Authorization Code flow. Sets a CSRF state cookie and issues
a redirect to Google's consent screen.

**Router**: `backend/src/api/auth.py`

#### Prerequisites

`GMAIL_CLIENT_ID` and `GMAIL_CLIENT_SECRET` must be set in `.env`. If either is
absent, this endpoint MUST return `503` with an instructional HTML error (not crash).

#### Request

```
GET /auth/gmail/initiate
```

No query parameters. No request body. No authentication required (single-operator,
local-network deployment).

#### Response — Success (`302 Found`)

```
HTTP/1.1 302 Found
Location: https://accounts.google.com/o/oauth2/auth?
    client_id=<GMAIL_CLIENT_ID>
    &redirect_uri=<CALLBACK_URL>
    &response_type=code
    &scope=https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fgmail.readonly
    &state=<state_token>
    &access_type=offline
    &prompt=consent
Set-Cookie: oauth_state=<signed_state>; HttpOnly; SameSite=Lax; Max-Age=600; Path=/; Secure (if HTTPS)
```

| Parameter | Value |
|-----------|-------|
| `scope` | `https://www.googleapis.com/auth/gmail.readonly` |
| `access_type` | `offline` — required to receive a refresh token |
| `prompt` | `consent` — forces Google to re-issue a refresh token on re-authorization |
| `state` | `secrets.token_urlsafe(32)` — plain state value sent to Google |
| `Set-Cookie: oauth_state` | `itsdangerous.URLSafeTimedSerializer` signed version of `state` |

**Cookie details**:

| Attribute | Value |
|-----------|-------|
| Name | `oauth_state` |
| Value | Signed serialization of `state` (via `URLSafeTimedSerializer(SECRET_KEY)`) |
| `HttpOnly` | Yes |
| `SameSite` | `Lax` |
| `Max-Age` | `600` (10 minutes) |
| `Secure` | Yes if `request.url.scheme == "https"` |
| `Path` | `/` |

#### Response — OAuth App Credentials Missing (`302 Found`)

```
HTTP/1.1 302 Found
Location: /config?gmail_error=oauth_unconfigured
```

The operator is redirected to the Configuration page with an error notification.
The event `gmail_initiate_unconfigured` MUST be logged at `WARNING` level.

---

### 2. `GET /auth/gmail/callback`

Receives the authorization code from Google, validates the CSRF state, exchanges
the code for tokens, stores the encrypted refresh token, and redirects the operator
back to the Configuration page.

**Router**: `backend/src/api/auth.py`

#### Request

```
GET /auth/gmail/callback?code=<authorization_code>&state=<state_token>
```

Also handles the error case from Google:

```
GET /auth/gmail/callback?error=access_denied&state=<state_token>
```

| Query Parameter | Description |
|----------------|-------------|
| `code` | One-time authorization code from Google (present on success) |
| `state` | Echo of the `state` value sent at `/initiate` |
| `error` | Google-supplied error string (present on user cancellation / denial) |

**Required Cookie**: `oauth_state` (set by `/initiate`). If absent or expired,
the endpoint MUST return `400`.

#### Processing Steps (success path)

1. Read `oauth_state` cookie → verify `URLSafeTimedSerializer` signature and
   10-minute expiry → raise `400` on `SignatureExpired` or `BadSignature`
2. Compare unsigned `state` cookie value to `state` query param → raise `400` on
   mismatch
3. Delete `oauth_state` cookie (one-use)
4. Call `google_auth_oauthlib.flow.Flow.fetch_token(code=code)` in executor
5. Extract `creds.refresh_token` and `creds.token` (access token for email lookup)
6. Call `gmail.users().getProfile(userId='me')` to retrieve `email_address` — stored for display only (FR-004)
7. Call `GmailCredentialService.upsert(plaintext_token, email_address)`
8. Redirect `302` to `/config?gmail_connected=1`

#### Response — Success (`302 Found`)

```
HTTP/1.1 302 Found
Location: /config?gmail_connected=1
Set-Cookie: oauth_state=; HttpOnly; Max-Age=0; Path=/
```

The `/config` page MUST detect `?gmail_connected=1` and render a success
notification banner (HTMX or template branch).

#### Response — Google Authorization Error / User Cancelled (`302 Found`)

```
HTTP/1.1 302 Found
Location: /config?gmail_error=cancelled
```

The error MUST be logged at `WARNING` level with the Google error string.
No token is stored. The `oauth_state` cookie IS cleared (validation succeeded before the `?error` branch — one-use enforced regardless of outcome).

#### Response — CSRF / State Validation Failure (`400`)

```
HTTP/1.1 400 Bad Request
Content-Type: text/html

<p>Authorization state is invalid or expired. Please try connecting Gmail again.</p>
```

#### Response — DB Write Failure (`302 Found` with error)

```
HTTP/1.1 302 Found
Location: /config?gmail_error=db_write_failed
```

The exception MUST be logged at `ERROR` level. The operator is directed to retry.

#### Security Notes

- The `oauth_state` cookie MUST be deleted immediately after successful validation,
  regardless of whether the DB write succeeds.
- `creds.refresh_token` MUST NOT appear in any log entry (FR-010). Log only
  `account_email` and a boolean `token_stored=True/False`.
- If `creds.refresh_token` is `None` (Google returns this if `prompt=consent` was
  omitted and a token was already issued), the callback MUST redirect to
  `/config?gmail_error=no_refresh_token` with an instructional message.

---

### 3. `POST /auth/gmail/disconnect`

Removes the stored credential and returns the operator to "Not Connected" status.

**Router**: `backend/src/api/auth.py`

#### Request

```
POST /auth/gmail/disconnect
```

No body. No query parameters. Triggered by the "Disconnect" button in the Config page
(`hx-post="/auth/gmail/disconnect"` or a standard form POST).

#### Processing Steps

1. Call `GmailCredentialService.delete()`
2. Log `gmail_disconnected` at `INFO` level
3. If the request includes `HX-Request: true` header, return an HTMX fragment
   rendering the "Not Connected" Gmail status section
4. Otherwise, redirect `302` to `/config?gmail_disconnected=1`

#### Response — HTMX (`200 OK`, `text/html`)

```html
<!-- Replaces #gmail-status-section in config.html -->
<div id="gmail-status-section">
  <p>Status: <strong>Not Connected</strong></p>
  <a href="/auth/gmail/initiate">Connect Gmail</a>
</div>
```

#### Response — Non-HTMX (`302 Found`)

```
HTTP/1.1 302 Found
Location: /config?gmail_disconnected=1
```

---

## Modified Endpoints

### 4. `GET /config` — Template Context Change

**Router**: `backend/src/api/config.py` (existing endpoint, modified)

The handler MUST inject a `gmail_status` context variable for the template.

#### New Template Context Keys

| Key | Type | Description |
|-----|------|-------------|
| `gmail_status` | `str` | One of `"ok"`, `"unconfigured"`, `"token_error"` |
| `gmail_account` | `str \| None` | Masked email (e.g. `re***@gmail.com`), or `None` if not connected |
| `gmail_connected` | `bool` | `True` if `?gmail_connected=1` query param present (success banner) |
| `gmail_error` | `str \| None` | Error key from `?gmail_error=<key>` query param, or `None` |
| `gmail_disconnected` | `bool` | `True` if `?gmail_disconnected=1` query param present (disconnection banner) |
| `gmail_oauth_configured` | `bool` | `True` if both `GMAIL_CLIENT_ID` and `GMAIL_CLIENT_SECRET` are set — controls whether Connect/Re-authorize buttons are active or disabled |

#### Gmail Status Derivation

```python
# In config.py route handler:
from src.services.gmail_credential_service import GmailCredentialService

cred_svc = GmailCredentialService(session)
cred = await cred_svc.get()
gmail_status = (await cred_svc.get_connection_status()).value  # "ok" | "unconfigured" | "token_error"
gmail_account = mask_email(cred.account_email) if cred else None
```

#### Config Page Gmail Section (template contract)

The `config.html` template MUST include a `<fieldset id="gmail-connection-section">`
that renders one of three states:

**State A — Not Connected** (`gmail_status == "unconfigured"`):
```html
<p>Status: <strong style="color:#e65100">Not Connected</strong></p>
<a href="/auth/gmail/initiate"
   style="...button styles...">Connect Gmail</a>
```

**State B — Connected** (`gmail_status == "ok"`):
```html
<p>Status: <strong style="color:#2e7d32">✓ Connected</strong>
   as {{ gmail_account }}</p>
<button hx-post="/auth/gmail/disconnect" hx-target="#gmail-connection-section"
        hx-swap="outerHTML">Disconnect</button>
<a href="/auth/gmail/initiate">Re-authorize</a>
```

**State C — Token Error** (`gmail_status == "token_error"`):
```html
<p>Status: <strong style="color:#b71c1c">⚠ Token Error / Reconnection Required</strong></p>
<p>The stored token is invalid or the application key has changed.
   Re-authorize to restore Gmail access.</p>
<a href="/auth/gmail/initiate">Re-authorize</a>
<button hx-post="/auth/gmail/disconnect" ...>Disconnect</button>
```

---

### 5. `POST /config/test/mail` — DB-Based Check

**Router**: `backend/src/api/config.py` (existing endpoint, modified)

The current implementation checks `settings.gmail_client_id`,
`settings.gmail_client_secret`, `settings.gmail_refresh_token` env vars.
After this feature, it MUST check:

1. Are `GMAIL_CLIENT_ID` and `GMAIL_CLIENT_SECRET` present? (env var check — unchanged)
2. Is a credential row present in `gmail_credentials`? (DB check — new)
3. Does the stored token decrypt without error? (Fernet check — new)

#### Updated Response Matrix

| Condition | Status | Detail message |
|-----------|--------|---------------|
| `GMAIL_CLIENT_ID` or `GMAIL_CLIENT_SECRET` missing | `unconfigured` | "Set GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET in .env" |
| Client creds present, no DB row | `unconfigured` | "No Gmail token stored — connect from the Configuration page" |
| Client creds present, DB row present, decryption OK | `ok` | "Gmail connected as {masked_email}" |
| DB row present, `InvalidToken` raised | `token_error` | "Stored token cannot be decrypted — re-authorize from Configuration" |

The HTML fragment format is unchanged (existing `_test_html` helper); add
`"token_error"` to `_STATUS_STYLES` and `_STATUS_ICONS` dicts.

---

## Error Notification Query Parameters (`/config`)

The `/config` GET handler MUST recognize and surface these query parameters as
template variables so the Jinja2 template can render inline notifications:

| `?param=value` | Template variable | Displayed message |
|----------------|-------------------|-------------------|
| `gmail_connected=1` | `gmail_connected=True` | "✓ Gmail connected successfully." |
| `gmail_disconnected=1` | `gmail_disconnected=True` | "Gmail has been disconnected." |
| `gmail_error=cancelled` | `gmail_error="cancelled"` | "Gmail authorization was cancelled." |
| `gmail_error=no_refresh_token` | `gmail_error="no_refresh_token"` | "Google did not return a refresh token. Try again." |
| `gmail_error=db_write_failed` | `gmail_error="db_write_failed"` | "Failed to save token — please try again." |
| `gmail_error=oauth_unconfigured` | `gmail_error="oauth_unconfigured"` | "Gmail client credentials are not configured." |

---

## Endpoint Summary Table

| Method | Path | Router file | Change |
|--------|------|-------------|--------|
| `GET` | `/auth/gmail/initiate` | `api/auth.py` | **NEW** |
| `GET` | `/auth/gmail/callback` | `api/auth.py` | **NEW** |
| `POST` | `/auth/gmail/disconnect` | `api/auth.py` | **NEW** |
| `GET` | `/config` | `api/config.py` | **MODIFIED** — gmail_status context |
| `POST` | `/config/test/mail` | `api/config.py` | **MODIFIED** — DB-based credential check |

All other existing endpoints are unchanged.

---

## Logging Contract (FR-010 Compliance)

Every log entry produced by the OAuth flow MUST conform to the following:

| Event | Level | Required Fields | Prohibited Fields |
|-------|-------|-----------------|-------------------|
| `gmail_initiate` | INFO | `redirect_uri` | `state` (plain value), any token |
| `gmail_callback_success` | INFO | `account_email` (masked), `token_stored=True` | `refresh_token`, `access_token`, `state` (plain) |
| `gmail_callback_google_error` | WARNING | `error` (Google string) | Any token |
| `gmail_callback_state_expired` | WARNING | — | Any token, `state` value |
| `gmail_callback_bad_signature` | WARNING | — | Any token, `state` value |
| `gmail_callback_state_mismatch` | WARNING | — | Any token, `state` value |
| `gmail_callback_db_write_failed` | ERROR | `error` (exception message) | Any token |
| `gmail_disconnected` | INFO | — | Any token |
| `gmail_token_migrated_from_env` | WARNING | `message` (deprecation instruction) | `refresh_token` value |
| `gmail_decrypt_failed` | WARNING | `reason=InvalidToken` | Ciphertext, token |
