# Field type classification helpers — used by extraction pipeline.
from __future__ import annotations

import re

from app.services.config.extraction_rules import (
    CANDIDATE_AVAILABILITY_TOKENS,
    CANDIDATE_CATEGORY_TOKENS,
    CANDIDATE_COLOR_CSS_NOISE_TOKENS,
    CANDIDATE_CURRENCY_TOKENS,
    CANDIDATE_DESCRIPTION_TOKENS,
    CANDIDATE_FIELD_GROUPS,
    CANDIDATE_IDENTIFIER_TOKENS,
    CANDIDATE_IMAGE_COLLECTION_TOKENS,
    CANDIDATE_IMAGE_TOKENS,
    CANDIDATE_PRICE_TOKENS,
    CANDIDATE_RATING_TOKENS,
    CANDIDATE_REVIEW_COUNT_TOKENS,
    CANDIDATE_SALARY_TOKENS,
    CANDIDATE_URL_SUFFIXES,
)
from app.services.extract.field_classifier import (
    _field_alias_tokens,
    _normalized_field_token,
)
from app.services.extract.candidate_processing import (
    _normalized_candidate_text,
    _AVAILABILITY_NOISE_PHRASES,
    _UI_ICON_TOKEN_RE,
    _UI_NOISE_TOKEN_RE,
    _SCRIPT_NOISE_RE,
    _UI_NOISE_PHRASES_RE,
    _VARIANT_SELECTOR_PROMPT_RE,
    _CROSSFIELD_VARIANT_VALUE_RE,
)


# ---------------------------------------------------------------------------
# Field group / token helpers
# ---------------------------------------------------------------------------

def _field_in_group(field_name: str, group_name: str) -> bool:
    return field_name in CANDIDATE_FIELD_GROUPS.get(group_name, set())


def _field_token(field_name: str) -> str:
    return _normalized_field_token(field_name)


def _field_has_any_token(field_name: str, tokens: tuple[str, ...]) -> bool:
    normalized = _field_token(field_name)
    return any(
        _normalized_field_token(token) in normalized for token in tokens if token
    )


_FIELD_TYPE_TOKENS: dict[str, tuple[str, ...]] = {
    "image_primary": CANDIDATE_IMAGE_TOKENS,
    "url": CANDIDATE_URL_SUFFIXES,
    "currency": CANDIDATE_CURRENCY_TOKENS,
    "numeric": CANDIDATE_PRICE_TOKENS,
    "salary": CANDIDATE_SALARY_TOKENS,
    "rating": CANDIDATE_RATING_TOKENS,
    "availability": CANDIDATE_AVAILABILITY_TOKENS,
    "category": CANDIDATE_CATEGORY_TOKENS,
    "description": CANDIDATE_DESCRIPTION_TOKENS,
    "identifier": CANDIDATE_IDENTIFIER_TOKENS,
    "image_collection": CANDIDATE_IMAGE_COLLECTION_TOKENS,
}


def _field_is_type(field_name: str, type_key: str) -> bool:
    normalized = _field_token(field_name)

    if type_key in {"color", "size"}:
        return _field_matches_exact_alias(normalized, type_key)
    if type_key in ("title", "job_text", "entity_name"):
        return _field_in_group(field_name, type_key)

    is_img_coll = _field_is_image_collection(field_name, normalized=normalized)
    if type_key == "image_collection":
        return is_img_coll

    is_img_prim = _field_is_primary_image(
        field_name,
        normalized=normalized,
        is_image_collection=is_img_coll,
    )
    if type_key == "image_primary":
        return is_img_prim

    if type_key == "url":
        return _field_is_url_type(
            field_name,
            normalized=normalized,
            is_primary_image=is_img_prim,
            is_image_collection=is_img_coll,
        )

    if type_key == "numeric":
        return _field_is_numeric_type(field_name)

    return _field_in_group(field_name, type_key) or _field_has_any_token(
        field_name, _FIELD_TYPE_TOKENS.get(type_key, ())
    )


