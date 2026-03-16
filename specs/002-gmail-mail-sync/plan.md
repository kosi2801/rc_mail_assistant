# Implementation Plan: Gmail Mail Sync

**Branch**: `002-gmail-mail-sync` | **Date**: 2026-02-28 | **Spec**: `specs/002-gmail-mail-sync/spec.md`  
**Input**: Feature specification from `/specs/002-gmail-mail-sync/spec.md` (two clarify sessions completed)

## Summary

Implement a Gmail mail connector that fetches visit-request emails into the application
database and exposes them via a mail list page. The system connects to Gmail using OAuth 2.0
credentials stored in `.env`, applies a configurable search filter, stores each qualifying
email as an immutable plain-text record (body capped at 100 KB), and deduplicates via the
Gmail message ID. A `MailSyncRun` table records every sync attempt for auditability. Manual
sync is the primary interaction (P1); browsing stored emails is the secondary flow (P2);
optional background polling via APScheduler's `AsyncIOScheduler` is P3 (disabled by default).

The connector is encapsulated behind a `MailAdapter` interface (analogous to `LLMAdapter`
from feature 001). `GmailAdapter` is the concrete implementation using
`google-api-python-client` v2 (Gmail REST API v1). Sync orchestration depends only on the
abstract interface — never on `GmailAdapter` directly.

## Technical Context

**Language/Version**: Python 3.11 (established by feature 001)  
**Primary Dependencies**: FastAPI, SQLAlchemy 2.x async, Alembic, HTMX + Jinja2
(all from feature 001) + `google-api-python-client>=2.0`, `google-auth>=2.0`,
`google-auth-httplib2>=0.1`, `html2text>=2024.2`, `apscheduler>=3.10,<4.0`  
**Storage**: PostgreSQL (Dockerised, via asyncpg); three new tables:
`incoming_emails`, `mail_sync_cursor`, `mail_sync_runs`  
**Testing**: pytest + pytest-asyncio (established by feature 001); stubs for `MailAdapter`
in unit tests; real DB via Docker for integration tests  
**Target Platform**: Linux (Docker on Raspberry Pi 5, 8 GB RAM)  
**Project Type**: Web service (FastAPI backend, HTMX + Jinja2 frontend — server-side rendered)  
**Performance Goals**: Manual sync of ≤ 200 emails completes within 60 s on RPi5 (SC-001);
sync result displayed within 10 s of completion (FR-007)  
**Constraints**: No external message broker; no cloud dependencies; all data stays on local
network; Gmail API is blocking I/O — every call must be wrapped in `run_in_executor`  
**Scale/Scope**: ~10–200 emails per Repair Café event cycle; single operator; no pagination
required in this feature

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| # | Principle | Status | Notes |
|---|-----------|--------|-------|
| I | **Privacy-First** — only plain-text stored locally; no raw HTML, no credentials committed, no data outside local network | ✅ PASS | HTML bodies stripped to plain text via `html2text` before storage; 100 KB cap enforced; Gmail credentials remain in `.env` only; all data stays on the local RPi5 node |
| II | **Manual Synchronization** — all inbound/outbound actions are user-triggered; idempotent on retry | ❌ FAIL | FR-014 (P3) introduces optional background polling via APScheduler. **Justified exception — see Complexity Tracking.** Manual sync (P1) remains the primary trigger; polling is disabled by default; all existing manual actions are unaffected. |
| III | **Minimal Footprint** — runs on RPi5 / Docker; no new heavy dependencies; models work offline | ✅ PASS | New deps are all lightweight single-purpose packages: `google-api-python-client` (~500 KB), `google-auth` (~200 KB), `google-auth-httplib2` (~20 KB), `html2text` (~50 KB), `apscheduler` (~200 KB). No NLP, ML, or build toolchain required. |
| IV | **Modular Design** — LLM, mail, DB, vector-search each behind a swappable interface; no cross-boundary direct imports | ✅ PASS | `MailAdapter` ABC in `src/services/mail_service.py`; `GmailAdapter` concrete impl in `src/adapters/gmail_adapter.py`. Sync orchestration imports only `MailAdapter`. Future IMAP/Exchange adapters can be substituted without touching orchestration or API layers. |
| V | **Resilience & Idempotency** — all writes upsert-safe; clean resume after Docker restart; health-check endpoint present | ✅ PASS | `gmail_message_id` UNIQUE constraint + `INSERT … ON CONFLICT DO NOTHING` (FR-004); `MailSyncRun` row created before any API call (survives crash); `MailSyncCursor` updated only on success; health endpoint unchanged; APScheduler `coalesce=True` prevents catch-up bursts on restart. |

**Gate result**: FAIL on Principle II — documented exception in Complexity Tracking. Proceeding
with the one justified violation. All other principles pass. Design is sound for Phase 1.

