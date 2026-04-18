from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, MutableMapping
from typing import Any


def make_getattr(
    *,
    module_globals: MutableMapping[str, Any] | None = None,
    attr_exports: Mapping[str, str] | None = None,
    value_exports: Mapping[str, Any] | Callable[[], Mapping[str, Any]] | None = None,
    dynamic_exports: Mapping[str, Any] | None = None,
    settings_obj: object | None = None,
    allow_private: bool = True,
    cache: bool = False,
) -> Callable[[str], Any]:
    def __getattr__(name: str) -> Any:
        if not allow_private and name.startswith("_"):
            raise AttributeError(name)

        if dynamic_exports is not None and name in dynamic_exports:
            resolver = dynamic_exports[name]
            value = resolver() if callable(resolver) else resolver
        else:
            exports = value_exports() if callable(value_exports) else value_exports
            if exports is not None and name in exports:
                value = exports[name]
            else:
                setting_name = attr_exports.get(name) if attr_exports is not None else None
                if setting_name is None or settings_obj is None:
                    raise AttributeError(name)
                value = getattr(settings_obj, setting_name)

        if cache and module_globals is not None:
            module_globals[name] = value
        return value

    return __getattr__


def module_dir(module_globals: Mapping[str, Any], public_names: Iterable[str]) -> list[str]:
    return sorted({*module_globals.keys(), *public_names})
