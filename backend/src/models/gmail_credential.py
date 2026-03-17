"""ORM model for the Gmail OAuth credential singleton (data-model.md)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Integer, String, Text, TIMESTAMP, func
from sqlalchemy.orm import Mapped, mapped_column

from src.base_model import Base


class GmailCredential(Base):
    """Singleton record (id=1) for the stored Gmail OAuth refresh token.

    At most one row exists at any time; the fixed primary key (id=1) enforces
    this at the database level. All writes go through GmailCredentialService.upsert(),
    which always sets id=1.
    """

    __tablename__ = "gmail_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # always 1
    # Fernet ciphertext — TEXT (not VARCHAR) to accommodate variable-length output
    encrypted_refresh_token: Mapped[str] = mapped_column(Text, nullable=False)
    # Email address from Google getProfile — displayed (masked) in the UI only
    account_email: Mapped[str] = mapped_column(String(255), nullable=False)
    connected_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
