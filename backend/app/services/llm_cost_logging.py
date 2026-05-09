from __future__ import annotations

import logging

from app.models.crawl import CrawlRun
from app.models.llm import LLMCostLog, LLMCostLogOutcome
from app.services.llm_errors import LLMErrorCategory
from app.services.llm_provider_client import estimate_cost_usd
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def record_llm_cost_log(
    session: AsyncSession,
    *,
    run_id: int | None,
    task_type: str,
    domain: str,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    error_message: str = "",
    error_category: LLMErrorCategory = LLMErrorCategory.NONE,
) -> None:
    try:
        persisted_run_id = run_id
        if run_id is not None:
            existing_run = await session.get(CrawlRun, run_id)
            if existing_run is None:
                persisted_run_id = None
        session.add(
            LLMCostLog(
                run_id=persisted_run_id,
                provider=provider,
                model=model,
                task_type=task_type,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=estimate_cost_usd(
                    provider, model, input_tokens, output_tokens
                ),
                domain=domain,
                outcome=(
                    LLMCostLogOutcome.ERROR.value
                    if error_message
                    else LLMCostLogOutcome.SUCCESS.value
                ),
                error_category=(
                    "" if error_category == LLMErrorCategory.NONE else str(error_category)
                ),
                error_message=str(error_message or ""),
            )
        )
        await session.flush()
    except SQLAlchemyError:
        await session.rollback()
        logger.warning("Failed to persist LLM cost log", exc_info=True)
