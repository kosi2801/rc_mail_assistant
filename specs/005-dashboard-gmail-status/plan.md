# Implementation Plan: Dashboard Gmail Connectivity Status Indicator

**Branch**: `005-dashboard-gmail-status` | **Date**: 2026-07-10 | **Spec**: `specs/005-dashboard-gmail-status/spec.md`
**Input**: Feature specification from `/specs/005-dashboard-gmail-status/spec.md`

## Summary

Add a Gmail status section to the dashboard health fragment that replaces the existing env-var-only "Gmail Credentials" row with two complementary indicators: (1) OAuth2 client credential presence (`gmail_oauth_configured: bool`) and (2) live token connectivity state derived from `GmailCredentialService.get_connection_status()`. Both indicators render as rows in the existing health table, both link to `/config`, and the masked account email is shown when connected. The change touches three files: `health.py` (route), `health_service.py` (no structural change, `mail` field retained for JSON backward compat), and `health_fragment.html` (template). No new DB tables, no new API endpoints.

## Technical Context

**Language/Version**: Python 3.11  
**Primary Dependencies**: FastAPI, SQLAlchemy (async), Jinja2, Fernet (`cryptography`), HTMX (frontend)  
**Storage**: PostgreSQL (local Docker); read-only access from health fragment route  
**Testing**: pytest + pytest-asyncio  
**Target Platform**: Linux (Raspberry Pi 5, Docker Compose via Portainer)  
**Project Type**: Web service (FastAPI backend + Jinja2 server-side templates)  
**Performance Goals**: No perceptible latency increase; health fragment already includes a DB check, so an additional DB read is negligible  
**Constraints**: Inline styles only (no external CSS framework); single-tenant; no network I/O in health fragment  
**Scale/Scope**: Single operator; display-only change; three files modified

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Principle I — Privacy-First ✅ PASS

The feature reads the `GmailCredential` row to obtain `account_email` (stored plaintext for display) and to perform a local Fernet decrypt to validate the token. It does **not** return or log the plaintext token or the ciphertext. The masked email (`mask_email()`) is all that is surfaced in the browser. Exception I.1 is already in effect for the credential storage introduced by feature 003; this feature is read-only with respect to that record.

### Principle II — Manual Synchronization ✅ PASS

The health fragment is triggered by the operator loading the dashboard page (`hx-trigger="load"`). No automatic background polling or timer-based reloading is introduced. The Gmail status check is a passive read, not a sync trigger.

### Principle III — Minimal Footprint ✅ PASS

Three files modified. No new dependencies. No Docker image changes. The DB session pattern (`Depends(get_session)`) is already used throughout the codebase.

### Principle IV — Modular Design ✅ PASS

`GmailCredentialService` is used through its defined service interface. The health fragment route calls the service at the call-site (same pattern as `config.py`) — no cross-boundary direct imports.

### Principle V — Resilience & Idempotency ✅ PASS

The `get_connection_status()` call is wrapped in `try/except Exception` (FR-008). A DB outage degrades the Gmail status to `"unknown"` rather than crashing the health fragment. The `db` health check already surfaces DB reachability separately, so the operator has the full picture.

**Constitution Check result: ALL PASS — cleared to proceed.**

---

*Post-Phase 1 re-check*: Design adds no new principles-relevant concerns. DB access is read-only, scoped to the existing `gmail_credentials` table, and behind the same graceful-degradation guard. **Re-check: PASS.**

## Project Structure

### Documentation (this feature)

```text
specs/005-dashboard-gmail-status/
├── plan.md        ✅ this file
├── research.md    ✅ Phase 0 output
└── tasks.md       (Phase 2 — produced by /speckit.tasks)
```

*No `data-model.md` (no schema changes), no `contracts/` (no new endpoints), no `quickstart.md` (display-only change with no new setup steps).*

### Source Files Modified

```text
backend/
├── src/
│   ├── api/
│   │   └── health.py                          # Add session dependency to health_fragment()
│   └── templates/
│       └── health_fragment.html               # Replace Gmail Credentials row with new section
└── tests/
    └── test_health_fragment_gmail_status.py   # New test file (unit + integration)
```

*`health_service.py` is read-only in this feature — `HealthResult.mail` is retained unchanged for the JSON endpoint's backward compatibility.*

## Phase 0: Research Findings

All NEEDS CLARIFICATION items resolved. See `research.md` for full findings. Summary:

