from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crawl import CrawlRun
from app.services.acquisition.acquirer import AcquisitionResult
from app.services.acquisition_plan import AcquisitionPlan
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.pipeline.types import URLProcessingConfig


@dataclass(slots=True)
class URLProcessingContext:
    session: AsyncSession
    run: CrawlRun
    url: str
    config: URLProcessingConfig
    url_timeout_seconds: float
    started_at_monotonic: float
    requested_fields: list[str] = field(default_factory=list)
    surface: str = ""


@dataclass(slots=True)
class FetchedURLStage:
    context: URLProcessingContext
    acquisition_result: AcquisitionResult
    url_metrics: dict[str, object]


@dataclass(slots=True)
class ExtractedURLStage:
    fetched: FetchedURLStage
    records: list[dict[str, object]]


def resolve_run_param(
    plan_value: object | None,
    config_value: object | None,
    default_value: int,
    *,
    min_value: int = 1,
) -> int:
    for candidate in (plan_value, config_value):
        if candidate is None:
            continue
        try:
            resolved = int(
                float(candidate)
                if isinstance(candidate, (int, float))
                else float(str(candidate))
            )
        except (TypeError, ValueError):
            continue
        if resolved >= int(min_value):
            return resolved
    return int(default_value)


def resolved_url_processing_config(
    config: URLProcessingConfig | None,
    *,
    surface: str,
    proxy_list: list[str] | None,
    traversal_mode: str | None,
    max_pages: int,
    max_scrolls: int,
    max_records: int,
    sleep_ms: int,
    update_run_state: bool,
    persist_logs: bool,
) -> URLProcessingConfig:
    if config is not None:
        plan = config.resolved_acquisition_plan(surface=surface)
        resolved_proxy_list = list(
            plan.proxy_list or config.proxy_list or proxy_list or []
        )
        resolved_traversal_mode = (
            plan.traversal_mode
            if plan.traversal_mode is not None
            else config.traversal_mode
            if config.traversal_mode is not None
            else traversal_mode
        )
        safety_iteration_cap = int(
            crawler_runtime_settings.traversal_max_iterations_cap
        )
        resolved_max_pages = min(
            resolve_run_param(plan.max_pages, config.max_pages, max_pages),
            safety_iteration_cap,
        )
        resolved_max_scrolls = min(
            resolve_run_param(plan.max_scrolls, config.max_scrolls, max_scrolls),
            safety_iteration_cap,
        )
        resolved_max_records = resolve_run_param(
            plan.max_records,
            config.max_records,
            max_records,
        )
        resolved_sleep_ms = resolve_run_param(
            plan.sleep_ms,
            config.sleep_ms,
            sleep_ms,
            min_value=0,
        )
        return URLProcessingConfig.from_acquisition_plan(
            AcquisitionPlan(
                surface=surface,
                proxy_list=tuple(resolved_proxy_list),
                traversal_mode=resolved_traversal_mode,
                max_pages=resolved_max_pages,
                max_scrolls=resolved_max_scrolls,
                max_records=resolved_max_records,
                sleep_ms=resolved_sleep_ms,
            ),
            update_run_state=config.update_run_state,
            persist_logs=config.persist_logs,
            prefetch_only=config.prefetch_only,
            record_writer=config.record_writer,
        )
    return URLProcessingConfig.from_acquisition_plan(
        AcquisitionPlan(
            surface=surface,
            proxy_list=tuple(list(proxy_list or [])),
            traversal_mode=traversal_mode,
            max_pages=max_pages,
            max_scrolls=max_scrolls,
            max_records=max_records,
            sleep_ms=sleep_ms,
        ),
        update_run_state=update_run_state,
        persist_logs=persist_logs,
    )
