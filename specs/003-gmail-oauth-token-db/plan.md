# Implementation Plan: Gmail OAuth Token Secure Storage

**Branch**: `003-gmail-oauth-token-db` | **Date**: 2025-06-26 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/003-gmail-oauth-token-db/spec.md`

## Summary

Move the Gmail OAuth refresh token from `.env` into the application database.
Add an in-app OAuth 2.0 Authorization Code flow (`GET /auth/gmail/initiate` →
Google → `GET /auth/gmail/callback`) so operators can connect, re-authorize, and
disconnect Gmail entirely from the Configuration page. Tokens are Fernet-encrypted
(AES-128-CBC + HMAC-SHA256, key derived from `SECRET_KEY`) before every DB write and
decrypted in memory only at the point of use. The existing `GmailAdapter` is refactored
to accept credentials as explicit constructor parameters; a new
`GmailCredentialService` owns the encrypt/decrypt/upsert/delete lifecycle. A startup
migration path imports any existing `GMAIL_REFRESH_TOKEN` env var into the database
automatically on first boot after upgrade.

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**: FastAPI 0.111+, SQLAlchemy 2.0+ (async), asyncpg 0.29+,
Alembic 1.13+, Jinja2 3.1+ + HTMX, google-api-python-client 2.0+, google-auth 2.0+,
**google-auth-oauthlib** (add explicitly to pyproject.toml — OAuth2 code exchange),
**cryptography** (add to pyproject.toml — Fernet token encryption), structlog 24.1+,
tenacity 8.3+
**Storage**: PostgreSQL via asyncpg; new `gmail_credentials` table — singleton row,
`encrypted_refresh_token TEXT` to accommodate variable-length Fernet ciphertext
**Testing**: pytest 8.1+ with pytest-asyncio (asyncio_mode = auto); existing test suite
under `backend/tests/`
**Target Platform**: Raspberry Pi 5 (arm64), Docker Compose, local LAN; operator
browser must route to the application's callback URL
**Project Type**: Web service — FastAPI backend, Jinja2/HTMX server-rendered UI
(no separate SPA; `frontend/` is empty)
**Performance Goals**: OAuth callback round-trip < 2 s; Config page load < 500 ms;
no change to mail sync throughput
**Constraints**: One Gmail account at a time; no session middleware (CSRF via signed
cookie only); `SECRET_KEY` rotation intentionally invalidates stored token (recovery
via re-auth, no migration utility); `GMAIL_CLIENT_ID` / `GMAIL_CLIENT_SECRET` remain
in `.env`
**Scale/Scope**: Single-operator, single-account; ~1 000 emails/month expected;
no multi-tenancy

## Constitution Check

_GATE: Must pass before Phase 0 research. Re-check after Phase 1 design._

### Principle I — Privacy-First · ⚠️ CONDITIONAL PASS (Amendment Required)

Constitution §I currently states:

> _"Sensitive credentials (Gmail OAuth tokens, API keys) MUST be stored in environment
> variables or a local secrets file that is excluded from version control."_

This feature stores the Gmail refresh token in PostgreSQL — a literal conflict with §I.

**Justification for Exception I.1:**

| Concern | Mitigation |
|---------|-----------|
| Token exposed in DB | Fernet-encrypted (AES-128-CBC + HMAC-SHA256) before every INSERT; ciphertext only ever written to DB |
| Key management | Fernet key derived from `SECRET_KEY` (already required, already in `.env`); key never stored in DB |
| At-rest exposure | Docker volume on local network perimeter; application-layer encryption is a second layer of defence-in-depth |
| Log / response leakage | FR-010 prohibits token in logs, API responses, or browser-visible fields; enforced at service layer |
| Network exposure | No change — database is not exposed outside the local Docker network (Constitution §I final sentence upheld) |

**Why `.env`-only is no longer viable**: The in-app OAuth flow produces tokens at
runtime — they cannot be written back to `.env` by the application. Requiring
operators to copy-paste tokens from an OAuth Playground into a config file is fragile,
error-prone, and blocks the core feature (in-app reconnection). Precedent set by
Exception II.1 (feature `002-gmail-mail-sync`) permits principled, scoped amendments.

**Required action (GATE — must complete before tasks.md):**
Amend `constitution.md` to add **Exception I.1** using the same procedure as
Exception II.1:
- Increment version to `1.2.0`
- Add carve-out under Principle I permitting refresh-token DB storage when:
  (a) the token is Fernet-encrypted with a key derived from `SECRET_KEY`,
  (b) the plaintext is never logged or returned in any response,
  (c) the exception is scoped to OAuth refresh tokens obtained via the in-app flow,
  (d) this feature (`003-gmail-oauth-token-db`) is cited as first-approved instance
- Run propagation check across plan-template.md, spec-template.md, tasks-template.md,
  agent-file-template.md
- Commit the amendment before implementation tasks begin

### Principle II — Manual Synchronization · ✅ PASS

No change to sync-trigger logic. New `/auth/*` endpoints handle OAuth credential
management only; they do not initiate mail sync. Exception II.1 (operator-enabled
scheduler) is untouched.

### Principle III — Minimal Footprint · ✅ PASS

Two new packages:
- `cryptography` — canonical Python crypto library; ~3 MB wheel; Fernet is a
  standard primitive; no alternatives that are lighter and equally safe exist
- `google-auth-oauthlib` — thin wrapper for Google OAuth2 code exchange;
  likely already transitively installed via `google-api-python-client` but not
  pinned; adding it explicitly ensures reproducible builds

No new Docker services. No external cloud dependencies at runtime.
Raspberry Pi 5 memory budget unaffected.

### Principle IV — Modular Design · ✅ PASS

- `GmailCredentialService` encapsulates all Fernet operations and DB access; the
  `GmailAdapter` has zero DB knowledge
- `GmailAdapter.__init__` refactored to accept explicit `refresh_token: str` (no
  more `app_settings.gmail_refresh_token` read-through)
- New `/auth` router is isolated from `/config` and `/mail` routers
- `MailAdapter` ABC interface is unchanged — existing adapter/service contract intact

### Principle V — Resilience & Idempotency · ✅ PASS

- Token upsert uses `INSERT … ON CONFLICT (id) DO UPDATE` — idempotent regardless
  of how many times callback fires
- DB write failure during callback surfaces an actionable error; no partial state
  is written
- Fernet `InvalidToken` on startup is caught; system falls back to `NullMailAdapter`
  with `TOKEN_ERROR` status (same path as revoked token)
- Re-authorization atomically replaces the existing credential record

## Project Structure

### Documentation (this feature)

```text
specs/003-gmail-oauth-token-db/
├── plan.md              ← this file
├── research.md          ← Phase 0 output
├── data-model.md        ← Phase 1 output
├── contracts/
│   └── auth.md          ← Phase 1 output
└── tasks.md             ← Phase 2 output (speckit.tasks — not created by speckit.plan)
```

### Source Code Changes (this feature)

```text
backend/
├── pyproject.toml                              MODIFIED  add cryptography, google-auth-oauthlib
├── .env.example                                MODIFIED  remove GMAIL_REFRESH_TOKEN
├── README.md (repo root)                       MODIFIED  replace OAuth Playground section
├── migrations/versions/
│   └── 0003_create_gmail_credentials.py        NEW       gmail_credentials table
├── src/
│   ├── models/
│   │   └── gmail_credential.py                 NEW       GmailCredential ORM model
│   ├── services/
│   │   └── gmail_credential_service.py         NEW       encrypt/decrypt/upsert/delete/status
│   ├── api/
│   │   └── auth.py                             NEW       /auth/gmail/initiate + /callback + /disconnect
│   ├── adapters/
│   │   └── gmail_adapter.py                    MODIFIED  accept refresh_token as constructor param
│   ├── api/config.py                           MODIFIED  gmail_status in context; test/mail uses DB
│   ├── config.py                               MODIFIED  remove gmail_refresh_token field
│   ├── main.py                                 MODIFIED  startup migration + DB-based adapter wiring
│   └── templates/
│       └── config.html                         MODIFIED  Gmail connection section (Connect / Re-auth / Disconnect)
└── tests/
    ├── unit/
    │   ├── test_gmail_credential_service.py     NEW
    │   └── test_gmail_adapter.py               MODIFIED  update credential construction tests
    └── integration/
        └── test_auth_api.py                    NEW
```

**Structure Decision**: Backend-only (Option 2 — web application backend subtree).
No frontend directory changes — UI is fully server-rendered via Jinja2 + HTMX,
consistent with all existing features.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|--------------------------------------|
| Constitution §I literal conflict — refresh token in DB | In-app OAuth flow produces tokens at runtime; the application cannot write back to `.env` | `.env`-only approach requires operators to copy-paste tokens from OAuth Playground — breaks in-app reconnect, which is the entire purpose of the feature |
