<!--
  Sync Impact Report
  ==================
  Version change: 1.1.0 → 1.2.0
  Modified principles: I — Privacy-First (added Exception I.1 for Fernet-encrypted OAuth refresh-token storage in DB)
  Added sections: Exception I.1 carve-out under Principle I
  Removed sections: N/A
  Templates:
    ✅ .specify/memory/constitution.md — this file
    ✅ .specify/templates/plan-template.md — Constitution Check gates reference principles by name; no update needed
    ✅ .specify/templates/spec-template.md — no constitution-specific references; no change required
    ✅ .specify/templates/tasks-template.md — no constitution-specific references; no change required
    ✅ .specify/templates/agent-file-template.md — no constitution-specific references; no change required
  Deferred TODOs: none
-->

# Repair Cafe Mail Assistant Constitution

## Core Principles

### I. Privacy-First (NON-NEGOTIABLE)

Only plain-text email content MUST be stored locally. No attachments MUST be persisted beyond a
metadata placeholder (message-id, filename, mime-type).
HTML email bodies MUST be stripped to plain text on ingest; no raw HTML is stored in the database.
Mail data MUST NOT be exposed outside the local network or committed to any public repository.
Sensitive credentials (Gmail OAuth tokens, API keys) MUST be stored in environment variables or a
local secrets file that is excluded from version control,
**except as provided by the following approved exception**:

> **Exception I.1 (Fernet-Encrypted OAuth Refresh Token in Database)**: Storing a Gmail OAuth
> refresh token in PostgreSQL is permitted when ALL of the following conditions hold:
> (a) the token is Fernet-encrypted (AES-128-CBC + HMAC-SHA256) using a key derived from
> `SECRET_KEY` via `base64.urlsafe_b64encode(hashlib.sha256(SECRET_KEY.encode()).digest())`
> before every database write — the plaintext token MUST NEVER be written to the database,
> (b) the plaintext token MUST NEVER appear in logs, API responses, or any browser-visible
> field (the Fernet ciphertext MUST NOT be returned to the client either),
> (c) this exception is scoped exclusively to OAuth refresh tokens obtained via the application's
> own in-app Authorization Code flow — it does NOT extend to API keys, passwords, or other
> credential types,
> (d) the `SECRET_KEY` (the encryption key source) continues to be stored only in `.env` and
> MUST NOT be committed to version control; rotating `SECRET_KEY` intentionally invalidates the
> stored token (recovery via re-authorization, no migration utility),
> (e) the database itself MUST NOT be exposed outside the local Docker network.
> First approved for feature `003-gmail-oauth-token-db`.

**Rationale**: Volunteer correspondence contains personal visitor information. Protecting this data
is a non-negotiable trust obligation to repair café visitors.

### II. Manual Synchronization

Inbound Gmail sync and outbound draft creation MUST each be triggered by an explicit user action.
No automated background polling, scheduled sending, or silent data transmission is permitted,
**except as provided by the following approved exception**:

> **Exception II.1 (Operator-Enabled Background Polling)**: An in-process, interval-based mail
> sync scheduler (APScheduler `AsyncIOScheduler`) is permitted when ALL of the following
> conditions hold: (a) the feature's implementation plan documents a Constitution Check against
> this principle, (b) the scheduler is **disabled by default** (`mail_poll_interval_minutes = 0`)
> and requires explicit operator opt-in via the config UI, (c) the scheduler runs in-process
> (no external broker), and (d) every scheduled sync produces a `MailSyncRun` record with
> `triggered_by = "scheduler"` so operator visibility is maintained. First approved for
> feature `002-gmail-mail-sync` (clarification session 2026-02-28).

Every sync operation MUST be idempotent so that re-triggering produces no duplicates or data loss.

**Rationale**: Volunteers must remain in full control of what data enters and leaves the system.
Optional operator-enabled polling with full auditability (MailSyncRun records) upholds this
principle while reducing manual burden for active deployments.

### III. Minimal Footprint

The entire application stack (API, database, frontend) MUST run inside Docker/Portainer on a
Raspberry Pi 5 (8 GB RAM) without external cloud dependencies for core functionality.
Local ML models (Ollama, llama.cpp) MUST function fully offline after initial model download.
Dependency count MUST be minimized; prefer standard-library or well-maintained single-purpose
packages over large framework bundles. Container images MUST be kept lean.

