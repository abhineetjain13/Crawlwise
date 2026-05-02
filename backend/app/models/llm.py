# LLM configuration and usage models.
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class LLMCostLogOutcome(StrEnum):
    SUCCESS = "success"
    ERROR = "error"


class LLMConfig(Base):
    __tablename__ = "llm_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(30))
    model: Mapped[str] = mapped_column(String(255))
    api_key_encrypted: Mapped[str] = mapped_column(Text)
    task_type: Mapped[str] = mapped_column(String(60))
    per_domain_daily_budget_usd: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("0")
    )
    global_session_budget_usd: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("0")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class LLMCostLog(Base):
    __tablename__ = "llm_cost_log"
    __table_args__ = (
        CheckConstraint(
            f"outcome in ('{LLMCostLogOutcome.SUCCESS.value}', '{LLMCostLogOutcome.ERROR.value}')",
            name="ck_llm_cost_log_outcome",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("crawl_runs.id"), nullable=True, index=True
    )
    provider: Mapped[str] = mapped_column(String(30))
    model: Mapped[str] = mapped_column(String(255))
    task_type: Mapped[str] = mapped_column(String(60))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal("0"))
    domain: Mapped[str] = mapped_column(String(255), default="")
    outcome: Mapped[str] = mapped_column(
        String(20), default=LLMCostLogOutcome.SUCCESS.value
    )
    error_category: Mapped[str] = mapped_column(String(60), default="")
    error_message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
