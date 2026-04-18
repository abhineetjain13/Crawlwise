from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from app.services.config._module_exports import make_getattr, module_dir
from app.services.config._export_data import load_export_data

_EXPORTS_PATH = Path(__file__).with_name("field_mappings.exports.json")


@lru_cache(maxsize=1)
def _static_exports() -> dict[str, Any]:
    return load_export_data(str(_EXPORTS_PATH))


__all__ = sorted(_static_exports().keys())

__getattr__ = make_getattr(
    module_globals=globals(),
    value_exports=_static_exports,
    cache=True,
)


def __dir__() -> list[str]:
    return module_dir(globals(), __all__)
