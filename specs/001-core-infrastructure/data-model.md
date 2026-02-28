# Data Model: Core Infrastructure

**Feature**: 001-core-infrastructure
**Date**: 2026-02-21

## Entities

### Settings

Stores all non-sensitive application configuration as key-value pairs. Sensitive values
(credentials, tokens) are stored only in `.env` and are never written to this table.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | `INTEGER` | PK, auto-increment | |
| `key` | `VARCHAR(255)` | UNIQUE, NOT NULL | Canonical setting name (e.g., `llm_endpoint`) |
| `value` | `TEXT` | NOT NULL | Serialised as string; parse at read site |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | NOT NULL, default `now()` | Auto-updated on upsert |

**Uniqueness rule**: `key` is unique — upsert pattern (`INSERT … ON CONFLICT (key) DO UPDATE`).

**Known keys** (initial set):

| Key | Description | Example Value |
|---|---|---|
| `llm_endpoint` | Base URL of the Ollama (or llama.cpp) API | `http://ollama:11434` |
| `llm_model` | Model name to request | `llama3.2` |
| `event_date` | Next repair café event date | `2026-03-15` |
| `event_location` | Venue name and address | `Wijkcentrum De Brug, Amsterdam` |
| `event_offerings` | Comma-separated repair categories | `electronics,clothing,bikes` |

**Keys never stored here** (remain in `.env` only):
- `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`
- `POSTGRES_PASSWORD`, `SECRET_KEY`

---

### ServiceHealth *(runtime, not persisted)*

A transient value object returned by `health_service.py`. Never written to the database.

| Field | Type | Values |
|---|---|---|
| `service` | `str` | `db`, `llm`, `mail` |
| `status` | `enum` | `ok`, `degraded`, `unreachable`, `unconfigured` |
| `detail` | `str \| None` | Human-readable reason when not `ok` |

---

## Migrations

Managed by **Alembic**. Migration files live in `backend/migrations/versions/`.

- Initial migration creates the `settings` table.
- Alembic runs automatically on startup (before the app begins serving requests) via
  the FastAPI lifespan handler.
- Migrations are idempotent — safe to re-run on restart.

---

## Relationships

The infrastructure feature introduces only the `settings` table. All future features
(email, threads, drafts) add their own tables via new Alembic migrations. There are no
foreign-key relationships from `settings` to other tables.
