# Contract Addendum: Gmail OAuth — Account Picker Parameters

**Feature**: `004-gmail-account-picker` | **Phase**: 1 (Design) | **Date**: 2025-07-21  
**Base contract**: [`specs/003-gmail-oauth-token-db/contracts/auth.md`](../../003-gmail-oauth-token-db/contracts/auth.md)  
**Source**: spec.md FR-001, FR-003, FR-004 | research.md R-001, R-002, R-003

This document is an **addendum** to the `003` auth contract. Only the sections that
change are listed here. All other behaviour, error responses, cookie contract, CSRF
flow, callback processing, disconnect endpoint, and logging contract remain exactly
as specified in the base contract.

---

## Modified Endpoint: `GET /auth/gmail/initiate`

### What changes

Two changes to the `flow.authorization_url()` call in `gmail_initiate()`:

1. **`prompt` parameter** — value changes from `"consent"` to `"select_account consent"`
2. **`login_hint` parameter** — new optional parameter; present only when a stored
   credential row exists

### New signature

```python
@router.get("/gmail/initiate")
async def gmail_initiate(
    request: Request,
    session: AsyncSession = Depends(get_session),   # ← NEW (P2)
):
```

The `session` dependency is added to support the server-side `login_hint` lookup
(FR-003). It follows the same pattern already used in `gmail_callback` and
`gmail_disconnect`.

### Updated `authorization_url()` call

**Before** (feature 003):
```python
auth_url, _ = flow.authorization_url(
    access_type="offline",
    prompt="consent",
    state=state,
)
```

**After** (this feature):
```python
credential = await GmailCredentialService(session).get()
login_hint = credential.account_email if credential else None

auth_url, _ = flow.authorization_url(
    access_type="offline",
    prompt="select_account consent",
    state=state,
    **({"login_hint": login_hint} if login_hint else {}),
)
```

### Updated Response — Success (`302 Found`)

The `Location` header now contains updated OAuth parameters:

```
HTTP/1.1 302 Found
Location: https://accounts.google.com/o/oauth2/auth?
    client_id=<GMAIL_CLIENT_ID>
    &redirect_uri=<CALLBACK_URL>
    &response_type=code
    &scope=https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fgmail.readonly
    &state=<state_token>
    &access_type=offline
    &prompt=select_account+consent
    [&login_hint=<account_email>]
Set-Cookie: oauth_state=<signed_state>; HttpOnly; SameSite=Lax; Max-Age=600; Path=/; Secure (if HTTPS)
```

### Updated OAuth parameter table

| Parameter | Value | Change |
|-----------|-------|--------|
| `scope` | `https://www.googleapis.com/auth/gmail.readonly` | unchanged |
| `access_type` | `offline` — required for refresh token | unchanged |
| `prompt` | `select_account consent` — forces account picker AND re-consent (refresh token guaranteed) | **CHANGED** from `consent` |
| `state` | `secrets.token_urlsafe(32)` | unchanged |
| `login_hint` | `account_email` from `GmailCredential` row (id=1) when present — absent on first connection | **NEW** (optional) |
| `Set-Cookie: oauth_state` | `URLSafeTimedSerializer` signed `state` | unchanged |

### Behaviour matrix

| Scenario | `prompt` | `login_hint` present? | Account picker shown? | Refresh token issued? |
|----------|----------|-----------------------|-----------------------|-----------------------|
| First connect (no credential row) | `select_account consent` | No | ✅ Always | ✅ Always |
| Re-authorize (credential row exists) | `select_account consent` | Yes (stored email) | ✅ Always, pre-selected | ✅ Always |
| After disconnect (row deleted) | `select_account consent` | No | ✅ Always | ✅ Always |
| Stored email absent / malformed (FR-004) | `select_account consent` | No (falls back) | ✅ Always | ✅ Always |

### Fallback contract (FR-004)

If `GmailCredentialService.get()` returns `None` (no stored credential), or if the
`account_email` field is empty or falsy, the endpoint MUST proceed **without** a
`login_hint`. The absence of a `login_hint` MUST NOT cause an error or alter the
CSRF/cookie flow in any way.

### Logging contract addendum

The existing `gmail_initiate` INFO log event gains one optional field:

| Event | Level | Required Fields | New optional field | Prohibited |
|-------|-------|-----------------|--------------------|------------|
| `gmail_initiate` | INFO | `redirect_uri` | `login_hint_present: bool` | `login_hint` value (email), `state` plain value, any token |

> Rationale: logging *whether* a hint was present aids diagnostics without exposing PII.

---

## No Other Changes

The following are explicitly **unchanged** by this feature:

- `GET /auth/gmail/callback` — processes the result of the account picker unchanged;
  stores the email returned by `gmail.users().getProfile()`, not the `login_hint`.
- `POST /auth/gmail/disconnect`
- `GET /config` and `POST /config/test/mail`
- All cookie attributes, CSRF validation, error responses, and error query parameters.
