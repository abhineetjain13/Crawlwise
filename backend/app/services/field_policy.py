from __future__ import annotations

import re
from collections.abc import Iterable

from app.services.config.field_mappings import (
    CANONICAL_SCHEMAS,
    FIELD_ALIASES,
    INTERNAL_ONLY_FIELDS,
)

_CAMEL_BOUNDARY_RE = re.compile(r"(?<!^)(?=[A-Z])")
_NON_FIELD_RE = re.compile(r"[^a-z0-9.]+")
_ALL_CANONICAL_FIELDS = frozenset(
    field_name
    for fields in CANONICAL_SCHEMAS.values()
    for field_name in fields
)
HTML_SECTION_FIELDS = frozenset(
    {"responsibilities", "qualifications", "benefits", "skills"}
)


def canonical_fields_for_surface(surface: str) -> list[str]:
    normalized = str(surface or "").strip().lower()
    return list(CANONICAL_SCHEMAS.get(normalized, _ALL_CANONICAL_FIELDS))


def excluded_fields_for_surface(surface: str) -> frozenset[str]:
    allowed = frozenset(canonical_fields_for_surface(surface))
    return (_ALL_CANONICAL_FIELDS - allowed) | INTERNAL_ONLY_FIELDS


def field_allowed_for_surface(surface: str, field_name: str) -> bool:
    normalized_field = normalize_field_key(field_name)
    return bool(
        normalized_field
        and normalized_field not in excluded_fields_for_surface(surface)
    )


def get_surface_field_aliases(surface: str) -> dict[str, list[str]]:
    normalized = str(surface or "").strip().lower()
    allowed = frozenset(canonical_fields_for_surface(normalized))
    aliases = {
        canonical: list(values)
        for canonical, values in FIELD_ALIASES.items()
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
    text = " ".join(str(value or "").split()).strip().lower()
    if not text:
        return ""
    text = text.replace("&", " ")
    text = _CAMEL_BOUNDARY_RE.sub("_", text)
    text = _NON_FIELD_RE.sub("_", text)
    return re.sub(r"_+", "_", text).strip("_.")


def _dedupe_aliases(*groups: object) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for group in groups:
        if isinstance(group, str):
            candidates = (group,)
        elif isinstance(group, (list, tuple, set, frozenset)):
            candidates = group
        else:
            continue
        for alias in candidates:
            cleaned = str(alias).strip()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                deduped.append(cleaned)
    return deduped


_REQUESTED_FIELD_ALIAS_BASES = {
    "responsibilities": FIELD_ALIASES["responsibilities"],
    "qualifications": FIELD_ALIASES["qualifications"],
    "benefits": FIELD_ALIASES["benefits"],
    "skills": FIELD_ALIASES["skills"],
    "summary": FIELD_ALIASES["summary"],
    "specifications": FIELD_ALIASES["specifications"],
    "features": FIELD_ALIASES["features"],
    "materials": FIELD_ALIASES["materials"],
    "material": FIELD_ALIASES["materials"],
    "care": FIELD_ALIASES["care"],
    "dimensions": FIELD_ALIASES["dimensions"],
    "remote": FIELD_ALIASES["remote"],
    "requirements": FIELD_ALIASES["requirements"],
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
    "color_variants": FIELD_ALIASES["color_variants"],
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
    return _ALIAS_TO_CANONICAL.get(text, text)


def expand_requested_fields(values: Iterable[str] | None) -> list[str]:
    expanded: list[str] = []
    for value in values or []:
        normalized = normalize_requested_field(value)
        if normalized and normalized not in expanded:
            expanded.append(normalized)
    return expanded


def normalize_review_target(surface: str, field_name: str | None) -> str:
    normalized = normalize_field_key(field_name)
    if not normalized or not field_allowed_for_surface(surface, normalized):
        return ""
    return normalized
