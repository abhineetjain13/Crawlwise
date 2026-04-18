from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class AcquisitionPlan:
    surface: str
    adapter_recovery_enabled: bool = False
