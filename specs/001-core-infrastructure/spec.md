# Feature Specification: Core Infrastructure

**Feature Branch**: `001-core-infrastructure`
**Created**: 2026-02-21
**Status**: Draft
**Input**: User description: "Basic infrastructure"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Run the Application Stack (Priority: P1)

A system operator sets up the Repair Cafe Mail Assistant for the first time. They start all
required services from a single command, confirm each service is healthy, and see the web
interface become accessible on the local network — without any cloud account or special
configuration beyond editing a single `.env` file.

**Why this priority**: Nothing else in the product is possible until the stack starts cleanly.
This is the deployment primitive every other story depends on.

**Independent Test**: Can be fully tested by running the start command on a fresh Raspberry Pi 5
with Docker installed, verifying the health-check endpoint returns success, and opening the web
UI — without any application features being implemented yet.

**Acceptance Scenarios**:

1. **Given** Docker and Docker Compose are installed and a valid `.env` file is present,
   **When** the operator runs the start command,
   **Then** all services start, pass their health checks, and the web UI is reachable on
   the local network within 2 minutes.

2. **Given** the application stack is running,
   **When** the operator visits the health-check endpoint,
   **Then** they receive a success response listing each service's status (database, LLM
   runtime, mail connector readiness).

3. **Given** the stack is running and the operator stops it,
   **When** they restart it,
   **Then** the system resumes cleanly with no data loss and no duplicate records.

---

### User Story 2 - Configure the Application (Priority: P2)

A system operator needs to connect the application to their Gmail account, point it at their
preferred LLM model, and set next-event metadata (date, location, offerings). They do this
through a dedicated configuration page in the web UI, can test each connection, and can save
settings that persist across Docker restarts.

**Why this priority**: Without valid configuration the application cannot perform any mail or
AI operations. The config page is the second thing an operator touches after the stack starts.

**Independent Test**: Can be fully tested by visiting the config page, entering Gmail OAuth
credentials and LLM endpoint settings, pressing "Test Connection" for each, and confirming
saved values survive a Docker restart — independently of any email sync or AI features.

**Acceptance Scenarios**:

1. **Given** the operator opens the config page,
   **When** they enter connection details and press "Test Connection",
   **Then** they see a clear success or failure message for each service (database, Gmail,
   LLM) within 5 seconds.

2. **Given** the operator saves configuration,
   **When** Docker restarts the container,
   **Then** all saved configuration values are present and unchanged on next startup.

3. **Given** invalid credentials are entered,
   **When** the operator tests the connection,
   **Then** the UI shows a descriptive error explaining which field is wrong, without
   exposing raw secrets in the message.

---

### User Story 3 - View Application Logs (Priority: P3)

A system operator encounters unexpected behaviour and wants to understand what the system is
doing. They open the logs view in Portainer or inspect structured log output, and can filter
by service and severity without needing SSH access or log-file management.

**Why this priority**: Logs are operational tooling, not a user-facing feature, and can be
added after the stack and config are stable.

**Independent Test**: Can be fully tested by triggering a known event (e.g., a failed
connection test), verifying the corresponding structured log entry appears in Docker's log
output with the expected fields — independently of mail or AI features.

**Acceptance Scenarios**:

1. **Given** the system is running and an operation completes or fails,
   **When** the operator checks container logs (e.g., via Portainer or `docker logs`),
   **Then** a structured log entry is present with at minimum: timestamp, severity, service
   name, and a human-readable message.

2. **Given** a startup sequence completes,
   **When** the operator reviews the logs,
   **Then** each service logs its successful initialisation with version/config info and
   no secrets are printed.

---

### Edge Cases

- What happens when the `.env` file is missing or contains invalid values at startup? → Container exits immediately with a descriptive log message; operator sees it as stopped in Portainer.
- How does the system behave when the database container is slow to become ready (race condition)? → Retries up to N times (default 5, 2s delay, configurable via `.env`), then exits with error.
- What happens when the LLM runtime is unreachable at startup (optional dependency)? → Starts in degraded state; status banner shown; AI actions disabled.
- How are port conflicts handled when the default ports are already in use on the host? → Out of scope for application-level handling. The operator must ensure host ports 8000 (backend) and 5432 (postgres) are free before running `docker compose up`. Port mapping overrides are documented in `docker-compose.override.yml.example`.
- What happens when disk space is critically low on the Raspberry Pi? → Out of scope for this feature. Docker surfaces disk pressure via container exit codes and Portainer alerts. The operator monitors disk usage via the Portainer dashboard or `df -h`.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST be startable via a single Docker Compose command with no manual
  per-service setup beyond providing a `.env` file.
- **FR-002**: The system MUST expose a health-check endpoint that reports the live status of
  each internal service (database, LLM runtime, mail connector).
- **FR-002a**: The mail connector check MUST verify that the required Gmail credential env
  vars (`GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`) are present and
  that the refresh token is structurally non-empty. No outbound Gmail API call is made
  during this check; full mail connectivity is validated by the mail connector feature.
- **FR-003**: The system MUST start cleanly after an unclean shutdown (e.g., power loss) with
  no manual intervention required to recover data integrity.
- **FR-004**: The system MUST provide a configuration page where the operator can set Gmail
  OAuth credentials, LLM endpoint/model, and event metadata (date, location, offerings).
