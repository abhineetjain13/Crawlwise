from __future__ import annotations

from app.models.crawl import BatchRunProgressState, _merge_run_acquisition_metrics
from app.services.run_summary import merge_run_summary_patch

# Backwards-compatible re-exports for callers and tests that still import the
# progress model and summary merge helpers from the service layer.
_merge_run_summary_patch = merge_run_summary_patch

__all__ = [
    "BatchRunProgressState",
    "_merge_run_acquisition_metrics",
    "_merge_run_summary_patch",
]
