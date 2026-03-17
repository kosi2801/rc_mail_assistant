# Tasks: Gmail OAuth Token Secure Storage

**Feature**: `003-gmail-oauth-token-db` | **Branch**: `003-gmail-oauth-token-db`
**Input**: Design documents from `/specs/003-gmail-oauth-token-db/`
**Prerequisites**: plan.md ✅ · spec.md ✅ · research.md ✅ · data-model.md ✅ · contracts/auth.md ✅
**Constitution Check**: ⚠️ CONDITIONAL PASS — Amendment to v1.2.0 required (T001, first task)

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no blocking dependencies on incomplete tasks)
- **[Story]**: User story label — [US1] Connect Gmail · [US2] Re-authorize/Disconnect · [US3] Env Migration
- Exact file paths included in every task description

---

## Phase 1: Setup (Constitution Amendment + Package Setup)

**Purpose**: Governance gate and dependency declaration — MUST complete before any implementation begins.

> ⛔ **HARD GATE**: T001 is non-negotiable. No implementation task may proceed until the
> constitution amendment is committed. This mirrors the procedure used for Exception II.1
> (feature `002-gmail-mail-sync`).

- [X] T001 Amend `.specify/memory/constitution.md` to v1.2.0: increment version, add Exception I.1 under Principle I permitting Fernet-encrypted refresh-token storage in DB when (a) key derived from `SECRET_KEY`, (b) plaintext never logged or returned in any response, (c) scoped to OAuth refresh tokens obtained via the in-app flow, (d) feature `003-gmail-oauth-token-db` cited as first-approved instance; run propagation check across `.specify/templates/plan-template.md`, `.specify/templates/spec-template.md`, `.specify/templates/tasks-template.md`, `.specify/templates/agent-file-template.md`; commit the amendment before T002+
- [X] T002 [P] Add `cryptography` and `google-auth-oauthlib` as explicit dependencies with version pins to `backend/pyproject.toml`

**Checkpoint**: Constitution v1.2.0 committed, new packages declared — implementation may begin.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure — shared DB model, migration, enum extension, settings annotation — that ALL user stories depend on.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T003 Add `TOKEN_ERROR = "token_error"` as a new variant to the `ConnectorStatus` enum in `backend/src/services/mail_service.py`
- [X] T004 [P] Create `GmailCredential` ORM model (singleton `id=1`, `encrypted_refresh_token TEXT NOT NULL`, `account_email VARCHAR(255) NOT NULL`, `connected_at TIMESTAMP WITH TIME ZONE`, `updated_at TIMESTAMP WITH TIME ZONE`) in `backend/src/models/gmail_credential.py`
- [X] T005 [P] Create Alembic migration `0003_create_gmail_credentials.py` with `revision="0003"`, `down_revision="0002"`, `upgrade()` creating the `gmail_credentials` table and `downgrade()` dropping it in `backend/migrations/versions/0003_create_gmail_credentials.py`
- [X] T006 [P] Register `GmailCredential` import in `backend/src/models/__init__.py` so Alembic autogenerate can discover the new table
- [X] T007 Annotate `gmail_refresh_token: str = ""` in `backend/src/config.py` with a deprecation comment (field kept temporarily for FR-009 startup migration; do NOT remove yet; `.env.example` entry removed separately in T027)

**Checkpoint**: Foundation ready — `TOKEN_ERROR` usable, `gmail_credentials` table migratable, model importable. User story implementation may begin.

---

## Phase 3: User Story 1 — Connect Gmail from the Configuration Page (Priority: P1) 🎯 MVP

**Goal**: Operator with no `GMAIL_REFRESH_TOKEN` in `.env` can click "Connect Gmail" on the Config page, complete Google OAuth consent, and have a working mail sync — all without editing any config file.

