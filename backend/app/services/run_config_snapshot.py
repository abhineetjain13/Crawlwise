from __future__ import annotations

from typing import Any

from app.services.config.runtime_settings import crawler_runtime_settings


def snapshot_extraction_runtime_settings() -> dict[str, Any]:
    return {
        "selector_self_heal": {
            "enabled": bool(crawler_runtime_settings.selector_self_heal_enabled),
            "min_confidence": float(
                crawler_runtime_settings.selector_self_heal_min_confidence
            ),
        }
    }
