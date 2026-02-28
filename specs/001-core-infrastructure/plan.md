# Implementation Plan: Core Infrastructure

**Branch**: `001-core-infrastructure` | **Date**: 2026-02-21 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/001-core-infrastructure/spec.md`

## Summary

Stand up the full application stack as a Docker Compose project runnable on a Raspberry Pi 5.
Delivers: single-command startup, health-check endpoint, configuration persistence (hybrid
`.env` + database), LLM-degraded-state UI, structured logging, and resilient DB retry on boot.
Frontend: HTMX + Jinja2 (no build step). Backend: Python / FastAPI. Database: PostgreSQL.

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**: FastAPI, SQLAlchemy 2, Alembic, tenacity, structlog, HTMX + Jinja2
**Storage**: PostgreSQL (Dockerized); key-value `settings` table for non-sensitive config
**Testing**: pytest + httpx (async FastAPI test client)
**Target Platform**: Linux / Docker on Raspberry Pi 5 (8 GB RAM), ARM64
**Project Type**: Web service (backend API + server-side rendered frontend)
**Performance Goals**: Health endpoint ≤ 2s; config connection-test ≤ 5s; idle RAM ≤ 2 GB total
**Constraints**: No public internet exposure; no JS build toolchain; ARM64-compatible images
**Scale/Scope**: Single operator; ≤ 10 concurrent browser tabs; no horizontal scaling

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| # | Principle | Status | Notes |
|---|-----------|--------|-------|
| I | **Privacy-First** | ✅ PASS | Credentials stay in `.env` only; DB stores no secrets; no public exposure |
| II | **Manual Synchronization** | ✅ PASS | This feature has no sync operations; N/A applies cleanly |
| III | **Minimal Footprint** | ✅ PASS | HTMX (no build), structlog (~100 KB), tenacity (small); ARM64 Docker images |
| IV | **Modular Design** | ✅ PASS | DB, LLM, config each behind service interfaces; health checks query adapters |
| V | **Resilience & Idempotency** | ✅ PASS | DB retry on startup (tenacity); health endpoint; clean restart via Alembic migrations |

**Gate result**: ✅ PASS — all principles satisfied. Proceeding to Phase 1 design.

## Project Structure

### Documentation (this feature)

```text
specs/001-core-infrastructure/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   └── health-and-config.md
└── tasks.md             # Phase 2 output (speckit.tasks)
```

### Source Code (repository root)

```text
backend/
├── src/
│   ├── main.py                  # FastAPI app factory, lifespan startup/shutdown
│   ├── config.py                # Settings loader (pydantic-settings, reads .env)
│   ├── database.py              # SQLAlchemy engine + session factory + startup retry
│   ├── logging_config.py        # structlog JSON configuration
│   ├── models/
│   │   └── settings.py          # ORM model: Settings key-value table
│   ├── services/
│   │   ├── config_service.py    # CRUD for non-sensitive config (DB-backed)
│   │   ├── health_service.py    # Per-service liveness checks (DB, LLM, mail)
│   │   └── llm_service.py       # LLM adapter interface + Ollama implementation
│   ├── api/
│   │   ├── health.py            # GET /health endpoint
│   │   └── config.py            # GET/POST /config + POST /config/test/{service}
│   └── templates/               # Jinja2 HTML templates
│       ├── base.html            # Layout with degraded-state banner slot
│       ├── config.html          # Configuration page
│       └── health.html          # Health status page
├── migrations/                  # Alembic migrations
├── tests/
│   ├── unit/
│   └── integration/
├── Dockerfile
└── .env.example                 # Documents all required/optional env vars

frontend/                        # Static assets (CSS, HTMX is CDN)
docker-compose.yml               # Orchestrates backend + postgres + (optional) ollama
docker-compose.override.yml.example
.env.example                     # Root-level copy / symlink
```

**Structure Decision**: Web application layout with `backend/` containing the FastAPI service.
Frontend is server-side rendered (HTMX + Jinja2) — no separate frontend container or build step.
PostgreSQL runs as a sidecar container. Ollama is an optional sidecar; absent = degraded mode.

## Complexity Tracking

> No constitution violations — section not required.