**Independent Test**: Start a fresh instance with no `GMAIL_REFRESH_TOKEN` in `.env`. Click "Connect Gmail" on the Config page, complete the Google OAuth consent screen, then verify: (a) the `gmail_credentials` table contains exactly one row with `id=1`; (b) the Config page status changes to "✓ Connected"; (c) triggering a mail sync succeeds using the DB-stored token.

### Tests for User Story 1

> Write these tests FIRST. They MUST fail before T010 implementation begins.

- [X] T008 [P] [US1] Write unit tests for `GmailCredentialService.get()`, `upsert()`, `decrypt_token()`, and `get_connection_status()` (including `UNCONFIGURED`, `OK`, and `TOKEN_ERROR` branches; mock Fernet and DB session) in `backend/tests/unit/test_gmail_credential_service.py`
- [X] T009 [P] [US1] Write integration tests for `GET /auth/gmail/initiate` (302 to Google, `oauth_state` cookie set; 503 when `GMAIL_CLIENT_ID` missing) and `GET /auth/gmail/callback` in `backend/tests/integration/test_auth_api.py`. Test cases:
  **Success path**: valid state cookie + code → upsert row → redirect `/config?gmail_connected=1`; assert no `refresh_token` value appears in captured log output (FR-010, SC-004).
  **Error paths**: (1) `?error=access_denied` → redirect `/config?gmail_error=cancelled`, `oauth_state` cookie cleared; (2) expired/missing `oauth_state` cookie → `400`; (3) `creds.refresh_token = None` → redirect `/config?gmail_error=no_refresh_token`.
  **Concurrent-tab CSRF**: two `/initiate` requests in sequence → second `/initiate` overwrites cookie → first callback (with old state) returns `400` rather than storing a stale token. This is the correct, secure outcome — document it as expected behaviour in a test comment.

### Implementation for User Story 1

- [X] T010 [US1] Implement `GmailCredentialService` with `_make_fernet()` helper (SHA-256 of `SECRET_KEY` → Fernet key), `get()`, `upsert()` (pg upsert `ON CONFLICT (id) DO UPDATE`), `decrypt_token()` (raises `cryptography.fernet.InvalidToken` on bad key), and `get_connection_status()` (`UNCONFIGURED` / `OK` / `TOKEN_ERROR`) in `backend/src/services/gmail_credential_service.py`; include module-level `mask_email()` helper per research.md R-010
- [X] T011 [P] [US1] Refactor `GmailAdapter.__init__` to accept explicit `refresh_token: str`, `client_id: str`, `client_secret: str` parameters; remove all `app_settings.gmail_*` reads from the adapter in `backend/src/adapters/gmail_adapter.py`
- [X] T012 [US1] Create `backend/src/api/auth.py`; implement `GET /auth/gmail/initiate`: check for `GMAIL_CLIENT_ID`/`GMAIL_CLIENT_SECRET` (503 if absent), generate `secrets.token_urlsafe(32)` state, sign with `itsdangerous.URLSafeTimedSerializer(SECRET_KEY)`, set `oauth_state` cookie (`HttpOnly`, `SameSite=Lax`, `Max-Age=600`, `Secure=request.url.scheme == "https"`), build `google_auth_oauthlib.flow.Flow` with `access_type=offline`, `prompt=consent`, `scope=gmail.readonly`, return `302` to Google consent URL
- [X] T013 [US1] Implement `GET /auth/gmail/callback` in `backend/src/api/auth.py`: read and verify `oauth_state` cookie (`URLSafeTimedSerializer.loads` with `max_age=600`; `400` on `SignatureExpired`/`BadSignature`); compare state to query param (`400` on mismatch); clear cookie; handle `?error=` from Google (redirect `/config?gmail_error=cancelled`); call `Flow.fetch_token(code=code)` in executor; retrieve account email via `gmail.users().getProfile(userId='me')`; call `GmailCredentialService.upsert()`; redirect `302` to `/config?gmail_connected=1`; handle `creds.refresh_token is None` → `/config?gmail_error=no_refresh_token`; handle DB write failure → `/config?gmail_error=db_write_failed`; log all events per contracts/auth.md logging contract (FR-010: no token in logs)
- [X] T014 [US1] Register `/auth` router in `backend/src/main.py` and update lifespan to wire `GmailAdapter` from the DB credential: after migrations, call `GmailCredentialService(session).get()` and `decrypt_token()` (catch `InvalidToken` → fall back to `NullMailAdapter` with `TOKEN_ERROR` status); pass explicit `refresh_token`, `client_id`, `client_secret` to `GmailAdapter.__init__`
- [X] T015 [P] [US1] Update `GET /config` handler in `backend/src/api/config.py` to inject the following into the Jinja2 template context using `GmailCredentialService`: `gmail_status` (`ConnectorStatus.value`), `gmail_account` (masked email or `None`), `gmail_connected` (`bool` from `?gmail_connected=1`), `gmail_error` (`str | None` from `?gmail_error=<key>`), `gmail_disconnected` (`bool` from `?gmail_disconnected=1`), and `gmail_oauth_configured` (`bool(settings.gmail_client_id and settings.gmail_client_secret)` — used to disable the Connect button when app credentials are absent)
- [X] T016 [P] [US1] Add `<fieldset id="gmail-connection-section">` to `backend/src/templates/config.html` with: State A (Not Connected) — if `gmail_oauth_configured` render `<a href="/auth/gmail/initiate">Connect Gmail</a>`, else render a disabled button labelled "Connect Gmail (app credentials required)" with instructional text pointing to `.env`; State B (Connected — masked email + placeholder Re-authorize link + Disconnect button stub); inline notification banners for `gmail_connected`, `gmail_error`, and `gmail_disconnected` query params

