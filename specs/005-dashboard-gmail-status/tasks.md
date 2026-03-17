# Tasks: Dashboard Gmail Connectivity Status Indicator

**Feature**: `005-dashboard-gmail-status`
**Branch**: `005-dashboard-gmail-status`
**Input**: `specs/005-dashboard-gmail-status/plan.md`, `specs/005-dashboard-gmail-status/spec.md`, `specs/005-dashboard-gmail-status/research.md`

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[US1/US2/US3]**: Maps to user story from spec.md
- Exact file paths are included in every task description

---

## Phase 1: Setup — Imports & Logger

**Purpose**: Add all required symbols to `health.py` before any logic is written. No behavioural change; the fragment still works identically after this step.

- [X] T001 Add `get_logger`/`logger`, `AsyncSession`, `Depends`, `get_session`, `GmailCredentialService`, and `mask_email` imports to `backend/src/api/health.py` (do NOT import `ConnectorStatus` — unused in this file; import it directly in the test file from `src.services.mail_service`)

**Checkpoint**: `health.py` imports compile without error; existing `/health/fragment` response is unchanged.

---

## Phase 2: Route Logic — `health_fragment()` changes

**Purpose**: Extend the `health_fragment()` handler with the DB session dependency and all Gmail context variables. This phase delivers the data layer for all three user stories.

- [X] T002 [US1] Add `session: AsyncSession = Depends(get_session)` parameter to `health_fragment()`; derive `gmail_oauth_configured = bool(settings.gmail_client_id and settings.gmail_client_secret)`; initialize `gmail_status: str = "unknown"` and `gmail_account: str | None = None` **before** the try block; call `GmailCredentialService(session).get_connection_status()` inside `try/except Exception`; set `gmail_status = status_enum.value` on success or leave as `"unknown"` on failure; pass `gmail_oauth_configured`, `gmail_status`, and `gmail_account` (the variable reference, not the literal `None`) as template context in `backend/src/api/health.py`
- [X] T003 [US3] Add a **nested** `try/except Exception` block **inside** the outer try (after `gmail_status` is set to `"ok"`): call `GmailCredentialService(session).get()` and apply `mask_email(credential.account_email)` to populate `gmail_account`; catch any exception from this inner call and leave `gmail_account = None` without resetting `gmail_status` — a masked-email fetch failure must not demote a confirmed-OK token status in `backend/src/api/health.py`
- [X] T002b [US1] Update `health_page()` in `backend/src/api/health.py` to also pass `gmail_oauth_configured`, `gmail_status`, and `gmail_account` into its `TemplateResponse` context; extract the Gmail context derivation (T002 + T003 logic) into a private `async def _get_gmail_context(session: AsyncSession) -> dict` helper in the same file so both routes call it with one `await` — ensures `/health/page` and `/health/fragment` render consistent Gmail state

**Checkpoint**: `GET /health/fragment` responds without error in all four token states (ok / unconfigured / token_error / unknown). `GET /health` JSON endpoint is unchanged.

---

## Phase 3: Template — Replace Gmail row with two-row section

**Purpose**: Remove the single legacy "Gmail Credentials" loop entry (`health.mail`) and replace it with two explicit rows that render all required visual states. Both rows link to `/config` satisfying US2.

- [X] T004 [P] [US1] [US2] In `backend/src/templates/health_fragment.html`: remove `("Gmail Credentials", health.mail)` from the `{% set rows %}` loop; add **Row A** ("Gmail App Credentials") below the loop with two states — `✓ Configured` (green `#2e7d32`) when `gmail_oauth_configured` is true, `— Not Configured` (grey `#6c757d`) otherwise, plus an inline `config →` anchor (`href="/config"`)
- [X] T005 [US1] [US2] In `backend/src/templates/health_fragment.html`: add **Row B** ("Gmail OAuth Token") immediately after Row A with four states — `✓ Connected` (green) for `gmail_status == "ok"`, `— Not Connected` (amber `#e65100`) for `"unconfigured"`, `⚠ Token Error` (red `#b71c1c`) for `"token_error"`, `? Unknown` (grey) for all other values, plus an inline `config →` anchor (`href="/config"`) in every state; add `{{ gmail_account }}` span (font-size 0.85rem, colour `#555`) inside the Connected state

**Checkpoint**: Dashboard loads with all four token states rendering the correct badge colour; both rows contain `href="/config"`; the existing Database and LLM/Ollama rows are visually unaffected; `health.mail` is no longer rendered in the HTML fragment.

---

## Phase 4: Tests

**Purpose**: Integration-test the three stories and all acceptance scenarios from `spec.md` using the established `_build_test_app` / `test_engine` fixture pattern from `backend/tests/integration/test_auth_api.py`.

