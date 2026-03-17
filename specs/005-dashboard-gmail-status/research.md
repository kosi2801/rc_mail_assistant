# Research: Dashboard Gmail Status — Feature 005

**Phase**: 0 — Outline & Research
**Branch**: `005-dashboard-gmail-status`
**Date**: 2026-07-10

---

## R-001 — Health Route Structure

**Decision**: The health fragment route (`GET /health/fragment`) in `backend/src/api/health.py` currently has no database session dependency. It delegates entirely to `get_health()` in `health_service.py`, which only reads environment variables.

**Finding**: Adding Gmail token status requires injecting `AsyncSession` via `Depends(get_session)` into `health_fragment()`. This is the same pattern used by `config_page()` in `backend/src/api/config.py`.

```python
# Current signature (no session):
async def health_fragment(request: Request):

# Required signature after change:
async def health_fragment(request: Request, session: AsyncSession = Depends(get_session)):
```

**Impact**: The JSON health endpoint (`GET /health`) is not modified by this feature. ~~The full health page (`GET /health/page`) is also not modified.~~ **[Superseded by T002b]** `health_page()` was updated to also call `_get_gmail_context(session)` so both routes pass the Gmail context variables to their templates.

---

## R-002 — HealthResult Dataclass and mail Field

**Decision**: The `HealthResult` dataclass (`health_service.py`) is **not modified**. FR-010 explicitly requires the new Gmail data to be supplied as separate template context variables, not fields on `HealthResult`.

**Finding**:
- `HealthResult` has fields: `db: CheckStatus`, `llm: CheckStatus`, `mail: CheckStatus`
- The `mail` field is derived from `_check_mail()` which checks for `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, and `GMAIL_REFRESH_TOKEN` presence — a legacy env-var-only check
- The JSON endpoint (`GET /health`) exposes `mail` under `checks.mail` — retained for backward compatibility with Docker/Portainer healthchecks, but its value is no longer displayed in the HTML health fragment
- The `health_fragment.html` "Gmail Credentials" row is **replaced** by the new two-row Gmail section

**Rationale**: Keeping `HealthResult.mail` avoids breaking the JSON contract consumed by Docker's healthcheck; the HTML fragment is the only consumer of the `mail` display row, and that row is being replaced.

---

## R-003 — GmailCredentialService.get_connection_status()

**Decision**: Use `GmailCredentialService(session).get_connection_status()` as the authoritative source for Gmail token state, wrapped in `try/except Exception` for graceful degradation (FR-008).

**Finding**:
- `get_connection_status()` is defined in `backend/src/services/gmail_credential_service.py`
- It returns `ConnectorStatus` (from `backend/src/services/mail_service.py`): `OK = "ok"`, `UNCONFIGURED = "unconfigured"`, `TOKEN_ERROR = "token_error"` (also `ERROR = "error"` but not returned by this method)
- The method performs no network I/O — only DB reads and local Fernet decrypt — confirming the spec assumption that it is safe to call from the health fragment route
- Already handles missing client credentials internally (returns `UNCONFIGURED` if `gmail_client_id` or `gmail_client_secret` is absent)
- Requires `AsyncSession` injected at `GmailCredentialService.__init__`

**Graceful degradation**: If the DB is unreachable, `get()` will raise; this must be caught and the status reported as `"unknown"` rather than propagating a 500.

---

## R-004 — gmail_oauth_configured Flag

**Decision**: Derive `gmail_oauth_configured: bool` from `settings.gmail_client_id` and `settings.gmail_client_secret` in the route handler, independent of the token status.

**Finding**:
- `settings.gmail_client_id: str = ""` and `settings.gmail_client_secret: str = ""` (both default to empty string)
- Check: `bool(settings.gmail_client_id and settings.gmail_client_secret)`
- This is a pure environment-variable check — no DB access — so it always succeeds regardless of DB health

**Rationale**: This allows the template to render Row A ("Gmail App Credentials") even when the DB is down, providing partial diagnostic value.

---

## R-005 — Masked Account Email (FR-007)

**Decision**: When `gmail_status == "ok"`, call `GmailCredentialService(session).get()` and apply the module-level `mask_email()` function. Pass the result as `gmail_account: str | None`.

**Finding**:
- `GmailCredentialService.get()` returns `GmailCredential | None`
- `GmailCredential` has an `account_email: str` field
- `mask_email()` handles the sentinel `"migrated-from-env"` value gracefully, returning `"(account unknown — please re-authorize)"`
- `get()` is already called internally by `get_connection_status()` — to avoid a second DB round-trip, the service call should be refactored slightly: call `get()` once and pass the record through, OR simply accept a second `get()` call (low cost on local Postgres)

**Implementation choice**: Accept a second `get()` call for simplicity. Since this runs on local Postgres (Raspberry Pi 5, single-tenant), the extra round-trip is negligible and avoids complicating the service interface.

---

## R-006 — HTMX Polling Pattern

**Decision**: No changes needed to the HTMX setup on the dashboard.

**Finding**:
- `dashboard.html` loads the health fragment with `hx-trigger="load"` only — **no timer-based polling**
- The fragment is loaded once on page load, not on an interval
- Adding a DB session dependency to the health fragment route does not affect HTMX behavior

---

## R-007 — Template Design: Replacing the Gmail Credentials Row

**Decision**: Replace the single "Gmail Credentials" table row in `health_fragment.html` with a two-row Gmail section. Both rows share a `<td>` link to `/config`.

**Finding from config.html**:
- Inline styles only — no external CSS framework
- Color conventions already in use: `#2e7d32` (green/ok), `#e65100` (orange/unconfigured), `#b71c1c` (red/error)
- Amber (`#f57f17` or `#e65100`) for "Not Connected" / indeterminate states

**Proposed rows**:
| Row | Label | States |
|-----|-------|--------|
| A | Gmail App Credentials | ✓ Configured (green) / — Not Configured (grey) |
| B | Gmail OAuth Token | ✓ Connected (green) / — Not Connected (amber) / ⚠ Token Error (red) / ? Unknown (grey) |

Both rows link to `/config` via an `<a>` tag wrapping the status badge or appended as a small link.

---

## Summary of Resolved Clarifications

| # | Question | Answer |
|---|----------|--------|
| 1 | Does health_fragment already have a DB session? | **No** — must add `Depends(get_session)` |
| 2 | Modify HealthResult or separate context vars? | **Separate context vars** (FR-010); HealthResult unchanged |
| 3 | How to degrade gracefully when DB down? | **try/except Exception → gmail_status = "unknown"** |
| 4 | How to get masked email? | Call `service.get()` when status is "ok", apply `mask_email()` |
| 5 | Does health fragment poll on a timer? | **No** — `hx-trigger="load"` only |
| 6 | What happens to HealthResult.mail / JSON endpoint? | **Retained in JSON** for backward compat; removed from HTML fragment display |