**Checkpoint**: User Story 1 fully functional. Fresh-instance OAuth flow works end-to-end. Mail sync reads from DB. Config page shows "Connected".

---

## Phase 4: User Story 2 — Re-authorize or Disconnect Gmail (Priority: P2)

**Goal**: Operator with an invalid/revoked token sees "Token Error" on the Config page and can re-authorize via the same OAuth flow, or disconnect entirely via a single click.

**Independent Test**: Insert an intentionally invalid ciphertext row (`id=1`) directly into `gmail_credentials`. Load the Config page — verify "⚠ Token Error / Reconnection Required" status and the Re-authorize link are shown. Click "Disconnect" — verify the row is deleted and status returns to "Not Connected". Click "Re-authorize" — complete OAuth flow — verify new row is stored and status returns to "✓ Connected".

### Tests for User Story 2

> Write these tests FIRST. They MUST fail before T019 implementation begins.

- [X] T017 [P] [US2] Write unit tests for `GmailCredentialService.delete()` (row deleted, idempotent when no row exists) and `TOKEN_ERROR` branch in `get_connection_status()` (mock `Fernet.decrypt` raising `InvalidToken`) in `backend/tests/unit/test_gmail_credential_service.py`
- [X] T018 [P] [US2] Write integration tests for `POST /auth/gmail/disconnect`: HTMX path (`HX-Request: true` header → 200 with HTML fragment replacing `#gmail-connection-section`); non-HTMX path (302 to `/config?gmail_disconnected=1`) in `backend/tests/integration/test_auth_api.py`

### Implementation for User Story 2

