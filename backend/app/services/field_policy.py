from __future__ import annotations

import re
from collections.abc import Iterable

from app.services.config.field_mappings import (
    CANONICAL_SCHEMAS,
    FIELD_ALIASES,
    INTERNAL_ONLY_FIELDS,
    SURFACE_BROWSER_RETRY_TARGETS,
    SURFACE_FIELD_REPAIR_TARGETS,
)

_NON_FIELD_RE = re.compile(r"[^a-z0-9.]+")
_REQUESTED_FIELD_PREFIXES = ("product_", "item_", "job_")
_ALL_CANONICAL_FIELDS = frozenset(
    field_name
    for fields in CANONICAL_SCHEMAS.values()
    for field_name in fields
)
HTML_SECTION_FIELDS = frozenset(
    {"responsibilities", "qualifications", "benefits", "skills"}
)
_FIELD_ALIASES = FIELD_ALIASES


def canonical_fields_for_surface(surface: str) -> list[str]:
    normalized = str(surface or "").strip().lower()
    return list(CANONICAL_SCHEMAS.get(normalized, _ALL_CANONICAL_FIELDS))


def excluded_fields_for_surface(surface: str) -> frozenset[str]:
    allowed = frozenset(canonical_fields_for_surface(surface))
    return (_ALL_CANONICAL_FIELDS - allowed) | INTERNAL_ONLY_FIELDS


def field_allowed_for_surface(surface: str, field_name: str) -> bool:
    normalized_field = normalize_field_key(field_name)
    if not normalized_field:
        return False
    return normalized_field in frozenset(canonical_fields_for_surface(surface))


def get_surface_field_aliases(surface: str) -> dict[str, list[str]]:
    normalized = str(surface or "").strip().lower()
    allowed = frozenset(canonical_fields_for_surface(normalized))
    aliases = {
        canonical: list(values)
        for canonical, values in _FIELD_ALIASES.items()
        if canonical in allowed
    }
    if normalized in {"automobile_listing", "automobile_detail"}:
        automobile_aliases = {
            canonical: list(values) for canonical, values in aliases.items()
        }
        make_aliases = automobile_aliases.setdefault("make", [])
        if "manufacturer" not in make_aliases:
            make_aliases.append("manufacturer")
        brand_aliases = automobile_aliases.get("brand")
        if brand_aliases is not None:
            automobile_aliases["brand"] = [
                alias for alias in brand_aliases if alias != "manufacturer"
            ]
        return automobile_aliases
    if normalized.startswith("ecommerce_"):
        ecommerce_aliases = {
            canonical: list(values) for canonical, values in aliases.items()
        }
        for field_name, field_aliases in {
            "capacity": ("capacity_l", "capacity_liter", "capacity_litre", "capacity_liters", "capacity_litres"),
            "energy_rating": ("energy_rating", "energy_star_rating", "star_rating"),
        }.items():
            bucket = ecommerce_aliases.setdefault(field_name, [])
            for alias in field_aliases:
                if alias not in bucket:
                    bucket.append(alias)
        category_aliases = ecommerce_aliases.get("category")
        if category_aliases is not None:
            ecommerce_aliases["category"] = [
                alias
                for alias in category_aliases
                if alias not in {"type", "job_type", "employment_type"}
            ]
            for alias in ("product_type",):
                if alias not in ecommerce_aliases["category"]:
                    ecommerce_aliases["category"].append(alias)
        return ecommerce_aliases
    if normalized.startswith("job_"):
        job_aliases = {
            canonical: list(values) for canonical, values in aliases.items()
        }
        if "job_type" in job_aliases:
            for alias in ("type", "employment_type", "commitment", "work_type"):
                if alias not in job_aliases["job_type"]:
                    job_aliases["job_type"].append(alias)
        return job_aliases
    return aliases


def normalize_field_key(value: str | None) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return ""
    text = text.replace("&", " ")
    text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", text)
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)
    text = text.lower()
    text = _NON_FIELD_RE.sub("_", text)
    return re.sub(r"_+", "_", text).strip("_.")


