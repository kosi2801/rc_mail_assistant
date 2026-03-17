# rc_mail_assistant Development Guidelines

Auto-generated from all feature plans. Last updated: 2026-03-16

## Active Technologies
- Python 3.11 (established by feature 001) + FastAPI, SQLAlchemy 2.x async, Alembic, HTMX + Jinja2 (002-gmail-mail-sync)
- PostgreSQL (Dockerised, via asyncpg); three new tables: (002-gmail-mail-sync)
- Python 3.11+ + FastAPI 0.111+, SQLAlchemy 2.0+ (async), asyncpg 0.29+, (003-gmail-oauth-token-db)
- PostgreSQL via asyncpg; new `gmail_credentials` table — singleton row, (003-gmail-oauth-token-db)

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
- 003-gmail-oauth-token-db: Added Python 3.11+ + FastAPI 0.111+, SQLAlchemy 2.0+ (async), asyncpg 0.29+,
- 002-gmail-mail-sync: Added Python 3.11 (established by feature 001) + FastAPI, SQLAlchemy 2.x async, Alembic, HTMX + Jinja2

- 001-core-infrastructure: Added Python 3.11+ + FastAPI, SQLAlchemy 2, Alembic, tenacity, structlog, HTMX + Jinja2

<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->