- [X] T019 [US2] Add `delete()` method to `GmailCredentialService` in `backend/src/services/gmail_credential_service.py` (`DELETE FROM gmail_credentials WHERE id=1`; idempotent — no-op if no row; log `gmail_disconnected` at INFO level)
- [X] T020 [US2] Implement `POST /auth/gmail/disconnect` in `backend/src/api/auth.py`: call `GmailCredentialService.delete()`; detect `HX-Request` header — if present return 200 HTML fragment with State A markup (suitable for `hx-target="#gmail-connection-section"`, `hx-swap="outerHTML"`); otherwise redirect `302` to `/config?gmail_disconnected=1`
- [X] T021 [US2] Add State C rendering (Token Error / Reconnection Required — Re-authorize link + Disconnect button with HTMX attrs) and `gmail_disconnected` notification banner to `backend/src/templates/config.html`; wire State B's Disconnect button HTMX attrs (`hx-post="/auth/gmail/disconnect"`, `hx-target="#gmail-connection-section"`, `hx-swap="outerHTML"`) and Re-authorize link (`href="/auth/gmail/initiate"`)
- [X] T022 [US2] Update `POST /config/test/mail` in `backend/src/api/config.py` to use DB-based credential check: (1) verify `GMAIL_CLIENT_ID`/`GMAIL_CLIENT_SECRET` env vars present; (2) call `GmailCredentialService.get()` — `UNCONFIGURED` if no row; (3) call `decrypt_token()` — `TOKEN_ERROR` on `InvalidToken`; add `"token_error"` to `_STATUS_STYLES` and `_STATUS_ICONS` dicts; remove env-var `gmail_refresh_token` check
- [X] T023 [US2] Update `backend/tests/unit/test_gmail_adapter.py` to reflect the new explicit-credential `GmailAdapter.__init__` signature (`refresh_token`, `client_id`, `client_secret`); remove any tests that previously patched `app_settings.gmail_*` fields

**Checkpoint**: User Stories 1 and 2 both independently functional. Operator can connect, re-authorize, and disconnect Gmail entirely from the Config page UI.

---

## Phase 5: User Story 3 — Transparent Operation After Token Migration (Priority: P3)

**Goal**: Existing operators upgrading with `GMAIL_REFRESH_TOKEN` in `.env` have it silently imported into the database on first boot — no manual action required — and receive a logged deprecation notice.

**Independent Test**: Start the upgraded application with `GMAIL_REFRESH_TOKEN=<valid_token>` set in `.env` and an empty `gmail_credentials` table. Verify: (a) a deprecation warning appears in structured logs; (b) the `gmail_credentials` table now has `id=1` with `account_email="migrated-from-env"`; (c) removing `GMAIL_REFRESH_TOKEN` from `.env` and restarting causes no errors and mail sync still works.

### Tests for User Story 3

> Write these tests FIRST. They MUST fail before T025 implementation begins.

- [X] T024 [P] [US3] Write unit tests for `GmailCredentialService.maybe_migrate_from_env()`: (1) env var present + no DB row → upsert called + deprecation warning logged; (2) env var present + row already exists → no upsert, advisory warning logged; (3) env var absent → complete no-op in `backend/tests/unit/test_gmail_credential_service.py`

### Implementation for User Story 3

- [X] T025 [US3] Implement `GmailCredentialService.maybe_migrate_from_env()` in `backend/src/services/gmail_credential_service.py`: (1) check `settings.gmail_refresh_token` non-empty; (2) check if DB row exists via `get()`; (3) if env present + no row: call `upsert(plaintext_token=settings.gmail_refresh_token, account_email="migrated-from-env")`, emit `logger.warning("gmail_token_migrated_from_env", message="GMAIL_REFRESH_TOKEN has been imported into the database. Remove it from .env at your convenience.")` (FR-010: no token value in log); (4) if env present + row exists: emit advisory warning to remove redundant env var; (5) if env absent: no-op
- [X] T026 [US3] Call `await GmailCredentialService(session).maybe_migrate_from_env()` in `backend/src/main.py` lifespan, after Alembic migrations complete and before adapter wiring (T014 lifespan block)

**Checkpoint**: All three user stories independently functional. Upgrade path for existing operators is transparent and logged.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Documentation cleanup, test hygiene, and transitive-dependency verification.