def _field_matches_exact_alias(normalized: str, field_name: str) -> bool:
    return normalized in _field_alias_tokens(field_name)


def _field_is_image_collection(field_name: str, *, normalized: str) -> bool:
    return _field_in_group(field_name, "image_collection") or any(
        token in normalized for token in _FIELD_TYPE_TOKENS["image_collection"]
    )


def _field_is_primary_image(
    field_name: str,
    *,
    normalized: str,
    is_image_collection: bool,
) -> bool:
    return _field_in_group(field_name, "image_primary") or (
        not is_image_collection
        and _field_has_any_token(field_name, _FIELD_TYPE_TOKENS["image_primary"])
        and bool(normalized)
    )


def _field_is_url_type(
    field_name: str,
    *,
    normalized: str,
    is_primary_image: bool,
    is_image_collection: bool,
) -> bool:
    if is_primary_image or is_image_collection:
        return False
    return _field_in_group(field_name, "url") or any(
        normalized.endswith(_normalized_field_token(suffix))
        for suffix in _FIELD_TYPE_TOKENS["url"]
    )


def _field_is_numeric_type(field_name: str) -> bool:
    return (
        _field_in_group(field_name, "numeric")
        or _field_has_any_token(field_name, _FIELD_TYPE_TOKENS["numeric"])
        or _field_has_any_token(field_name, CANDIDATE_REVIEW_COUNT_TOKENS)
    )


# ---------------------------------------------------------------------------
# UI noise stripping
# ---------------------------------------------------------------------------

def _strip_ui_noise(value: str) -> str:
    text = _normalized_candidate_text(value)
    if not text:
        return ""
    if _UI_ICON_TOKEN_RE:
        text = _UI_ICON_TOKEN_RE.sub(" ", text)
    if _UI_NOISE_TOKEN_RE:
        text = _UI_NOISE_TOKEN_RE.sub(" ", text)
    if _SCRIPT_NOISE_RE:
        text = _SCRIPT_NOISE_RE.sub(" ", text)
    if _UI_NOISE_PHRASES_RE:
        text = _UI_NOISE_PHRASES_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip(" -|,:;/")
    return text


def _looks_like_variant_selector_text(value: str) -> bool:
    text = _normalized_candidate_text(value)
    if not text:
        return False
    return bool(
        _VARIANT_SELECTOR_PROMPT_RE.match(text)
        or _CROSSFIELD_VARIANT_VALUE_RE.match(text)
    )


def _normalize_color_candidate(value: str) -> str | None:
    cleaned = _strip_ui_noise(value)
    if not cleaned:
        return None
    if _looks_like_variant_selector_text(cleaned):
        return None
    lowered = cleaned.lower()
    if any(token in lowered for token in CANDIDATE_COLOR_CSS_NOISE_TOKENS):
        return None
    if any(marker in cleaned for marker in ("{", "}", ";")):
        return None
    if "colors" in cleaned.lower() and cleaned.split()[0].isdigit():
        return None
    # Reject JavaScript minified booleans/expressions: !1 (false), !0 (true)
    if re.search(r"!\d", cleaned):
        return None
    # Reject JS object shorthand patterns: key:value with non-alpha keys
    if re.search(r"(?<![A-Za-z ])\s*:\s*!", cleaned):
        return None
    cleaned = re.sub(r"(?i)^choose an option\b", "", cleaned).strip(" ,")
    cleaned = re.sub(r"(?i)\bclear\b$", "", cleaned).strip(" ,")
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    if len(cleaned) > 40:
        return None
    if len(cleaned.split()) > 6:
        return None
    lowered_clean = cleaned.lower()
    if any(phrase in lowered_clean for phrase in _AVAILABILITY_NOISE_PHRASES):
        return None
    return cleaned or None
