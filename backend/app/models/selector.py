# Selector persistence model.
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Selector(Base):
    __tablename__ = "selectors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    domain: Mapped[str] = mapped_column(String(255), index=True)
    field_name: Mapped[str] = mapped_column(String(255), index=True)
    selector: Mapped[str] = mapped_column(Text)
    selector_type: Mapped[str] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(30), default="manual")
    last_validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