- **FR-005**: The configuration page MUST include a "Test Connection" action for each external
  dependency, returning a success or failure result within 5 seconds.
- **FR-006**: All configuration values MUST persist across container restarts without requiring
  re-entry.
- **FR-007**: Credentials and secrets MUST NOT appear in log output. 
- **FR-008**: The system MUST emit structured logs (at minimum: timestamp, severity, service
  name, message) to stdout, consumable by Docker's logging driver.
- **FR-009**: On startup, if required configuration is absent (missing env vars) or the
  database is unreachable, the application container MUST exit immediately with a
  descriptive error message written to stdout. The container MUST NOT attempt to serve
  the web UI in this state. The operator diagnoses the cause via Portainer logs.
- **FR-010**: The entire stack MUST run on a Raspberry Pi 5 (8 GB RAM) within the Docker
  resource budget defined in `docker-compose.yml`.
- **FR-011**: When the LLM runtime is unreachable, the system MUST display a persistent status
  banner on all pages and disable AI-dependent actions with a descriptive tooltip. All
  non-AI features MUST remain fully functional in this degraded state.
- **FR-012**: On startup, the application MUST retry the database connection up to a
  configurable number of times (default: 5) with a configurable delay between attempts
  (default: 2 seconds) before treating the database as unreachable and exiting per FR-009.
  Retry count and delay MUST be configurable via `.env`.
- **FR-013**: The root page (`GET /`) MUST render a minimal dashboard displaying the current
  health status summary (all service checks, inline — not a redirect) and a prominent
  "Go to Config" navigation link. It MUST NOT redirect to `/health` or `/config`.
- **FR-014**: The application MUST accept a `SECRET_KEY` environment variable (required,
  no default). This key is reserved for future session-signing and CSRF protection
  middleware. At the infrastructure stage it MUST be validated as present and non-empty
  at startup (triggering FR-009 exit if absent), but no active middleware uses it yet.

### Key Entities

- **Configuration**: Stores non-sensitive settings in the database (LLM endpoint URL, event
  metadata: date, location, offerings, UI preferences). Sensitive credentials (Gmail OAuth
  tokens, API keys) are stored exclusively in the `.env` file managed by the operator —
  never written to the database. Persists across restarts via the database for non-secret
  values; `.env` is the operator's responsibility to back up.
- **ServiceHealth**: A runtime representation of the health state (healthy / degraded /
  unreachable) for each registered service dependency.

## Clarifications

### Session 2026-02-21 (continued)

- Q: What does "test connection" for the mail service mean at the infrastructure level? → A: Check that Gmail credential env vars are present and refresh token is structurally non-empty. No outbound API call — live Gmail connectivity is the mail connector feature's responsibility.
- Q: What is the root landing page (`GET /`)? → A: A dedicated minimal dashboard page showing the health status summary (inline, no redirect) and a prominent "Go to Config" link. Not a redirect to /health.

- Q: Where is configuration stored — `.env` only, database only, or hybrid? → A: Hybrid. Sensitive credentials (Gmail OAuth tokens, API keys) live exclusively in `.env`. Non-sensitive settings (LLM endpoint, event metadata, UI preferences) are stored in the database and persist across restarts.
- Q: What does the user see when the LLM runtime is unavailable? → A: A persistent status banner on all pages with AI-dependent actions disabled (tooltip explains reason). Non-AI workflows remain fully functional.
- Q: Is any authentication required beyond LAN access? → A: No. LAN network isolation is the sole access boundary. No login or password is required for any page, including the config page.
- Q: When required config is missing or the DB is unreachable at startup, what happens? → A: Container exits immediately with a descriptive log message. No web UI is served. Operator diagnoses via Portainer logs.
- Q: How is the database startup race condition (DB slow to be ready) handled? → A: App retries up to N times (default 5, 2-second intervals, both configurable via `.env`) before exiting with an error.

## Assumptions

- The operator has Docker and Docker Compose installed on the Raspberry Pi 5 before setup.
- The operator manages Gmail OAuth credentials outside the app (creates them in Google Cloud
  Console); the app only stores and uses the resulting token.
- LLM runtime (Ollama) is expected to be running as a separate container in the same Compose
  network; if absent at startup the app starts in a degraded state. When degraded, a
  persistent status banner is shown on all pages and AI-dependent actions are disabled with
  a tooltip explaining the LLM is unreachable. Non-AI workflows remain fully functional.
- "Local network access" means the Raspberry Pi is accessible via its LAN IP; no public
  internet exposure is in scope. No authentication is required — LAN isolation is the
  sole access boundary for all pages, including the configuration page.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A new operator can bring the full stack up from zero on a Raspberry Pi 5 in
  under 10 minutes following the quickstart documentation.
- **SC-002**: The health-check endpoint responds within 2 seconds under normal operating
  conditions.
- **SC-003**: The system survives 30 consecutive unclean shutdowns (simulated power loss) with
  no data corruption or manual recovery required.
- **SC-004**: All connection-test actions on the config page return a result (success or
  descriptive failure) within 5 seconds.
- **SC-005**: No secrets or credentials appear in structured log output under any operating
  condition (verified by log scan).
- **SC-006**: Total memory usage of all containers combined remains under 2 GB at idle on the
  Raspberry Pi 5 (leaving headroom for LLM runtime).

