from __future__ import annotations

from app.services.pipeline.pipeline_config import PipelineConfig
from app.services.pipeline.types import (
    PipelineContext,
    URLProcessingConfig,
    URLProcessingResult,
)
from app.services.pipeline.verdict import (
    VERDICT_ERROR,
    VERDICT_LISTING_FAILED,
    VERDICT_PARTIAL,
    VERDICT_SUCCESS,
    compute_verdict,
)

VERDICT_FAILED = VERDICT_ERROR
VERDICT_LISTING_DETECTION_FAILED = VERDICT_LISTING_FAILED

__all__ = [
    "PipelineConfig",
    "PipelineContext",
    "URLProcessingConfig",
    "URLProcessingResult",
    "VERDICT_SUCCESS",
    "VERDICT_PARTIAL",
    "VERDICT_FAILED",
    "VERDICT_LISTING_DETECTION_FAILED",
    "compute_verdict",
]
