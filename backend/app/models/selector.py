# Selector persistence model.
from __future__ import annotations

from enum import StrEnum
from datetime import UTC, datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Enum, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SelectorStatus(StrEnum):
    PENDING = "pending"
    VALIDATED = "validated"
    MANUAL = "manual"
    DETERMINISTIC = "deterministic"
    REJECTED = "rejected"


class Selector(Base):
    __tablename__ = "selectors"
    __table_args__ = (
        CheckConstraint(
            "css_selector IS NOT NULL OR xpath IS NOT NULL OR regex IS NOT NULL",
            name="ck_selectors_has_selector",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    domain: Mapped[str] = mapped_column(String(255), index=True)
    field_name: Mapped[str] = mapped_column(String(255), index=True)
    css_selector: Mapped[str | None] = mapped_column(Text, nullable=True)
    xpath: Mapped[str | None] = mapped_column(Text, nullable=True)
    regex: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[SelectorStatus] = mapped_column(
        Enum(SelectorStatus, native_enum=False, validate_strings=True, length=20),
        default=SelectorStatus.VALIDATED,
        server_default=SelectorStatus.PENDING.value,
    )
    sample_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(30), default="manual")
    source_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    last_validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