| # | Question | Resolution |
|---|----------|------------|
| R-001 | Does `health_fragment` have a DB session? | No — add `Depends(get_session)` |
| R-002 | Modify `HealthResult` or separate context vars? | Separate vars (FR-010); `HealthResult` unchanged |
| R-003 | Graceful degradation when DB down? | `try/except Exception → gmail_status = "unknown"` |
| R-004 | `gmail_oauth_configured` source | `bool(settings.gmail_client_id and settings.gmail_client_secret)` |
| R-005 | Masked email | Call `service.get()` when status is `"ok"`, apply `mask_email()` |
| R-006 | HTMX polling? | `hx-trigger="load"` only — no timer |
| R-007 | `HealthResult.mail` fate | Retained in JSON; row removed from HTML fragment |

## Phase 1: Design

### 1. Route Change — `backend/src/api/health.py`

**Add imports**:
```python
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends
from src.database import get_session
from src.config import settings
from src.services.gmail_credential_service import GmailCredentialService, mask_email
```

**Updated `health_fragment` handler** (calls shared helper):
```python
async def _get_gmail_context(session: AsyncSession) -> dict:
    """Shared Gmail context derivation for health_fragment and health_page (FR-010)."""
    gmail_oauth_configured: bool = bool(
        settings.gmail_client_id and settings.gmail_client_secret
    )
    gmail_status: str = "unknown"
    gmail_account: str | None = None
    try:
        service = GmailCredentialService(session)
        status_enum = await service.get_connection_status()
        gmail_status = status_enum.value  # "ok" | "unconfigured" | "token_error"

        # FR-007: nested try so a masked-email failure never demotes a confirmed-OK status
        if gmail_status == "ok":
            try:
                credential = await service.get()
                if credential and credential.account_email:
                    gmail_account = mask_email(credential.account_email)
            except Exception:
                pass  # gmail_account stays None; gmail_status is preserved
    except Exception:
        logger.warning("health_fragment_gmail_status_failed")
        gmail_status = "unknown"

    return {
        "gmail_oauth_configured": gmail_oauth_configured,
        "gmail_status": gmail_status,
        "gmail_account": gmail_account,
    }


@router.get("/health/fragment", response_class=HTMLResponse)
async def health_fragment(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    result = await get_health()
    gmail_ctx = await _get_gmail_context(session)
    return templates.TemplateResponse(
        request, "health_fragment.html", {"health": result, **gmail_ctx}
    )


@router.get("/health/page", response_class=HTMLResponse)
async def health_page(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    result = await get_health()
    gmail_ctx = await _get_gmail_context(session)
    return templates.TemplateResponse(
        request, "health.html", {"health": result, **gmail_ctx}
    )
```

---

### 2. Template Change — `backend/src/templates/health_fragment.html`

Replace the existing single "Gmail Credentials" row (which uses `health.mail`) with a two-row Gmail section. Both rows link to `/config`.

**Current (to be replaced)**:
```html
{% set rows = [("Database", health.db), ("LLM / Ollama", health.llm), ("Gmail Credentials", health.mail)] %}
{% for name, check in rows %}
<tr ...>
  <td>{{ name }}</td>
  <td>{% if check.value == "ok" %}...{% endif %}</td>
</tr>
{% endfor %}
```

**Replacement strategy**: Keep the Database and LLM rows in the loop (they are unchanged). Add the two Gmail rows as separate, explicitly rendered rows after the loop.

**New template structure** (the two `{% set rows %}` items remain for DB and LLM; Gmail rows added after):

