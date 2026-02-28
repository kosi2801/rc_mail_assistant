FROM python:3.11-slim AS base

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Upgrade pip before installing dependencies
RUN pip install --no-cache-dir --upgrade pip

# --- Dependency layer (cached until pyproject.toml changes) ---
COPY pyproject.toml .
# Minimal stub so setuptools can resolve the package during install.
# The real src/ is copied below and overwrites this.
RUN mkdir -p src && touch src/__init__.py && \
    pip install --no-cache-dir ".[dev]"

# --- Application source (invalidates only the layers below) ---
COPY alembic.ini .
COPY src/ ./src/
COPY migrations/ ./migrations/

# Non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
