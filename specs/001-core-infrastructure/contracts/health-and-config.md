# Contract: Health Endpoint

**Feature**: 001-core-infrastructure
**Date**: 2026-02-21

## `GET /health`

Returns the live health status as **JSON**. Always returns HTTP 200. Used by Docker/Portainer
health checks and API consumers.

### Request

No parameters, no authentication required.

### Response

**HTTP 200 OK**

```json
{
  "status": "ok" | "degraded",
  "checks": {
    "db":   "ok" | "unreachable",
    "llm":  "ok" | "unreachable" | "unconfigured",
    "mail": "ok" | "unreachable" | "unconfigured"
  }
}
```

---

## `GET /health/fragment`

Returns the health status as an **HTML fragment** for HTMX inline embedding. Used by the
dashboard (`GET /`) via `hx-get="/health/fragment" hx-trigger="load"`. Not a full page —
no `<html>`, `<head>`, or `<body>` wrapper.

### Response

**HTTP 200 OK** (`Content-Type: text/html`)

Renders the same service status rows as the full health page, as an embeddable `<div>`.
Status values and logic are identical to `GET /health`.

---

**`status` logic**:
- `"ok"` — all checks are `"ok"`.
- `"degraded"` — one or more checks are not `"ok"`. The application is partially functional.

**`checks` values**:

| Value | Meaning |
|---|---|
| `ok` | Service responded successfully within the timeout |
| `unreachable` | Service is configured but did not respond within 3 seconds |
| `unconfigured` | Required configuration (endpoint, credentials) is not yet set |

**Mail check behaviour**: The `mail` check verifies that `GMAIL_CLIENT_ID`,
`GMAIL_CLIENT_SECRET`, and `GMAIL_REFRESH_TOKEN` env vars are present and non-empty.
No outbound Gmail API call is made. Returns `unconfigured` if any credential is absent,
`ok` if all are present.

**Timeout**: Each individual check has a 3-second hard timeout. Total endpoint response time
MUST be ≤ 2 seconds under normal conditions (checks run concurrently via `asyncio.gather`).

### Example Responses

**All healthy**:
```json
{ "status": "ok", "checks": { "db": "ok", "llm": "ok", "mail": "ok" } }
```

**LLM container not running (expected degraded)**:
```json
{ "status": "degraded", "checks": { "db": "ok", "llm": "unreachable", "mail": "unconfigured" } }
```

**DB unreachable (critical — container should have exited on startup; this state indicates mid-run failure)**:
```json
{ "status": "degraded", "checks": { "db": "unreachable", "llm": "ok", "mail": "ok" } }
```

---

## `GET /config`

Returns the current non-sensitive configuration values from the database.

### Response

**HTTP 200 OK**

```json
{
  "llm_endpoint":    "http://ollama:11434",
  "llm_model":       "llama3.2",
  "event_date":      "2026-03-15",
  "event_location":  "Wijkcentrum De Brug, Amsterdam",
  "event_offerings": "electronics,clothing,bikes"
}
```

Missing keys are returned as `null`.

---

## `POST /config`

Saves one or more non-sensitive configuration values.

### Request body

```json
{
  "llm_endpoint":   "http://ollama:11434",
  "event_date":     "2026-03-15"
}
```

Any subset of known keys is accepted. Unknown keys are rejected with 422.

### Response

**HTTP 200 OK** — returns the full updated config object (same shape as `GET /config`).

---

## `POST /config/test/{service}`

Tests the live connection to a named service using currently saved configuration (or
`.env` credentials for sensitive services).

**Path parameter**: `service` ∈ `{ "db", "llm", "mail" }`

### Response

**HTTP 200 OK** (`Content-Type: text/html`) — always HTTP 200; result is an HTML fragment
for HTMX inline embedding. Success/failure is conveyed in the fragment content.

The fragment renders a status badge and detail message. The `status` concept maps to one of
the following values:

| Status | Meaning |
|--------|---------|
| `ok` | Service responded successfully |
| `unreachable` | Service is configured but did not respond within the timeout |
| `unconfigured` | Required configuration (endpoint, credentials) is not set |
| `model_not_found` | Ollama is reachable but the configured model is not installed; includes the `ollama pull <model>` command in the detail |

**Timeout**: 5 seconds per test (matches SC-004).
