from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.config._export_data import load_export_data

_EXPORTS_PATH = Path(__file__).with_name("selectors.exports.json")
_STATIC_EXPORTS = load_export_data(str(_EXPORTS_PATH))

for _name, _value in _STATIC_EXPORTS.items():
    globals()[_name] = _value

__all__ = sorted(_STATIC_EXPORTS.keys())
