# Quickstart: Core Infrastructure

**Feature**: 001-core-infrastructure

## Prerequisites

- Raspberry Pi 5 (8 GB RAM) running Raspberry Pi OS (64-bit) or Ubuntu Server 24.04 (ARM64)
- Docker Engine 24+ and Docker Compose v2 installed
- Git installed
- A Gmail account with a Google Cloud project (for OAuth credentials — set up separately)

## 1. Clone and configure

```bash
git clone <repo-url> rc_mail_assistant
cd rc_mail_assistant
cp .env.example .env
```

Edit `.env` and fill in the required values:

```dotenv
# Required — application will refuse to start without these
POSTGRES_PASSWORD=change_me_strong_password
SECRET_KEY=change_me_32_char_random_string

# Optional — omit to start in degraded mode (AI features disabled)
GMAIL_CLIENT_ID=
GMAIL_CLIENT_SECRET=
GMAIL_REFRESH_TOKEN=

# Optional — defaults shown; override if your Ollama runs elsewhere
OLLAMA_BASE_URL=http://ollama:11434

# Optional — startup retry tuning (defaults: 5 attempts, 2s delay)
DB_CONNECT_ATTEMPTS=5
DB_CONNECT_DELAY_SECONDS=2
```

## 2. Start the stack

```bash
# Core stack only (no AI / LLM):
docker compose up -d

# Core stack + Ollama (AI features enabled):
docker compose --profile ai up -d
```

## 3. Verify

Open in a browser on your local network:

```
http://<raspberry-pi-ip>:8000/health
```

Expected response when healthy:

```json
{ "status": "ok", "checks": { "db": "ok", "llm": "ok", "mail": "unconfigured" } }
```

When running without Ollama (`degraded` is normal and expected):

```json
{ "status": "degraded", "checks": { "db": "ok", "llm": "unreachable", "mail": "unconfigured" } }
```

## 4. Open the web UI

```
http://<raspberry-pi-ip>:8000/
```

Navigate to the **Config** page to set:
- LLM endpoint and model name
- Next event date, location, and repair offerings

Use **Test Connection** next to each service to verify connectivity.

## 5. Troubleshooting

**Container exits immediately on startup**:

```bash
docker compose logs backend
```

Common causes: missing required env vars in `.env`, or database refused connection
after all retry attempts. The log message names the specific cause.

**Banner shows "AI features unavailable"**: Ollama container is not running. Start it with
`docker compose --profile ai up -d ollama`, or omit if AI features are not needed yet.

**Config page shows all nulls**: First run — no settings saved yet. Fill in the fields and
click Save.

## 6. Stopping and restarting

```bash
docker compose down        # stop containers, preserve data volumes
docker compose down -v     # stop + delete all data (destructive!)
docker compose up -d       # restart — resumes cleanly, no data loss
```