```html
<div id="health-status">
  <table style="width:100%;border-collapse:collapse">
    <thead>
      <tr style="text-align:left;border-bottom:1px solid #dee2e6">
        <th style="padding:0.5rem 0.75rem">Service</th>
        <th style="padding:0.5rem 0.75rem">Status</th>
      </tr>
    </thead>
    <tbody>
      {# Stable rows: Database, LLM/Ollama #}
      {% set rows = [("Database", health.db), ("LLM / Ollama", health.llm)] %}
      {% for name, check in rows %}
      <tr style="border-bottom:1px solid #f1f3f5">
        <td style="padding:0.5rem 0.75rem">{{ name }}</td>
        <td style="padding:0.5rem 0.75rem">
          {% if check.value == "ok" %}
            <span style="color:#2e7d32;font-weight:600">✓ ok</span>
          {% elif check.value == "unconfigured" %}
            <span style="color:#e65100">— unconfigured</span>
          {% else %}
            <span style="color:#b71c1c;font-weight:600">✗ unreachable</span>
          {% endif %}
        </td>
      </tr>
      {% endfor %}

      {# Row A: Gmail App Credentials (env-var presence, always renderable) #}
      <tr style="border-bottom:1px solid #f1f3f5">
        <td style="padding:0.5rem 0.75rem">Gmail App Credentials</td>
        <td style="padding:0.5rem 0.75rem">
          {% if gmail_oauth_configured %}
            <span style="color:#2e7d32;font-weight:600">✓ Configured</span>
          {% else %}
            <span style="color:#6c757d">— Not Configured</span>
          {% endif %}
          <a href="/config" style="margin-left:0.5rem;font-size:0.8rem;color:#1565c0">config →</a>
        </td>
      </tr>

      {# Row B: Gmail OAuth Token (DB-backed, with graceful degradation) #}
      <tr style="border-bottom:1px solid #f1f3f5">
        <td style="padding:0.5rem 0.75rem">Gmail OAuth Token</td>
        <td style="padding:0.5rem 0.75rem">
          {% if gmail_status == "ok" %}
            <span style="color:#2e7d32;font-weight:600">✓ Connected</span>
            {% if gmail_account %}
              <span style="color:#555;font-size:0.85rem"> — {{ gmail_account }}</span>
            {% endif %}
          {% elif gmail_status == "token_error" %}
            <span style="color:#b71c1c;font-weight:600">⚠ Token Error</span>
          {% elif gmail_status == "unconfigured" %}
            <span style="color:#e65100">— Not Connected</span>
          {% else %}
            <span style="color:#6c757d">? Unknown</span>
          {% endif %}
          <a href="/config" style="margin-left:0.5rem;font-size:0.8rem;color:#1565c0">config →</a>
        </td>
      </tr>
    </tbody>
  </table>
  <p style="margin-top:0.75rem;font-size:0.8rem;color:#6c757d">
    Overall: <strong>{{ health.overall }}</strong>
  </p>
</div>
```

---

### 3. Test Strategy — `backend/tests/test_health_fragment_gmail_status.py`

Tests use FastAPI `TestClient` (or async test client) with mocked `GmailCredentialService` and `settings`.

| Test case | Setup | Expected template context |
|-----------|-------|--------------------------|
| TC-01: Connected with email | `get_connection_status()→OK`, `get()→credential(email="alice@example.com")` | `gmail_status="ok"`, `gmail_account="al***@example.com"`, `gmail_oauth_configured=True` |
| TC-02: Not connected | `get_connection_status()→UNCONFIGURED` | `gmail_status="unconfigured"`, `gmail_account=None` |
| TC-03: Token error | `get_connection_status()→TOKEN_ERROR` | `gmail_status="token_error"`, `gmail_account=None` |
| TC-04: DB down (graceful) | `get_connection_status()` raises `Exception` | `gmail_status="unknown"`, `gmail_account=None` |
| TC-05: OAuth creds absent | `settings.gmail_client_id=""` | `gmail_oauth_configured=False` |
| TC-06: OAuth creds present | `settings.gmail_client_id="x"`, `settings.gmail_client_secret="y"` | `gmail_oauth_configured=True` |
| TC-07: Connected, no email (sentinel) | `get()→credential(email="migrated-from-env")` | `gmail_account="(account unknown — please re-authorize)"` |
| TC-08: Regression — DB row intact | DB row rendered, LLM row rendered | no regressions on existing rows |

---

### 4. Scope Boundaries

| Item | Decision |
|------|----------|
| `health_service.py` — `_check_mail()` | Unchanged; still checks env-var triple for the JSON endpoint |
| `HealthResult.mail` field | Retained; still returned in `GET /health` JSON response |
| `GET /health` JSON endpoint | Unchanged; backward compatible |
| `GET /health/page` full page route | **Updated** — `health_page()` must also pass `gmail_oauth_configured`, `gmail_status`, `gmail_account`; shared via `_get_gmail_context(session)` helper (T002b) |
| `health.html` (full page template) | Unchanged — embeds `health_fragment.html` via include; picks up Row A/B automatically once the template is updated |
| `GmailCredentialService` | Unchanged; consumed read-only |
| `config.html` / config routes | Unchanged |
| DB schema | No changes |
| New API endpoints | None |

## Complexity Tracking

*No Constitution Check violations — section not applicable.*
