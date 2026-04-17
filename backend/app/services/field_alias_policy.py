from __future__ import annotations

from app.services.config.field_mappings import (
    CANONICAL_SCHEMAS,
    FIELD_ALIASES,
    INTERNAL_ONLY_FIELDS,
)

_ALL_CANONICAL_FIELDS = frozenset(
    field_name
    for fields in CANONICAL_SCHEMAS.values()
    for field_name in fields
)


def excluded_fields_for_surface(surface: str) -> frozenset[str]:
    normalized = (surface or "").strip().lower()
    allowed = frozenset(CANONICAL_SCHEMAS.get(normalized, _ALL_CANONICAL_FIELDS))
    return (_ALL_CANONICAL_FIELDS - allowed) | INTERNAL_ONLY_FIELDS


def field_allowed_for_surface(surface: str, field_name: str) -> bool:
    normalized_field = str(field_name or "").strip().lower()
    return bool(
        normalized_field and normalized_field not in excluded_fields_for_surface(surface)
    )


def get_surface_field_aliases(surface: str) -> dict[str, list[str]]:
    normalized = (surface or "").strip().lower()
    allowed = frozenset(CANONICAL_SCHEMAS.get(normalized, _ALL_CANONICAL_FIELDS))

    aliases = {
        canonical: list(aliases)
        for canonical, aliases in FIELD_ALIASES.items()
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
    return aliases


def _dedupe_aliases(*groups: object) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for group in groups:
        if isinstance(group, str):
            candidates = (group,)
        elif isinstance(group, (list, tuple, set)):
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
        "minimum requirements",
        "minimum_requirements",
        "preferred qualifications",
        "preferred_qualifications",
        "who you are",
        "what we're looking for",
    ),
    "benefits": ("job benefits", "perks", "why you'll love this job", "life at stripe"),
    "skills": ("job skills", "job_skills", "experience", "what you'll bring"),
    "summary": ("description", "our opportunity", "about the role", "about the team"),
    "specifications": ("specs", "spec", "technical details", "tech specs", "the details"),
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
