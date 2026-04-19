from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator

from app.services.acquisition_plan import AcquisitionPlan
from app.services.pipeline.pipeline_config import PipelineDefaults


@dataclass(slots=True)
class URLProcessingResult:
    records: list[dict] = field(default_factory=list)
    verdict: str = ""
    url_metrics: dict[str, Any] = field(default_factory=dict)

    def __iter__(self) -> Iterator:
        return iter((self.records, self.verdict, self.url_metrics))

    def __len__(self) -> int:
        return 3


@dataclass(slots=True)
class URLProcessingConfig:
    acquisition_plan: AcquisitionPlan | None = None
    proxy_list: list[str] = field(default_factory=list)
    traversal_mode: str | None = None
    max_pages: int = PipelineDefaults.MAX_PAGES
    max_scrolls: int = PipelineDefaults.MAX_SCROLLS
    max_records: int = PipelineDefaults.MAX_RECORDS
    sleep_ms: int = PipelineDefaults.SLEEP_MS
    update_run_state: bool = True
    persist_logs: bool = True
    prefetch_only: bool = False
    record_writer: object | None = None

    def __post_init__(self) -> None:
        if self.acquisition_plan is None:
            self.acquisition_plan = AcquisitionPlan(
                surface="",
                proxy_list=tuple(self.proxy_list),
                traversal_mode=self.traversal_mode,
                max_pages=self.max_pages,
                max_scrolls=self.max_scrolls,
                max_records=self.max_records,
                sleep_ms=self.sleep_ms,
            )
        self._sync_from_plan(self.acquisition_plan)

    @classmethod
    def from_acquisition_plan(
        cls,
        plan: AcquisitionPlan,
        *,
        update_run_state: bool = True,
        persist_logs: bool = True,
        prefetch_only: bool = False,
        record_writer: object | None = None,
    ) -> "URLProcessingConfig":
        return cls(
            acquisition_plan=plan,
            update_run_state=update_run_state,
            persist_logs=persist_logs,
            prefetch_only=prefetch_only,
            record_writer=record_writer,
        )

    def resolved_acquisition_plan(self, *, surface: str) -> AcquisitionPlan:
        if self.acquisition_plan is None:
            self.acquisition_plan = AcquisitionPlan(surface=str(surface or "").strip())
        if self.acquisition_plan.surface == str(surface or "").strip():
            return self.acquisition_plan
        return self.acquisition_plan.with_updates(surface=str(surface or "").strip())

    def _sync_from_plan(self, plan: AcquisitionPlan) -> None:
        self.proxy_list = list(plan.proxy_list)
        self.traversal_mode = plan.traversal_mode
        self.max_pages = plan.max_pages
        self.max_scrolls = plan.max_scrolls
        self.max_records = plan.max_records
        self.sleep_ms = plan.sleep_ms
