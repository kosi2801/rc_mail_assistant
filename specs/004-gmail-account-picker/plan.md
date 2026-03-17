# Implementation Plan: Gmail Account Picker

**Branch**: `004-gmail-account-picker` | **Date**: 2025-07-21 | **Spec**: [spec.md](spec.md)  
**Input**: Feature specification from `specs/004-gmail-account-picker/spec.md`

## Summary

Force Google's account picker on every "Connect Gmail" OAuth flow so volunteers with
multiple Google accounts in their browser always choose explicitly. Implemented by two
targeted changes to `gmail_initiate()` in `backend/src/api/auth.py`:

1. **P1 — Always show account picker**: Change `prompt="consent"` →
   `prompt="select_account consent"` in the `flow.authorization_url()` call.
2. **P2 — Pre-select on re-auth**: Inject `session: AsyncSession = Depends(get_session)`,
   look up `GmailCredentialService.get()`, and pass `login_hint=credential.account_email`
   when a stored credential row exists.

No new packages, no schema changes, no new endpoints. Total diff: ~10 lines of
production code plus new/updated tests.

## Technical Context

**Language/Version**: Python 3.11+  
**Primary Dependencies**: FastAPI, google-auth-oauthlib, SQLAlchemy (AsyncSession),
itsdangerous — all pre-existing  
**Storage**: PostgreSQL (read-only for this feature — reads `gmail_credentials` row id=1
via `GmailCredentialService.get()`)  
**Testing**: pytest with `TestClient` (async); existing `TestGmailInitiate` class in
`backend/tests/integration/test_auth_api.py`  
**Target Platform**: Linux server (Docker/Portainer on Raspberry Pi 5, 8 GB RAM)  
**Project Type**: Web service (FastAPI)  
**Performance Goals**: N/A — trivial URL parameter change; no measurable latency impact  
**Constraints**: No new Python packages; backward-compatible with existing single-account
flows; `access_type="offline"` MUST be preserved alongside new `prompt` value  
**Scale/Scope**: Single-operator, local-network deployment; one `gmail_credentials` row

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Verdict | Justification |
|-----------|---------|---------------|
| **I — Privacy-First** | ✅ PASS | No new credential storage. `login_hint` uses `account_email` already stored (display-only, non-sensitive). It is passed as a URL query parameter to Google, not persisted or logged in plaintext. Refresh-token handling is unchanged. Exception I.1 scope unaffected. |
| **II — Manual Synchronization** | ✅ PASS | `gmail_initiate()` is triggered exclusively by user action (button click). No background jobs or polling introduced. |
| **III — Minimal Footprint** | ✅ PASS | Zero new dependencies. Two parameter changes within a single existing function. Container images unchanged. |
| **IV — Modular Design** | ✅ PASS | Change stays within `backend/src/api/auth.py`. Consumes the existing `GmailCredentialService.get()` interface — no cross-boundary coupling added. |
| **V — Resilience & Idempotency** | ✅ PASS | `login_hint` is optional and advisory only (FR-004). Absent credential row → graceful fallback, no error. No new DB writes introduced. |

**Gate result: PASS** — no violations; Complexity Tracking section omitted.

**Post-design re-check** (after Phase 1): All five verdicts unchanged. The addendum to
`contracts/auth.md` and the minimal research confirm no new architectural surface was
added. Gate remains PASS.

## Project Structure

### Documentation (this feature)

```text
specs/004-gmail-account-picker/
├── plan.md              ← this file
├── research.md          ← Phase 0 output (minimal — all clarifications resolved in spec)
├── contracts/
│   └── auth.md          ← Phase 1 output (addendum to 003 contract)
└── tasks.md             ← Phase 2 output (speckit.tasks — NOT created here)
```

> `data-model.md` and `quickstart.md` are **omitted** for this feature: no schema
> changes are introduced, and the existing `GmailCredential` model / service layer
> are consumed read-only. A quickstart section is not warranted for a two-line diff.

### Source Code (repository root)

```text
backend/
├── src/
│   └── api/
│       └── auth.py               ← MODIFIED — gmail_initiate() only
└── tests/
    └── integration/
        └── test_auth_api.py      ← MODIFIED — TestGmailInitiate (new test cases)
```

No frontend changes. No model, service, or migration files touched.

**Structure Decision**: Web application layout (backend-only changes). Frontend is
unaffected; the account picker behaviour is entirely driven by Google OAuth URL
parameters constructed server-side.
