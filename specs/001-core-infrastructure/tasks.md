---
description: "Task list for core infrastructure implementation"
---

# Tasks: Core Infrastructure

**Input**: Design documents from `/specs/001-core-infrastructure/`
**Prerequisites**: plan.md ✅ spec.md ✅ research.md ✅ data-model.md ✅ contracts/health-and-config.md ✅

**Tests**: Not requested — test tasks omitted.

**Organization**: Tasks are grouped by user story to enable independent implementation and
testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)

---

## Phase 1: Setup

**Purpose**: Repository and project skeleton initialisation.

- [x] T001 Create directory structure: `backend/src/`, `backend/src/models/`, `backend/src/services/`, `backend/src/api/`, `backend/src/templates/`, `backend/migrations/`, `backend/tests/unit/`, `backend/tests/integration/`
- [x] T002 [P] Create `backend/pyproject.toml` with dependencies: fastapi, uvicorn[standard], sqlalchemy[asyncio], asyncpg, alembic, tenacity, structlog, python-multipart, jinja2, httpx, pydantic-settings, pytest, pytest-asyncio
- [x] T003 [P] Create `.env.example` at repo root documenting all env vars: `POSTGRES_PASSWORD`, `SECRET_KEY`, `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`, `OLLAMA_BASE_URL`, `DB_CONNECT_ATTEMPTS`, `DB_CONNECT_DELAY_SECONDS`
- [x] T004 [P] Create `docker-compose.yml` defining services: `postgres` (with `HEALTHCHECK: pg_isready`) mounted to a named volume `postgres_data` for data persistence across restarts (required by FR-003/SC-003), `backend` (with `depends_on: postgres: condition: service_healthy`), and `ollama` under `profiles: [ai]`; declare `volumes: postgres_data:` at top level
- [x] T005 [P] Create `backend/Dockerfile` using `python:3.11-slim` (ARM64-compatible); install dependencies via pyproject.toml; non-root user; expose port 8000

---

## Phase 2: Foundational

**Purpose**: Core infrastructure that MUST be complete before any user story can be implemented.

⚠️ **CRITICAL**: No user story work can begin until this phase is complete.

- [x] T006 Create `backend/src/config.py` — pydantic-settings `Settings` class reading all env vars from `.env`; include `db_connect_attempts: int = 5`, `db_connect_delay_seconds: int = 2`, and `secret_key: str = Field(...)` (required, no default — pydantic raises `ValidationError` on startup if absent, which `main.py` lifespan catches and exits per FR-009/FR-014)
- [x] T007 Create `backend/src/logging_config.py` — configure structlog with `JSONRenderer`; add a custom processor that redacts any key whose name contains `token`, `secret`, `password`, `key`, or `credential` before rendering; bind `service` field to each logger
- [x] T008 Create `backend/src/database.py` — async SQLAlchemy engine + `AsyncSession` factory; `connect_with_retry()` function using `tenacity` `@retry(wait=wait_exponential(min=delay, max=10), stop=stop_after_attempt(n))` wrapping a test query; raises `SystemExit(1)` with a descriptive log message on `RetryError`
- [x] T009 Create `backend/migrations/env.py` and `backend/migrations/alembic.ini` — Alembic async setup pointing to `DATABASE_URL` from settings
- [x] T010 Create `backend/migrations/versions/0001_create_settings_table.py` — Alembic migration creating `settings` table with columns: `id` (PK), `key` (VARCHAR 255, UNIQUE, NOT NULL), `value` (TEXT NOT NULL), `updated_at` (TIMESTAMPTZ, default `now()`)
- [x] T011 Create `backend/src/main.py` — FastAPI app factory with `lifespan` handler that: (1) calls `logging_config.configure()`, (2) calls `database.connect_with_retry()`, (3) runs Alembic migrations programmatically (`alembic upgrade head`), (4) mounts Jinja2 templates; include `StaticFiles` mount for future assets
- [x] T012 Create `backend/src/templates/base.html` — base Jinja2 layout with: `<head>` block, `<nav>` with links (Health, Config), `{% block content %}`, and a conditional `{% if degraded %}` banner div showing "AI features unavailable — LLM unreachable" (non-blocking, styled distinctly)

**Checkpoint**: Foundation ready — each user story can now be implemented independently.

---

## Phase 3: User Story 1 — Run the Application Stack (P1) 🎯 MVP

