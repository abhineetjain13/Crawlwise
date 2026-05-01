from __future__ import annotations

from pathlib import Path
from typing import Any, Final

from app.services.config._export_data import load_export_data
from app.services.config.runtime_settings import crawler_runtime_settings


FieldPathMap = dict[str, tuple[str, ...]]
PayloadMappingSpec = dict[
    str,
    str | tuple[str, ...] | tuple[tuple[str, ...], ...] | FieldPathMap,
]


def _tuple_of_strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        return ()
    return tuple(str(item) for item in value if str(item).strip())


def _tuple_of_tuple_of_strings(value: object) -> tuple[tuple[str, ...], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    rows: list[tuple[str, ...]] = []
    for item in value:
        normalized = _tuple_of_strings(item)
        if normalized:
            rows.append(normalized)
    return tuple(rows)


def _field_path_map(value: object) -> FieldPathMap:
    if not isinstance(value, dict):
        return {}
    normalized: FieldPathMap = {}
    for key, raw_paths in value.items():
        paths = _tuple_of_strings(raw_paths)
        if paths:
            normalized[str(key)] = paths
    return normalized


def _payload_mapping_specs(
    value: object,
) -> tuple[tuple[str, tuple[PayloadMappingSpec, ...]], ...]:
    if not isinstance(value, dict):
        return ()
    normalized_specs: dict[str, tuple[PayloadMappingSpec, ...]] = {}
    for surface, raw_specs in value.items():
        if not isinstance(raw_specs, list):
            continue
        specs: list[PayloadMappingSpec] = []
        for raw_spec in raw_specs:
            if not isinstance(raw_spec, dict):
                continue
            spec: PayloadMappingSpec = {}
            for key, raw_value in raw_spec.items():
                normalized_key = str(key)
                if normalized_key == "field_paths":
                    spec[normalized_key] = _field_path_map(raw_value)
                elif normalized_key == "required_path_groups":
                    spec[normalized_key] = _tuple_of_tuple_of_strings(raw_value)
                elif normalized_key in {"endpoint_families", "endpoint_path_tokens"}:
                    spec[normalized_key] = _tuple_of_strings(raw_value)
                else:
                    spec[normalized_key] = str(raw_value) if isinstance(raw_value, str) else raw_value
            specs.append(spec)
        normalized_specs[str(surface)] = tuple(specs)
    return tuple(normalized_specs.items())


_EXPORTS = load_export_data(str(Path(__file__).with_name("network_payload_specs.exports.json")))
_SURFACE_SPECS = dict(_payload_mapping_specs(_EXPORTS.get("NETWORK_PAYLOAD_SPECS")))

NETWORK_PAYLOAD_SIGNATURE_MIN_MATCH: Final[int] = (
    crawler_runtime_settings.network_payload_signature_min_match
)
NETWORK_PAYLOAD_PRODUCT_SIGNATURE: Final[frozenset[str]] = frozenset(
    _tuple_of_strings(_EXPORTS.get("NETWORK_PAYLOAD_PRODUCT_SIGNATURE"))
)
NETWORK_PAYLOAD_JOB_SIGNATURE: Final[frozenset[str]] = frozenset(
    _tuple_of_strings(_EXPORTS.get("NETWORK_PAYLOAD_JOB_SIGNATURE"))
)
NETWORK_PAYLOAD_LIST_COLLECTION_KEYS: Final[frozenset[str]] = frozenset(
    _tuple_of_strings(_EXPORTS.get("NETWORK_PAYLOAD_LIST_COLLECTION_KEYS"))
)
NETWORK_PAYLOAD_DETAIL_CONTAINER_KEYS: Final[frozenset[str]] = frozenset(
    _tuple_of_strings(_EXPORTS.get("NETWORK_PAYLOAD_DETAIL_CONTAINER_KEYS"))
)
GHOST_ROUTE_COMPATIBLE_SURFACES: Final[frozenset[str]] = frozenset(
    _tuple_of_strings(_EXPORTS.get("GHOST_ROUTE_COMPATIBLE_SURFACES"))
)
DETAIL_URL_IGNORE_TOKENS: Final[frozenset[str]] = frozenset(
    _tuple_of_strings(_EXPORTS.get("DETAIL_URL_IGNORE_TOKENS"))
)
NETWORK_PAYLOAD_SPECS: Final[dict[str, tuple[PayloadMappingSpec, ...]]] = _SURFACE_SPECS


def endpoint_type_path_tokens() -> dict[str, dict[str, tuple[str, ...]]]:
    tokens_by_surface: dict[str, dict[str, tuple[str, ...]]] = {}
    for surface, specs in NETWORK_PAYLOAD_SPECS.items():
        surface_tokens: dict[str, tuple[str, ...]] = {}
        for spec in specs:
            endpoint_type = str(spec.get("endpoint_type") or "").strip().lower()
            raw_tokens = spec.get("endpoint_path_tokens")
            if not endpoint_type or not isinstance(raw_tokens, tuple) or not raw_tokens:
                continue
            existing_tokens = surface_tokens.get(endpoint_type, ())
            surface_tokens[endpoint_type] = tuple(
                dict.fromkeys([*existing_tokens, *raw_tokens])
            )
        if surface_tokens:
            tokens_by_surface[surface] = surface_tokens
    return tokens_by_surface


__all__ = [
    "DETAIL_URL_IGNORE_TOKENS",
    "FieldPathMap",
    "GHOST_ROUTE_COMPATIBLE_SURFACES",
    "NETWORK_PAYLOAD_DETAIL_CONTAINER_KEYS",
    "NETWORK_PAYLOAD_JOB_SIGNATURE",
    "NETWORK_PAYLOAD_LIST_COLLECTION_KEYS",
    "NETWORK_PAYLOAD_PRODUCT_SIGNATURE",
    "NETWORK_PAYLOAD_SIGNATURE_MIN_MATCH",
    "NETWORK_PAYLOAD_SPECS",
    "PayloadMappingSpec",
    "endpoint_type_path_tokens",
]