- [X] T006 [P] Create `backend/tests/integration/test_health_fragment_gmail_status.py` with:
  - `TEST_DB_URL = "sqlite+aiosqlite:///:memory:"`
  - `test_engine` / `db_session` async fixtures (same pattern as `test_auth_api.py`)
  - `_build_test_app(test_engine)` factory that includes the health router and overrides `get_session`
  - `client` sync fixture wrapping `TestClient`
  - **TC-01** — `gmail_status="ok"`, `gmail_oauth_configured=True`: mock `get_connection_status()→ConnectorStatus.OK`, `get()→GmailCredential(account_email="alice@example.com")`; assert response contains `✓ Connected` and `al***@example.com`
  - **TC-02** — `gmail_status="unconfigured"`, `gmail_oauth_configured=True`: mock `get_connection_status()→ConnectorStatus.UNCONFIGURED`; assert response contains `— Not Connected`
  - **TC-03** — `gmail_status="token_error"`, `gmail_oauth_configured=True`: mock `get_connection_status()→ConnectorStatus.TOKEN_ERROR`; assert response contains `⚠ Token Error`
  - **TC-04** — DB down (graceful): mock `get_connection_status()` raises `Exception`; assert response contains `? Unknown` and HTTP 200
  - **TC-05** — `gmail_oauth_configured=False`: patch `settings.gmail_client_id=""` and `settings.gmail_client_secret=""`; assert response contains `— Not Configured`
  - **TC-06** — `gmail_oauth_configured=True`: patch `settings.gmail_client_id="x"` and `settings.gmail_client_secret="y"`; assert response contains `✓ Configured`
  - **TC-07** — Connected, sentinel email: mock `get()→GmailCredential(account_email="migrated-from-env")`; assert response contains `(account unknown — please re-authorize)`
  - **TC-08** — Regression: assert response for any state still contains `Database` row text and `LLM / Ollama` row text; also assert at least one known status string (`✓ ok`, `— unconfigured`, or `✗ unreachable`) appears in the Database row context with no HTTP 5xx

**Checkpoint**: All 8 test cases present in file; no imports unresolved.

---

## Phase 5: Polish & Verify

**Purpose**: Confirm all tests pass, no regressions on existing health checks, and the implementation matches the spec's success criteria.

- [X] T007 Run `pytest backend/tests/integration/test_health_fragment_gmail_status.py -v` from the `backend/` directory and fix any failures; confirm all 8 cases pass (green); optionally run `pytest backend/tests/` to verify no regressions on `test_auth_api.py`, `test_mail_api.py`, and unit tests

**Checkpoint**: `pytest` exits 0; SC-004 confirmed (Database and LLM rows unchanged); SC-003 confirmed (`href="/config"` present in both Gmail rows across all states).

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately
- **Phase 2 (Route Logic)**: Depends on Phase 1 (imports must exist first)
  - T002, T003, T002b must execute sequentially (all modify the same file; T003 extends T002's try block; T002b adds the helper and updates `health_page()`)
- **Phase 3 (Template)**: Depends on Phase 2 checkpoint (context vars must be defined before template uses them)
  - T004 and T005 must execute sequentially (T005 appends Row B as a sibling `<tr>` **after** Row A in the same file; sequential execution avoids edit conflicts)
- **Phase 4 (Tests)**: T006 is marked [P] and can start as soon as Phase 3 is complete (tests reference the finished route + template); can also be written speculatively after Phase 2 and run after Phase 3
- **Phase 5 (Verify)**: Depends on Phase 4

### User Story Dependencies

| Story | Satisfied by | Depends on |
|-------|-------------|------------|
| **US1** At-a-glance status | T002, T004, T005 | Phase 1 |
| **US2** Config link navigation | T004, T005 (both rows include `href="/config"`) | US1 template tasks |
| **US3** Masked account email | T003, T005 (gmail_account rendering) | T002 (sets gmail_status), T004 (Connected state row exists) |

### Parallel Opportunities

- T004 (Row A template) and T006 (test file skeleton) can be written in parallel once Phase 2 is done
- T005 (Row B template) cannot start until T004 is committed (same file, sequential edits)
- T007 (verify) must wait for T006

---

## Parallel Example: Phase 3 → Phase 4

```bash
# After Phase 2 route logic is done, these can begin in parallel:
Task: "T004 — Add Row A to health_fragment.html"
Task: "T006 — Draft test file skeleton with fixtures"  # write tests speculatively

# After T004 is committed:
Task: "T005 — Add Row B to health_fragment.html"       # same file, must be sequential

# After T005 is committed, add the remaining test assertions to T006 and run:
Task: "T007 — pytest -v test_health_fragment_gmail_status.py"
```

---

## Implementation Strategy

### MVP First (User Stories 1 + 2 only)

1. Complete Phase 1: Add imports
2. Complete T002: Session dependency + `gmail_oauth_configured` + `get_connection_status` + graceful degradation
3. Complete T004 + T005: Template rows with `/config` links (4 visual states, no masked email yet)
4. **STOP and VALIDATE**: Load dashboard — confirm Row A and Row B render; confirm `/config` links present; confirm DB and LLM rows unchanged
5. Deploy/demo if ready (US1 + US2 fully satisfied)

### Incremental Delivery

1. Setup + Route (T001–T002) → basic data ready
2. Template (T004–T005) → US1 + US2 visible in browser → demo
3. Masked email (T003 + T005 addendum) → US3 visible → demo
4. Tests (T006–T007) → CI green → merge

### File Change Summary

| Task | File | Change type |
|------|------|-------------|
| T001 | `backend/src/api/health.py` | Add import lines |
| T002 | `backend/src/api/health.py` | Extend function signature + add logic block |
| T003 | `backend/src/api/health.py` | Extend existing `try` block |
| T004 | `backend/src/templates/health_fragment.html` | Edit `{% set rows %}` + add new `<tr>` |
| T005 | `backend/src/templates/health_fragment.html` | Add second new `<tr>` |
| T006 | `backend/tests/integration/test_health_fragment_gmail_status.py` | **New file** |
| T007 | _(no file change)_ | Run verification |

---

## Notes

- `HealthResult.mail` is **not modified** — retained for `GET /health` JSON backward compatibility (Docker healthcheck)
- `GET /health` JSON endpoint and `GET /health/page` routes are **not touched**
- `config.html` is **not touched**
- No new DB tables, no new API endpoints
- All inline styles follow the existing `health_fragment.html` convention (`#2e7d32` green, `#e65100` amber, `#b71c1c` red, `#6c757d` grey)
- The test file belongs in `backend/tests/integration/` (same location as `test_auth_api.py`) and follows its `_build_test_app` / `test_engine` / `client` fixture pattern