**Goal**: Single-command startup, all services healthy, web UI reachable on LAN.

**Independent Test**: Run `docker compose up -d`, visit `http://localhost:8000/health`, confirm JSON response with `db: ok`; visit `http://localhost:8000/` and see the base layout — no other features needed.

### Implementation for User Story 1

- [x] T013 [P] [US1] Create `backend/src/services/health_service.py` — `HealthService` class with async methods `check_db(session)`, `check_llm(adapter: LLMAdapter)`, `check_mail(settings)`; each returns a `ServiceStatus` value (`ok`, `unreachable`, `unconfigured`) with a detail string; all checks run concurrently via `asyncio.gather` with a 3-second per-check timeout
- [x] T013a [P] [US1] Create `backend/src/services/llm_service.py` — define `LLMAdapter` abstract base class with async method `ping() → ServiceStatus`; implement `OllamaAdapter(LLMAdapter)` that sends a lightweight HTTP GET to `{settings.ollama_base_url}/api/tags` with a 3-second timeout, returning `ok` on success or `unreachable` on connection error; `health_service.py:check_llm()` MUST delegate to this adapter (not call Ollama directly) — required by Constitution IV (Modular Design)
- [x] T014 [P] [US1] Create `backend/src/api/health.py` — two routes: (1) `GET /health` returns JSON `{"status": "ok"|"degraded", "checks": {...}}` always HTTP 200 (for Docker health checks and API consumers); (2) `GET /health/fragment` returns an HTML fragment (`health_fragment.html`) for HTMX inline embedding; inject `degraded` boolean into all template responses via a FastAPI dependency
- [x] T015 [US1] Create `backend/src/templates/health.html` — extends `base.html`; renders each service check as a status row (service name + coloured badge); full-page health view accessible via the nav "Health" link
- [x] T015a [P] [US1] Create `backend/src/templates/health_fragment.html` — bare HTML fragment (no `base.html` extension); renders the same status rows as `health.html`; returned by `GET /health/fragment` and embedded in the dashboard via `hx-get="/health/fragment" hx-trigger="load"`
- [x] T016 [US1] Create `backend/src/templates/dashboard.html` — extends `base.html`; embeds health status via `hx-get="/health/fragment" hx-trigger="load" hx-target="#health-status"` into a `<div id="health-status">`; includes a prominent "Go to Config →" link; register `GET /` route in `main.py` rendering this template (not a redirect)

**Checkpoint**: User Story 1 fully functional — stack starts, health endpoint works, UI reachable.

---

## Phase 4: User Story 2 — Configure the Application (P2)

**Goal**: Config page where operator sets non-sensitive values, tests connections, saves settings that persist across restarts.

**Independent Test**: Visit `http://localhost:8000/config`, enter `llm_endpoint` + `event_date`, click Save, restart Docker, reload page — saved values reappear. Click "Test Connection" for each service — result appears within 5 seconds.

### Implementation for User Story 2

- [x] T017 [P] [US2] Create `backend/src/models/settings.py` — SQLAlchemy ORM model `Setting` mapping to `settings` table: `id`, `key`, `value`, `updated_at`
- [x] T018 [P] [US2] Create `backend/src/services/config_service.py` — `ConfigService` with methods: `get_all(session) → dict[str, str|None]`, `upsert(session, key, value)` using `INSERT … ON CONFLICT (key) DO UPDATE`; validates `key` is in the known-keys allowlist (reject unknowns with `ValueError`)
- [x] T019 [US2] Create `backend/src/api/config.py` — three routes: `GET /config` (render config page with current values), `POST /config` (save submitted form fields via `ConfigService.upsert`, redirect back), `POST /config/test/{service}` (call `HealthService.check_{service}`, return JSON `{service, status, detail}` within 5s timeout)
- [x] T020 [US2] Create `backend/src/templates/config.html` — extends `base.html`; form with labelled inputs for all known config keys; "Test Connection" button per service that uses `hx-post` + `hx-target` to show inline result without page reload; "Save" button for the full form
- [x] T021 [US2] Wire `config` router into `main.py`

**Checkpoint**: User Stories 1 and 2 both independently functional.

---

## Phase 5: User Story 3 — View Application Logs (P3)

**Goal**: Structured JSON logs emitted to stdout for all operations; secrets never appear; startup logs include version/config info.