- [X] T027 [P] Remove `GMAIL_REFRESH_TOKEN=<your-refresh-token>` entry from `backend/.env.example` (FR-008); add a comment directing operators to use the in-app "Connect Gmail" button on the Configuration page
- [X] T028 [P] Update `README.md`: replace the "Obtain a refresh token via OAuth Playground" section with instructions to use the in-app "Connect Gmail" button on the Configuration page; keep Google Cloud project and OAuth client setup steps (`GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`) intact (FR-008)
- [X] T029 [P] Verify `itsdangerous` is available as a transitive dependency (`python -c "import itsdangerous; print(itsdangerous.__version__)"` inside the backend container/venv); add explicit pin to `backend/pyproject.toml` only if verification fails (research.md R-009)

---

## Dependencies & Execution Order

### Phase Dependencies

```
Phase 1: Setup         → No dependencies — start immediately
Phase 2: Foundational  → Depends on Phase 1 completion (constitution committed) — BLOCKS all user stories
Phase 3: US1 (P1)      → Depends on Phase 2 completion
Phase 4: US2 (P2)      → Depends on Phase 3 completion (builds on GmailCredentialService, auth.py, config.html from US1)
Phase 5: US3 (P3)      → Depends on T010 completion (Phase 3 — US1). T024 (test, mocks service) may be written in parallel with Phase 3; T025–T026 (implementation) MUST wait for T010 to be merged.
Phase 6: Polish        → Depends on Phase 5 completion (all stories done)
```

### User Story Dependencies

| Story | Depends On | Independent? |
|-------|------------|--------------|
| US1 (P1) — Connect Gmail | Foundational (T003–T007) | ✅ Yes — no other story required |
| US2 (P2) — Re-auth/Disconnect | US1 complete (`GmailCredentialService`, `auth.py`, `config.html` created) | ⚠️ Partial — US1 creates the files US2 extends |
| US3 (P3) — Env Migration | Foundational only (`GmailCredentialService` from T010 needed) | ✅ Yes — independently testable from US1/US2 |

> **Note on US2 dependency**: US2 *extends* `auth.py`, `config.html`, and `GmailCredentialService` created in US1. US2 is independently *testable* (insert bad DB row, verify UI) but US1 must be implemented first since US2 adds to those files.

### Within Each User Story

```
Tests (T008/T009, T017/T018, T024) → written FIRST, fail before implementation
Models/Service (T010)              → before endpoints (T012, T013)
GmailAdapter refactor (T011)       → parallel with T010 (different file)
Endpoints (T012 → T013)            → T012 creates file; T013 adds to it (sequential)
Router + lifespan wiring (T014)    → after T010, T011, T012, T013
Config handler (T015)              → parallel with T012/T013 (different file)
Template (T016)                    → parallel with T012/T013 (different file)
```

### Critical Sequential Chain (US1)

```
T003 → T004 → T006 → T010 → T012 → T013 → T014
                   ↘
              T011 (parallel)
                   ↗
              T015 (parallel) → T016 (parallel)
```

---

## Parallel Execution Examples

### Phase 2 — Foundational (run together)

```
Task: "Add TOKEN_ERROR to ConnectorStatus in backend/src/services/mail_service.py"  (T003)
Task: "Create GmailCredential ORM model in backend/src/models/gmail_credential.py"  (T004)
Task: "Create Alembic migration 0003 in backend/migrations/versions/"               (T005)
Task: "Register GmailCredential in backend/src/models/__init__.py"                  (T006)
```

### Phase 3 — User Story 1 (parallel opportunities)

```
# Tests — write together first:
Task: "Unit tests for GmailCredentialService in backend/tests/unit/test_gmail_credential_service.py"  (T008)
Task: "Integration tests for /auth/gmail/* in backend/tests/integration/test_auth_api.py"             (T009)

# Implementation — parallel after T010:
Task: "Refactor GmailAdapter constructor in backend/src/adapters/gmail_adapter.py"       (T011)
Task: "Update GET /config handler in backend/src/api/config.py"                          (T015)
Task: "Add Gmail connection fieldset to backend/src/templates/config.html"               (T016)
```

### Phase 6 — Polish (all parallelizable)

