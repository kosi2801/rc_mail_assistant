# Research: Core Infrastructure

**Feature**: 001-core-infrastructure
**Date**: 2026-02-21

## 1. Frontend Framework

**Decision**: HTMX + Jinja2 (server-side rendering, no build step)

**Rationale**: Zero build pipeline means no Node.js, no npm, no webpack on the RPi5. HTMX
weighs ~14 KB (CDN). Jinja2 is already a FastAPI dependency. Full interactivity for a
single-operator tool is achievable with `hx-post`, `hx-get`, and response fragments.

**Alternatives considered**:
- Vue 3 CDN: ~34 KB, still no build, but adds client-side routing complexity not needed here.
- React: requires Node build infrastructure — violates Minimal Footprint principle.

---

## 2. Configuration Persistence (Non-Sensitive Values)

**Decision**: `settings` table with rows `(id, key, value, updated_at)` — key-value design

**Rationale**: Schema-agnostic, easy to extend (add a new setting = no migration change to
table structure). Simple queries. Allows runtime update via config page with a single
`INSERT … ON CONFLICT DO UPDATE`.

**Alternatives considered**:
- Single typed-columns row: requires a migration for every new setting field.
- Single JSON blob column: opaque, harder to query or patch individual values.

---

## 3. Database Startup Retry

**Decision**: `tenacity` library — `@retry(wait=wait_exponential(min=2, max=10), stop=stop_after_attempt(N))`

**Rationale**: Minimal dependency (~50 KB), readable declarative retry policy, handles
exponential backoff out of the box. N and initial delay configurable via env vars, passed
at runtime. Raises `tenacity.RetryError` on exhaustion — caught in `main.py` lifespan to
log a clear message and `sys.exit(1)`.

**Alternatives considered**:
- Manual `for` loop: verbose, no backoff, easy to get wrong.
- SQLAlchemy pool pre-ping: only catches dead connections after pool is established, not
  initial unavailability.

---

## 4. Structured Logging

**Decision**: `structlog` with `JSONRenderer` processor, writing to stdout

**Rationale**: Lightweight (~100 KB), integrates with Python stdlib `logging` so third-party
libraries (SQLAlchemy, FastAPI) also emit structured entries. Docker log driver consumes
stdout natively. Fields: `timestamp`, `level`, `service`, `event` (message) + arbitrary
context bound per module.

**Secret redaction**: A custom processor strips any key whose name contains `token`,
`secret`, `password`, `key`, `credential` before rendering — satisfying FR-007.

**Alternatives considered**:
- `loguru`: heavier, structured output requires plugin, adds runtime overhead.
- `python-json-logger`: more boilerplate to configure; less composable processors.

---

## 5. Health Check Endpoint

**Decision**: `GET /health` returns `200 OK` with JSON body regardless of degraded state:

```json
{
  "status": "ok" | "degraded",
  "checks": {
    "db":  "ok" | "unreachable",
    "llm": "ok" | "unreachable",
    "mail": "ok" | "unconfigured" | "unreachable"
  }
}
```

**Rationale**: Always returns 200 so Docker/Portainer health checks don't restart the
container on LLM unavailability (which is intentionally degraded, not fatal). The `status`
field is `degraded` if any non-fatal check fails. Granular `checks` object lets the UI
banner know exactly which services are affected.

**Alternatives considered**:
- Return 503 on any failure: causes Portainer to restart container unnecessarily.
- Separate endpoints per service: more complex, harder to cache or render in one UI widget.

---

## 6. Docker Compose Service Orchestration

**Decision**: `depends_on` with `condition: service_healthy` on the `postgres` service,
combined with app-level tenacity retry (FR-012).

**Rationale**: Compose waits for postgres to pass its `HEALTHCHECK` before starting the
app container. The app-level retry then handles any transient window after Compose's
health check passes but before the first query succeeds. Double safety net with minimal
overhead.

**Postgres healthcheck**: `pg_isready -U $POSTGRES_USER`

**Ollama**: Listed as `profiles: [ai]` — only started when the operator explicitly enables
the AI profile. Absence = degraded mode. No `depends_on` on Ollama; app checks it via
health service at runtime.

**Alternatives considered**:
- `depends_on: service_started` (not `service_healthy`): too early, DB not accepting connections.
- App-level retry only (no Compose health check): longer startup time, noisier logs.