**Independent Test**: Trigger a failed connection test (wrong LLM endpoint), inspect `docker logs rc_mail_assistant-backend-1` — confirm a JSON log entry with `timestamp`, `level`, `service`, `event` fields is present, and no secret values appear.

### Implementation for User Story 3

- [x] T022 [P] [US3] Update `backend/src/main.py` lifespan handler — after migrations complete, emit a structured startup log with: app version (read from `pyproject.toml`), `llm_endpoint` setting value, `event_date` setting value; confirm the secret-redaction processor in `logging_config.py` covers all bound context vars
- [x] T023 [P] [US3] Update `backend/src/services/health_service.py` — add structured log emission on each check result: `logger.info("health_check", service=name, status=result.status)`
- [x] T024 [US3] Update `backend/src/api/config.py` — add structured log entries for: config saved (log changed keys but not values of sensitive-looking keys), connection-test initiated, connection-test result
- [x] T025 [US3] Update `backend/src/database.py` — log each retry attempt with attempt number and delay: `logger.warning("db_connect_retry", attempt=n, delay_seconds=d)`; log final failure as `logger.error("db_connect_failed")`

**Checkpoint**: All three user stories independently functional.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Operational completeness across all stories.

- [x] T026 [P] Add `backend/src/templates/404.html` and `backend/src/templates/500.html` Jinja2 error page templates (both extend `base.html`); register FastAPI `exception_handlers` for 404 and 500 in `main.py`
- [x] T027 [P] Add Docker Compose resource limits in `docker-compose.yml`: `backend` 512 MB RAM, `postgres` 512 MB RAM, `ollama` (ai profile) 1 GB RAM — total ≤ 2 GB at idle per SC-006
- [x] T028 [P] Create `docker-compose.override.yml.example` showing how to override ports and `OLLAMA_BASE_URL` for local development
- [x] T029 Validate quickstart.md against the running stack: follow each step in `specs/001-core-infrastructure/quickstart.md`, confirm all commands and expected outputs are accurate, update file if discrepancies found
- [x] T030 [P] Add `backend/.dockerignore` and repo-root `.gitignore` entries: exclude `.env`, `__pycache__`, `*.pyc`, `.pytest_cache`, `migrations/versions/*.pyc`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately; T002–T005 run in parallel
- **Foundational (Phase 2)**: Requires Phase 1 complete — BLOCKS all user stories; T006–T012 sequential per listed order
- **User Story 1 (Phase 3)**: Requires Phase 2; T013+T013a in parallel, then T014, then T015, then T016
- **User Story 2 (Phase 4)**: Requires Phase 2; T017–T018 in parallel, then T019, then T020, then T021
- **User Story 3 (Phase 5)**: Requires Phase 2; T022–T023 in parallel, then T024, then T025
- **Polish (Phase 6)**: Requires all user stories complete; T026–T030 mostly parallel

### User Story Dependencies

- **US1**: Depends on Phase 2 only — no dependency on US2 or US3
- **US2**: Depends on Phase 2 only — no dependency on US1 or US3
- **US3**: Depends on Phase 2 only — extends US1+US2 files but does not block them

### Parallel Opportunities Within Stories

```bash
# Phase 1 (parallel group):
T002: pyproject.toml
T003: .env.example
T004: docker-compose.yml
T005: backend/Dockerfile

# Phase 3, US1 (parallel start):
T013: backend/src/services/health_service.py
T013a: backend/src/services/llm_service.py
T014: backend/src/api/health.py (after T013+T013a)

# Phase 4, US2 (parallel start):
T017: backend/src/models/settings.py
T018: backend/src/services/config_service.py

# Phase 5, US3 (parallel start):
T022: logging_config.py startup logs
T023: health_service.py log entries
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL — blocks all stories)
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: `docker compose up -d` → `GET /health` returns `db: ok` → base UI loads
5. Deploy and confirm on RPi5

### Incremental Delivery

1. Setup + Foundational → skeleton runs
2. US1 → health check + stack startup ✅ (MVP)
3. US2 → config page + connection tests ✅
4. US3 → structured logging ✅
5. Polish → resource limits, error pages, gitignore ✅

---

## Notes

- [P] tasks operate on different files — safe to parallelize
- [USn] label maps task to its user story for traceability
- No test tasks generated (not requested in spec)
- Each story is independently completable and testable before the next begins
- The `degraded` banner (base.html) is wired in Phase 2 so US2/US3 inherit it automatically
