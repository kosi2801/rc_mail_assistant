"""Root conftest.py — sets required environment variables before any src imports."""
import os

# Set required env vars before any src.config import happens
os.environ.setdefault("SECRET_KEY", "test_secret_key_32_chars_minimum_ok")
os.environ.setdefault("POSTGRES_PASSWORD", "test_password")
os.environ.setdefault("POSTGRES_USER", "rcmail")
os.environ.setdefault("POSTGRES_DB", "rcmail")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
