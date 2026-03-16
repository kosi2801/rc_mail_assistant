# rc_mail_assistant Development Guidelines

Auto-generated from all feature plans. Last updated: 2026-02-21

## Active Technologies
- Python 3.11 (established by feature 001) + FastAPI, SQLAlchemy 2.x async, Alembic, HTMX + Jinja2 (002-gmail-mail-sync)
- PostgreSQL (Dockerised, via asyncpg); three new tables: (002-gmail-mail-sync)

- Python 3.11+ + FastAPI, SQLAlchemy 2, Alembic, tenacity, structlog, HTMX + Jinja2 (001-core-infrastructure)

## Project Structure

```text
src/
tests/
```

## Commands

cd src [ONLY COMMANDS FOR ACTIVE TECHNOLOGIES][ONLY COMMANDS FOR ACTIVE TECHNOLOGIES] pytest [ONLY COMMANDS FOR ACTIVE TECHNOLOGIES][ONLY COMMANDS FOR ACTIVE TECHNOLOGIES] ruff check .

## Code Style

Python 3.11+: Follow standard conventions

## Recent Changes
- 002-gmail-mail-sync: Added Python 3.11 (established by feature 001) + FastAPI, SQLAlchemy 2.x async, Alembic, HTMX + Jinja2

- 001-core-infrastructure: Added Python 3.11+ + FastAPI, SQLAlchemy 2, Alembic, tenacity, structlog, HTMX + Jinja2

<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->