def _dedupe_aliases(*groups: object) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for group in groups:
        candidates: tuple[str, ...]
        if isinstance(group, str):
            candidates = (group,)
        elif isinstance(group, (list, tuple, set, frozenset)):
            candidates = tuple(str(item) for item in group)
        else:
            continue
        for alias in candidates:
            cleaned = str(alias).strip()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                deduped.append(cleaned)
    return deduped


_REQUESTED_FIELD_ALIAS_BASES = {
    "responsibilities": _FIELD_ALIASES.get("responsibilities", []),
    "qualifications": _FIELD_ALIASES.get("qualifications", []),
    "benefits": _FIELD_ALIASES.get("benefits", []),
    "skills": _FIELD_ALIASES.get("skills", []),
    "summary": _FIELD_ALIASES.get("summary", []),
    "specifications": _FIELD_ALIASES.get("specifications", []),
    "product_details": _FIELD_ALIASES.get("product_details", []),
    "features": _FIELD_ALIASES.get("features", []),
    "materials": _FIELD_ALIASES.get("materials", []),
    "material": _FIELD_ALIASES.get("materials", []),
    "care": _FIELD_ALIASES.get("care", []),
    "dimensions": _FIELD_ALIASES.get("dimensions", []),
    "remote": _FIELD_ALIASES.get("remote", []),
    "requirements": _FIELD_ALIASES.get("requirements", []),
    "country_of_origin": [
        "country of origin",
        "country_of_origin",
        "origin",
        "made in",
        "manufactured in",
        "importer",
        "importer_info",
        "importer name and address",
    ],
    "color_variants": _FIELD_ALIASES.get("color_variants", []),
}
_REQUESTED_FIELD_ALIAS_EXTRAS = {
    "responsibilities": (
        "job responsibilities",
        "key responsibilities",
        "job duties",
        "what you'll do",
        "what_you_ll_do",
        "what_you_will_do",
        "role responsibilities",
    ),
    "qualifications": (
        "job qualifications",
        "job_qualification",
        "should have",
        "you should have",
        "minimum requirements",
        "minimum_requirements",
        "preferred qualifications",
        "preferred_qualifications",
        "who you are",
        "what we're looking for",
    ),
    "benefits": (
        "job benefits",
        "perks",
        "why you'll love this job",
        "life at stripe",
        "what we offer",
    ),
    "skills": ("job skills", "job_skills", "experience", "what you'll bring"),
    "summary": ("description", "our opportunity", "about the role", "about the team"),
    "specifications": (
        "specs",
        "spec",
        "technical details",
        "tech specs",
        "the details",
    ),
    "product_details": ("product detail",),
    "features": ("key features",),
    "materials": ("fabrics", "material composition"),
    "material": ("fabrics", "material composition"),
    "care": ("care instructions", "washing instructions"),
}
REQUESTED_FIELD_ALIASES = {
    canonical: _dedupe_aliases(
        _REQUESTED_FIELD_ALIAS_BASES[canonical],
        _REQUESTED_FIELD_ALIAS_EXTRAS.get(canonical, ()),
    )
    for canonical in _REQUESTED_FIELD_ALIAS_BASES
}
_ALIAS_TO_CANONICAL: dict[str, str] = {}
NORMALIZED_REQUESTED_FIELD_ALIASES: dict[str, list[str]] = {}
for canonical, aliases in REQUESTED_FIELD_ALIASES.items():
    canonical_key = normalize_field_key(canonical)
    if canonical_key:
        _ALIAS_TO_CANONICAL[canonical_key] = canonical_key
    normalized_aliases: list[str] = []
    for alias in aliases:
        alias_key = normalize_field_key(alias)
        if alias_key and alias_key not in _ALIAS_TO_CANONICAL:
            _ALIAS_TO_CANONICAL[alias_key] = canonical_key or canonical
        if alias_key and alias_key not in normalized_aliases:
            normalized_aliases.append(alias_key)
    if canonical_key:
        NORMALIZED_REQUESTED_FIELD_ALIASES[canonical_key] = _dedupe_aliases(
            canonical_key,
            normalized_aliases,
        )