**Post-Phase 1 re-check**: The design produced in Phase 1 (data-model.md, contracts/mail.md)
does not introduce any new violations. Background polling is disabled by default; the
`mail_poll_interval_minutes` setting defaults to `"0"`. Constitution Check re-affirmed ✅ (except
the pre-approved Principle II exception).

## Project Structure

### Documentation (this feature)

```text
specs/002-gmail-mail-sync/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   └── mail.md          # Phase 1 output — mail + config-extension contracts
└── tasks.md             # Phase 2 output (speckit.tasks — NOT created here)
```

### Source Code (repository root)

```text
backend/
├── src/
│   ├── adapters/                          # NEW — concrete adapter implementations
│   │   ├── __init__.py
│   │   └── gmail_adapter.py               # GmailAdapter implements MailAdapter
│   ├── api/
│   │   ├── config.py                      # EXTEND — add mail_filter, mail_poll_interval_minutes,
│   │   │                                  #   mail_sync_max_retries to KNOWN_KEYS; add scheduler
│   │   │                                  #   reschedule on poll-interval save
│   │   ├── health.py                      # UNCHANGED
│   │   └── mail.py                        # NEW — GET /mail, GET /mail/{id}, POST /mail/sync,
│   │                                      #   DELETE /mail/{id}, POST /mail/cursor,
│   │                                      #   GET /mail/sync/status
│   ├── models/
│   │   ├── settings.py                    # EXTEND — add new keys to KNOWN_KEYS frozenset
│   │   └── mail.py                        # NEW — IncomingEmail, MailSyncCursor, MailSyncRun
│   ├── services/
│   │   ├── config_service.py              # UNCHANGED
│   │   ├── health_service.py              # UNCHANGED
│   │   ├── llm_service.py                 # UNCHANGED
│   │   ├── mail_service.py                # NEW — MailAdapter ABC, EmailMessage, ConnectorStatus,
│   │   │                                  #   run_sync() orchestration, asyncio.Lock guard
│   │   └── scheduler_service.py           # NEW — AsyncIOScheduler setup, start/stop helpers,
│   │                                      #   update_poll_interval() for runtime reconfiguration
│   ├── templates/
│   │   ├── base.html                      # EXTEND — add Mail nav-link
│   │   ├── mail_list.html                 # NEW — mail list page (FR-011, FR-013, FR-022)
│   │   ├── mail_detail.html               # NEW — single email detail page (FR-012, FR-020)
│   │   ├── mail_sync_result.html          # NEW — HTMX fragment for POST /mail/sync response
│   │   └── mail_sync_status.html          # NEW — HTMX fragment for GET /mail/sync/status
│   ├── base_model.py                      # UNCHANGED
│   ├── config.py                          # UNCHANGED (GMAIL_* vars already present)
│   ├── database.py                        # UNCHANGED
│   ├── logging_config.py                  # UNCHANGED
│   └── main.py                            # EXTEND — register mail router; start/stop scheduler
│                                          #   in lifespan; wire GmailAdapter via factory
├── migrations/
│   └── versions/
│       └── 0002_create_mail_tables.py     # NEW — incoming_emails, mail_sync_cursor,
│                                          #   mail_sync_runs tables
├── tests/
│   ├── unit/
│   │   ├── test_gmail_adapter.py          # NEW — MIME extraction, body truncation, dedup logic
│   │   ├── test_mail_service.py           # NEW — sync orchestration with MailAdapter stub
│   │   └── test_scheduler_service.py      # NEW — interval reconfiguration logic
│   └── integration/
│       └── test_mail_api.py               # NEW — full round-trip via TestClient + DB
├── alembic.ini                            # UNCHANGED
├── Dockerfile                             # UNCHANGED
└── pyproject.toml                         # EXTEND — add new dependencies
```

**Structure Decision**: Web application (backend-only, HTMX+Jinja2 server-side rendering).
No frontend directory changes — the application has no separate frontend SPA (confirmed by
feature 001 research: HTMX + Jinja2 templates live in `backend/src/templates/`). A new
`src/adapters/` package is introduced to keep the concrete `GmailAdapter` implementation
separate from the `MailAdapter` interface and sync orchestration (Constitution IV).

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|--------------------------------------|
| **Principle II** — background polling (FR-014, P3) contradicts "no automated background polling" | Repair Café coordinators explicitly requested automatic inbox updates without pressing Sync Mail before every event-prep session. The feature owner accepted this during the 2026-02-28 clarification session. Polling is disabled by default (`mail_poll_interval_minutes = 0`); requires an explicit operator configuration action to enable. | Manual-only operation remains fully supported (P1). Background polling could be deferred to a later feature, but: (a) the clarification session made it a confirmed requirement; (b) APScheduler is already the lightest viable in-process solution — no external broker or daemon is added; (c) deferral would require re-opening the spec and clarification cycle for a decision already made. The P3 designation signals it is not a blocker for P1/P2 delivery. |
