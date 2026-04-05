# Site memory persistence model.
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SiteMemory(Base):
    __tablename__ = "site_memory"

    domain: Mapped[str] = mapped_column(String(255), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    last_crawl_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