**Rationale**: The target hardware is a low-power SBC. Excessive resource use directly degrades
volunteer usability.

### IV. Modular Design

The LLM provider, vector search engine, mail connector, and relational database MUST each be
isolated behind a clearly defined interface (adapter/service layer).
No direct cross-boundary imports are permitted between these components; they MUST communicate
through defined service interfaces.
Each module MUST be independently testable using stubs or fakes for its dependencies.
The LLM backend MUST be switchable at configuration time (Ollama ↔ llama.cpp) without code changes.

**Rationale**: Hardware and software constraints may force provider switches. Modularity prevents
cascading rewrites across the codebase.

### V. Resilience & Idempotency

All database write operations MUST be idempotent (upsert-safe or pre-checked for existence).
The system MUST resume cleanly after an abrupt Docker shutdown mid-operation with no corrupted state.
Long-running operations MUST checkpoint progress so a restart does not repeat already-completed work.
Health-check and connection-test endpoints MUST be exposed for Portainer / Docker health monitoring.

**Rationale**: Nightly Docker restarts are expected operational behavior. Data integrity MUST be
guaranteed across those boundaries.

## Technology Stack & Deployment

- **Language**: Python 3.11+
- **Web framework**: FastAPI
- **Database**: PostgreSQL (Dockerized); pgvector extension for vector search (swappable via adapter)
- **LLM runtime**: Ollama (default); llama.cpp as configured fallback; interface MUST be swappable
- **Mail connector**: Gmail API (OAuth 2.0); adapter interface allows alternative mail backends
- **Frontend**: Lightweight SPA; MUST avoid heavy build toolchains to keep the footprint small
- **Containerization**: Docker Compose managed via Portainer on Raspberry Pi 5 (8 GB)
- **Secrets**: `.env` file excluded from version control; MUST NOT be committed under any circumstance
- **Logging**: Structured JSON logs to stdout; consumed by the Docker logging driver

No cloud-hosted services are permitted for core data paths. All processing MUST remain on the
local node.

## Development Workflow

All features MUST follow the Speckit pipeline in strict order:

1. **Specify** (`speckit.specify`) — produce `specs/###/spec.md`
2. **Clarify** (`speckit.clarify`) — resolve ambiguity before planning
3. **Plan** (`speckit.plan`) — produce `plan.md`, `research.md`, `data-model.md`, `contracts/`
4. **Constitution Check** (GATE) — see plan-template.md; MUST pass before Phase 0 research and
   again after Phase 1 design
5. **Tasks** (`speckit.tasks`) — produce `specs/###/tasks.md`
6. **Implement** (`speckit.implement`) — execute tasks
7. **Analyze** (`speckit.analyze`) — cross-artifact consistency check

A feature MUST NOT enter implementation until its Constitution Check passes.

## Governance

This constitution supersedes all other design guidance and README statements where they conflict.
Amendments require: (a) an updated `constitution.md` with an incremented version number,
(b) a propagation check across all dependent templates, and (c) a commit referencing the version bump.

**Versioning policy**:
- MAJOR: backward-incompatible removal or redefinition of an existing principle
- MINOR: new principle or section added; materially expanded guidance
- PATCH: clarifications, wording refinements, non-semantic fixes

All feature plans MUST include a Constitution Check section with explicit pass/fail verdicts against
each principle before implementation begins.

**Version**: 1.2.0 | **Ratified**: 2026-02-21 | **Last Amended**: 2026-06-26

**Changelog**:
- `1.2.0` (2026-06-26): Added Exception I.1 to Principle I — permits Fernet-encrypted OAuth
  refresh token storage in PostgreSQL when key is derived from `SECRET_KEY`, plaintext is never
  logged or returned, scope is limited to in-app OAuth refresh tokens, and the database remains
  on the local Docker network. First approved for feature `003-gmail-oauth-token-db`.
  Propagation check: plan-template.md Constitution Check gate references concrete principles
  by name — no change needed. spec-template.md, tasks-template.md, agent-file-template.md —
  no constitution-specific references; no change required.
- `1.1.0` (2026-02-28): Added Exception II.1 to Principle II — permits operator-enabled
  in-process background polling (disabled by default) for feature `002-gmail-mail-sync`.
  Propagation check: plan-template.md Constitution Check gate references concrete principles
  by name — no change needed. spec-template.md, tasks-template.md, agent-file-template.md —
  no constitution-specific references; no change required.
