"""ORM models for the Gmail mail sync feature (data-model.md)."""
from datetime import datetime

from sqlalchemy import Integer, String, Text, TIMESTAMP, func, Index
from sqlalchemy.orm import Mapped, mapped_column

from src.base_model import Base


class IncomingEmail(Base):
    """Stores fetched Gmail messages as plain-text records."""

    __tablename__ = "incoming_emails"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    gmail_message_id: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True
    )
    gmail_thread_id: Mapped[str] = mapped_column(String(255), nullable=False)
    sender_name: Mapped[str] = mapped_column(String(255), nullable=False)
    sender_email: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    synced_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )


class MailSyncCursor(Base):
    """Singleton (id=1) tracking the last successful sync timestamp."""

    __tablename__ = "mail_sync_cursor"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    overlap_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class MailSyncRun(Base):
    """Audit log of each sync execution."""

    __tablename__ = "mail_sync_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    outcome: Mapped[str | None] = mapped_column(
        String(20), nullable=True  # "success" | "partial" | "failed" | None = in-progress
    )
    new_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    triggered_by: Mapped[str] = mapped_column(
        String(20), nullable=False, default="manual"
    )