def normalize_requested_field(value: str | None) -> str:
    text = normalize_field_key(value)
    if not text:
        return ""
    if text.startswith("sections."):
        text = text.split(".", 1)[1]
    for candidate in _requested_field_candidates(text):
        canonical = _ALIAS_TO_CANONICAL.get(candidate)
        if canonical:
            return canonical

    best_match = ""
    best_score = (0, 0)
    for candidate in _requested_field_candidates(text):
        candidate_tokens = set(candidate.split("_"))
        for alias_key, canonical in _ALIAS_TO_CANONICAL.items():
            alias_tokens = set(alias_key.split("_"))
            if not alias_tokens or not alias_tokens.issubset(candidate_tokens):
                continue
            score = (len(alias_tokens), len(alias_key))
            if score > best_score:
                best_score = score
                best_match = canonical
    return best_match or text


def exact_requested_field_key(value: str | None) -> str:
    text = normalize_field_key(value)
    if not text:
        return ""
    if text.startswith("sections."):
        text = text.split(".", 1)[1]
    for candidate in _requested_field_candidates(text):
        canonical = _ALIAS_TO_CANONICAL.get(candidate)
        if canonical:
            return canonical
    return text


def _requested_field_candidates(text: str) -> list[str]:
    candidates = [text]
    for prefix in _REQUESTED_FIELD_PREFIXES:
        if text.startswith(prefix):
            stripped = text[len(prefix) :]
            if stripped and stripped not in candidates:
                candidates.append(stripped)
    return candidates


def expand_requested_fields(values: Iterable[str] | None) -> list[str]:
    expanded: list[str] = []
    for value in values or []:
        normalized = normalize_requested_field(value)
        if normalized and normalized not in expanded:
            expanded.append(normalized)
    return expanded


def canonical_requested_fields(values: Iterable[str] | None) -> list[str]:
    return expand_requested_fields(values)


def repair_target_fields_for_surface(
    surface: str,
    requested_fields: Iterable[str] | None,
) -> list[str]:
    normalized = str(surface or "").strip().lower()
    requested = [
        field_name
        for field_name in canonical_requested_fields(requested_fields)
        if field_allowed_for_surface(normalized, field_name)
    ]
    defaults = [
        field_name
        for field_name in list(SURFACE_FIELD_REPAIR_TARGETS.get(normalized) or [])
        if field_allowed_for_surface(normalized, field_name)
    ]
    # Union: user-requested fields + surface canonical defaults.
    # A setup crawl must discover selectors for both so domain memory is
    # maximally useful on subsequent cheaper runs.
    seen: set[str] = set(requested)
    return requested + [f for f in defaults if f not in seen]


def browser_retry_target_fields_for_surface(
    surface: str,
    requested_fields: Iterable[str] | None,
) -> list[str]:
    normalized = str(surface or "").strip().lower()
    requested = [
        field_name
        for field_name in canonical_requested_fields(requested_fields)
        if field_allowed_for_surface(normalized, field_name)
    ]
    defaults = [
        field_name
        for field_name in list(SURFACE_BROWSER_RETRY_TARGETS.get(normalized) or [])
        if field_allowed_for_surface(normalized, field_name)
    ]
    # Union: if user asked for price+title but canonical retry targets include
    # currency, we still upgrade to browser when currency is missing.
    seen: set[str] = set(requested)
    return requested + [f for f in defaults if f not in seen]


def preserve_requested_fields(values: Iterable[str] | None) -> list[str]:
    preserved: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        cleaned = " ".join(str(value or "").split()).strip()
        if not cleaned:
            continue
        dedupe_key = cleaned.casefold()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        preserved.append(cleaned)
    return preserved


def normalize_review_target(surface: str, field_name: str | None) -> str:
    normalized = normalize_field_key(field_name)
    if not normalized or not field_allowed_for_surface(surface, normalized):
        return ""
    return normalized
