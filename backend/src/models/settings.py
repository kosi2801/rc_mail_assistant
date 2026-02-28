"""ORM model for the key-value settings table (data-model.md)."""
from datetime import datetime

from sqlalchemy import Integer, String, Text, TIMESTAMP, func
from sqlalchemy.orm import Mapped, mapped_column

from src.base_model import Base

KNOWN_KEYS = frozenset({
    "llm_endpoint",
    "llm_model",
    "event_date",
    "event_location",
    "event_offerings",
})


class Setting(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