```
Task: "Remove GMAIL_REFRESH_TOKEN from backend/.env.example"  (T027)
Task: "Update README.md Connect Gmail instructions"            (T028)
Task: "Verify itsdangerous transitive availability"            (T029)
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup — commit constitution amendment
2. Complete Phase 2: Foundational — migrate DB, extend enum
3. Complete Phase 3: User Story 1 — full OAuth connect flow, DB wiring, Config page
4. **STOP and VALIDATE**: Test US1 acceptance scenarios independently
5. Deploy/demo — operators can connect Gmail in-app; `.env` `GMAIL_REFRESH_TOKEN` no longer required

### Incremental Delivery

1. **Phase 1 + 2 → Foundation** ready; can run `alembic upgrade head`
2. **+ Phase 3 (US1)** → In-app Gmail connect works end-to-end → **Demo/Deploy (MVP)**
3. **+ Phase 4 (US2)** → Re-authorize and Disconnect available; token error recovery complete
4. **+ Phase 5 (US3)** → Existing `.env` operators seamlessly upgraded on restart
5. **+ Phase 6** → Docs cleaned up, env example corrected

### Suggested Single-Developer Sequence

```
T001 → T002 → T003, T004, T005, T006 (parallel) → T007 →
T008, T009 (parallel, write tests first) →
T010 → T011 (parallel), T015 (parallel), T016 (parallel) →
T012 → T013 → T014 →
T017, T018 (parallel, write tests first) →
T019 → T020 → T021 → T022 → T023 →
T024 (write test first) → T025 → T026 →
T027, T028, T029 (parallel)
```

---

## Task Summary

| Phase | Tasks | Count |
|-------|-------|-------|
| Phase 1: Setup | T001–T002 | 2 |
| Phase 2: Foundational | T003–T007 | 5 |
| Phase 3: US1 — Connect Gmail (P1) | T008–T016 | 9 |
| Phase 4: US2 — Re-auth/Disconnect (P2) | T017–T023 | 7 |
| Phase 5: US3 — Env Migration (P3) | T024–T026 | 3 |
| Phase 6: Polish | T027–T029 | 3 |
| **Total** | | **29** |

**Parallel opportunities**: 14 tasks marked [P]
**Test tasks**: T008, T009 (US1), T017, T018 (US2), T024 (US3) — 5 tasks
**New files**: `gmail_credential.py`, `0003_create_gmail_credentials.py`, `gmail_credential_service.py`, `auth.py`, `test_gmail_credential_service.py`, `test_auth_api.py`
**Modified files**: `mail_service.py`, `models/__init__.py`, `config.py`, `main.py`, `gmail_adapter.py`, `config.py (api)`, `config.html`, `test_gmail_adapter.py`, `pyproject.toml`, `.env.example`, `README.md`, `.specify/memory/constitution.md`

---

## Notes

- **[P]** = different files, no dependency on an incomplete same-phase task — safe to parallelize
- **[US1/US2/US3]** = maps task to user story from spec.md for traceability
- T001 (constitution amendment) is a non-negotiable hard gate before any code change
- `gmail_refresh_token` field stays in `backend/src/config.py` through this feature (needed by FR-009); it will be removed in a future feature after the migration period ends — do NOT remove it here
- `itsdangerous.URLSafeTimedSerializer` is used for CSRF state signing (R-003); it is a transitive dep of Starlette/FastAPI — verify before adding explicit pin (T029)
- Fernet key derivation: `base64.urlsafe_b64encode(hashlib.sha256(settings.secret_key.encode()).digest())` — documented in research.md R-001; intentionally invalidated by `SECRET_KEY` rotation (recovery via re-auth, no migration utility)
- `SECRET_KEY` rotation → `InvalidToken` → caught in lifespan → `NullMailAdapter` + `TOKEN_ERROR` status; operator re-authorizes via US2 flow
- Commit after each phase checkpoint at minimum; commit after T001 before any implementation
