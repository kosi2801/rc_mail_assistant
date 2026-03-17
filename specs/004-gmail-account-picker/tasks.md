# Tasks: Gmail Account Picker

**Feature Branch**: `004-gmail-account-picker`  
**Input**: `specs/004-gmail-account-picker/` (spec.md, plan.md, research.md, contracts/auth.md)  
**Scope**: Two targeted changes to `gmail_initiate()` in `backend/src/api/auth.py` + four new test cases in `backend/tests/integration/test_auth_api.py`  
**Tests**: Included — required per feature summary and spec acceptance scenarios

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (US1, US2)

---

## Phase 1: Setup & Foundational

> **Skipped** — no new packages, no schema changes, no project initialization required.  
> The existing `GmailCredentialService`, `get_session`, and test infrastructure are all
> in place and ready to use.

---

## Phase 2: User Story 1 — Account Picker on First Connect (Priority: P1) 🎯 MVP

**Goal**: Every "Connect Gmail" initiation always shows the Google account chooser by
changing `prompt="consent"` → `prompt="select_account consent"` in
`flow.authorization_url()`.

**Independent Test**: Hit `GET /auth/gmail/initiate` with mocked `_build_flow` and
assert the redirect `Location` URL contains both `select_account` and `consent` in the
`prompt` parameter.

### Tests for User Story 1

> **Write these tests FIRST — they MUST fail before T002 is implemented.**

- [X] T001 [P] [US1] Add `test_prompt_contains_select_account` and `test_prompt_contains_consent` to `TestGmailInitiate` in `backend/tests/integration/test_auth_api.py` — mock `_build_flow`, capture `mock_flow.authorization_url.call_args`, assert both `select_account` and `consent` appear in the `prompt` kwarg

### Implementation for User Story 1

- [X] T002 [US1] Change `prompt="consent"` → `prompt="select_account consent"` in the `flow.authorization_url()` call (~line 92) in `backend/src/api/auth.py`

**Checkpoint**: Run `pytest backend/tests/integration/test_auth_api.py::TestGmailInitiate` — all five tests (three pre-existing + two new) must pass. US1 is fully delivered.

---

## Phase 3: User Story 2 — Pre-selected Account on Re-authorization (Priority: P2)

**Goal**: When a credential row already exists, pass `login_hint=account_email` to
`flow.authorization_url()` so Google pre-selects the previously connected account in the
picker. Gracefully omit the hint when no credential exists (FR-004).

**Independent Test**: Two test cases — one with a seeded `GmailCredential` row asserting
`login_hint` kwarg is passed to `authorization_url`, one with an empty DB asserting
`login_hint` is absent.

### Tests for User Story 2

> **Write these tests FIRST — they MUST fail before T004 is implemented.**

- [X] T003 [P] [US2] Add `test_login_hint_present_when_credential_exists` and `test_login_hint_absent_when_no_credential` to `TestGmailInitiate` in `backend/tests/integration/test_auth_api.py` — seed a `GmailCredential` row via `db_session` fixture for the first case; assert `mock_flow.authorization_url.call_args.kwargs` contains / does not contain `login_hint`

### Implementation for User Story 2

- [X] T004 [US2] Update `gmail_initiate()` in `backend/src/api/auth.py`:
  1. Add `session: AsyncSession = Depends(get_session)` to the function signature (mirrors `gmail_callback` / `gmail_disconnect` pattern)
  2. After `flow = _build_flow(redirect_uri)`, add: `credential = await GmailCredentialService(session).get()` and `login_hint = credential.account_email if credential else None`
  3. Replace the `flow.authorization_url(...)` call with the conditional `login_hint` spread per `contracts/auth.md` updated call pattern
  4. Add `login_hint_present=login_hint is not None` to the existing `logger.info("gmail_initiate", ...)` call per logging contract

**Checkpoint**: Run `pytest backend/tests/integration/test_auth_api.py::TestGmailInitiate` — all seven tests must pass. Run full integration suite `pytest backend/tests/integration/` to confirm no regressions.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 2 (US1)**: No dependencies — start immediately
- **Phase 3 (US2)**: No hard dependency on US1 (touches different code paths), but US1 should be complete first for a clean commit history

### Within Each User Story

- Tests (T001, T003) MUST be written and **fail** before their paired implementation tasks (T002, T004)
- T001 and T003 are marked [P] — they touch the same test file but add non-overlapping test cases to `TestGmailInitiate`; they can be written in sequence within one sitting

### Parallel Opportunities

- T001 (test) and T002 (impl) are in **different files** → can be written in parallel by two contributors
- T003 (test) and T004 (impl) are in **different files** → same parallelism applies

---

## Parallel Example: User Story 1

```bash
# Two contributors can work simultaneously:
Task A: "Add select_account/consent tests to TestGmailInitiate in backend/tests/integration/test_auth_api.py"  # T001
Task B: "Change prompt value in gmail_initiate() in backend/src/api/auth.py"                                   # T002
# Merge when both done — no conflict, different files
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. T001 — Write failing tests for prompt value
2. T002 — Change `prompt` value (one-line diff)
3. **STOP and VALIDATE**: `pytest backend/tests/integration/test_auth_api.py::TestGmailInitiate` — all pass
4. **Ship P1**: This alone fixes the reported bug (volunteers silently connecting wrong account)

### Full Delivery (Both Stories)

5. T003 — Write failing tests for login_hint
6. T004 — Inject session + credential lookup + login_hint + log field
7. **VALIDATE**: Full `pytest backend/tests/integration/` suite — zero regressions
8. Manual smoke test: connect with stored credential → verify `login_hint` in auth URL

---

## Notes

- **Total tasks**: 4 (T001–T004)
- **Total test cases added**: 4 (2 per user story)
- **Production lines changed**: ~10 (one-word prompt change + ~8 lines for session/lookup/hint)
- Existing `test_redirect_when_oauth_not_configured`, `test_302_to_google_when_configured`, and `test_oauth_state_cookie_set` must continue passing — no changes to the unconfigured-credentials branch or cookie logic
- `access_type="offline"` MUST remain in the `flow.authorization_url()` call (R-003 / spec §Assumptions)
- The `login_hint` value (email) MUST NOT appear in any log event — only `login_hint_present: bool` is permitted (logging contract addendum)
