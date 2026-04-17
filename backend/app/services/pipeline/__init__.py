from __future__ import annotations

from importlib import import_module

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

_EXPORTS = {
    "PipelineConfig": ("app.services.pipeline.pipeline_config", "PipelineConfig"),
    "PipelineContext": ("app.services.pipeline.types", "PipelineContext"),
    "URLProcessingConfig": ("app.services.pipeline.types", "URLProcessingConfig"),
    "URLProcessingResult": ("app.services.pipeline.types", "URLProcessingResult"),
    "VERDICT_SUCCESS": ("app.services.publish.verdict", "VERDICT_SUCCESS"),
    "VERDICT_PARTIAL": ("app.services.publish.verdict", "VERDICT_PARTIAL"),
    "VERDICT_FAILED": ("app.services.publish.verdict", "VERDICT_ERROR"),
    "VERDICT_LISTING_DETECTION_FAILED": (
        "app.services.publish.verdict",
        "VERDICT_LISTING_FAILED",
    ),
    "compute_verdict": ("app.services.publish.verdict", "compute_verdict"),
}


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(name)
    module_name, attr_name = _EXPORTS[name]
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value
