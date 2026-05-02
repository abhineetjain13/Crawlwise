from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.services.config.data_enrichment import (
    DATA_ENRICHMENT_AVAILABILITY_TERMS,
    DATA_ENRICHMENT_COLOR_FAMILY_ALIASES,
    DATA_ENRICHMENT_GENDER_ALIASES,
    DATA_ENRICHMENT_SEO_STOPWORDS,
    DATA_ENRICHMENT_SHOPIFY_ATTRIBUTE_CRAWL_FIELDS,
    DATA_ENRICHMENT_SHOPIFY_NORMALIZATION_ATTRIBUTE_NAMES,
    DATA_ENRICHMENT_TAXONOMY_CONTEXT_BLOCKS,
    DATA_ENRICHMENT_TAXONOMY_VERSION,
)
from app.services.field_value_core import clean_text, strip_html_tags

_token_re = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True, slots=True)
class TaxonomyIndex:
    version: str
    categories: tuple[dict[str, object], ...]
    exact_lookup: dict[str, dict[str, object]]
    leaf_lookup: dict[str, tuple[dict[str, object], ...]]
    id_lookup: dict[str, dict[str, object]]


def normalize_category_path(value: object) -> str:
    return " > ".join(
        " ".join(tokenize_text(part))
        for part in clean_text(value).split(">")
        if tokenize_text(part)
    )


def tokenize_text(value: object) -> list[str]:
    return [
        normalized
        for token in _token_re.findall(clean_text(strip_html_tags(value)).casefold())
        if (normalized := normalize_taxonomy_token(token))
    ]


def normalize_taxonomy_token(value: object) -> str:
    token = str(value or "").strip().casefold()
    if len(token) > 4 and token.endswith("ies"):
        return f"{token[:-3]}y"
    if len(token) > 4 and token.endswith("sses"):
        return token[:-2]
    if len(token) > 4 and token.endswith(("xes", "ches", "shes")):
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def repository_terms(repository: dict[str, object]) -> dict[str, object]:
    terms = repository.get("normalization_terms")
    return dict(terms) if isinstance(terms, dict) else {}


def term_dict(terms: dict[str, object], key: str) -> dict[str, object]:
    value = terms.get(key)
    return dict(value) if isinstance(value, dict) else {}


def attribute_lookup_keys(attribute: str) -> tuple[str, ...]:
    normalized = str(attribute or "").strip().replace("-", "_")
    explicit = DATA_ENRICHMENT_SHOPIFY_ATTRIBUTE_CRAWL_FIELDS.get(normalized)
    if explicit:
        return tuple(str(item) for item in explicit)
    variants = [normalized]
    if normalized.endswith("_type"):
        variants.append(normalized[:-5])
    if normalized.startswith("target_"):
        variants.append(normalized.replace("target_", "", 1))
    return tuple(dict.fromkeys(item for item in variants if item))


def category_attribute_handles(
    category_path: str | None, taxonomy_index: TaxonomyIndex
) -> list[str]:
    if not category_path:
        return []
    reference = taxonomy_reference_for_category_path(category_path, taxonomy_index)
    if not reference:
        return []
    return [
        str(item)
        for item in object_list(reference.get("attribute_handles"))
        if str(item or "").strip()
    ]


def exact_category_match(
    values: list[object],
    taxonomy_index: TaxonomyIndex,
    scores: tuple[float, float],
) -> dict[str, object] | None:
    for value in values:
        normalized = normalize_category_path(clean_text(value))
        if normalized in taxonomy_index.exact_lookup:
            return category_match_payload(
                taxonomy_index.exact_lookup[normalized],
                score=scores[0],
                source="exact_path",
            )
        if not normalized:
            continue
        leaf_matches = list(taxonomy_index.leaf_lookup.get(normalized) or ())
        if len(leaf_matches) == 1:
            return category_match_payload(
                leaf_matches[0],
                score=scores[1],
                source="leaf",
            )
    return None


def top_taxonomy_candidates(
    data: dict[str, object],
    taxonomy_index: TaxonomyIndex,
    *,
    category_match_threshold: float,
    limit: int,
    candidate_values: list[object],
    candidate_value_loader,
) -> list[dict[str, object]]:
    exact_match = exact_category_match(candidate_values, taxonomy_index, (1.0, 0.92))
    if exact_match:
        return [exact_match]

    primary_tokens = pool_tokens(
        data, candidate_value_loader, "category", "product_type"
    )
    secondary_tokens = pool_tokens(data, candidate_value_loader, "title")
    tertiary_tokens = pool_tokens(data, candidate_value_loader, "brand", "materials")
    if not primary_tokens and not secondary_tokens and not tertiary_tokens:
        return []

    scored: list[dict[str, object]] = []
    for item in taxonomy_index.categories:
        category_tokens = set(
            item.get("path_match_tokens") or tokenize_text(item.get("category_path"))
        )
        attribute_tokens = (
            set(item.get("attribute_match_tokens") or ()) - category_tokens
        )
        if not category_tokens:
            continue
        if taxonomy_context_conflicts(
            primary_tokens | secondary_tokens | tertiary_tokens,
            item.get("category_path"),
        ):
            continue
        primary_score = weighted_overlap(primary_tokens, category_tokens)
        secondary_score = weighted_overlap(secondary_tokens, category_tokens)
        tertiary_score = weighted_overlap(tertiary_tokens, category_tokens)
        attribute_score = weighted_overlap(
            primary_tokens | secondary_tokens | tertiary_tokens,
            attribute_tokens,
        )
        score = (
            primary_score
            + (secondary_score * 0.35)
            + (tertiary_score * 0.15)
            + (attribute_score * 0.3)
        )
        if primary_score == 0 and score > 0:
            score *= 0.6
        if score < category_match_threshold:
            continue
        scored.append(
            category_match_payload(
                item,
                score=round(score, 3),
                source="scored_match",
            )
        )
    scored.sort(
        key=lambda item: (
            -float(item.get("score") or 0.0),
            len(str(item.get("category_path") or "")),
            str(item.get("category_path") or ""),
        )
    )
    return scored[:limit]


def taxonomy_context_conflicts(source_tokens: set[str], category_path: object) -> bool:
    if not source_tokens:
        return False
    path_text = clean_text(category_path).casefold()
    if not path_text:
        return False
    for block in tuple(DATA_ENRICHMENT_TAXONOMY_CONTEXT_BLOCKS or ()):
        if not isinstance(block, dict):
            continue
        context_terms = tuple(
            str(item).casefold() for item in object_list(block.get("context_terms"))
        )
        path_terms = tuple(
            str(item).casefold() for item in object_list(block.get("path_terms"))
        )
        if not context_terms or not path_terms:
            continue
        if not any(
            tokens and tokens <= source_tokens
            for term in context_terms
            if (tokens := set(tokenize_text(term)))
        ):
            continue
        if any(term in path_text for term in path_terms):
            return True
    return False


def taxonomy_reference_for_category_path(
    category_path: str, taxonomy_index: TaxonomyIndex
) -> dict[str, object] | None:
    match = exact_category_match([category_path], taxonomy_index, (1.0, 0.92))
    if not match:
        return None
    return taxonomy_reference_payload(
        taxonomy_index.id_lookup.get(str(match.get("category_id") or ""), {})
    )


@lru_cache(maxsize=16)
def load_attribute_repository_data(path: Path) -> dict[str, object]:
    raw = load_json_dict(path)
    raw_attributes = [
        item for item in object_list(raw.get("attributes")) if isinstance(item, dict)
    ]
    attribute_lookup = {
        str(item.get("handle") or "").replace("-", "_"): {
            "name": str(item.get("name") or ""),
            "handle": str(item.get("handle") or ""),
            "values": [
                str(value.get("name") or "")
                for value in object_list(item.get("values"))
                if isinstance(value, dict) and str(value.get("name") or "").strip()
            ],
        }
        for item in raw_attributes
        if str(item.get("handle") or "").strip()
    }
    color_attribute = attribute_by_name(
        raw_attributes,
        DATA_ENRICHMENT_SHOPIFY_NORMALIZATION_ATTRIBUTE_NAMES["color"],
    )
    color_values = {
        clean_text(value).casefold()
        for value in object_list(color_attribute.get("values"))
        if clean_text(value)
    }
    color_families = {
        canonical: [token for token in aliases if token.casefold() in color_values]
        or list(aliases)
        for canonical, aliases in DATA_ENRICHMENT_COLOR_FAMILY_ALIASES.items()
    }
    size_attribute = attribute_by_name(
        raw_attributes,
        DATA_ENRICHMENT_SHOPIFY_NORMALIZATION_ATTRIBUTE_NAMES["size"],
    )
    size_systems = shopify_size_systems(size_attribute)
    material_terms = shopify_material_terms(
        raw_attributes,
        DATA_ENRICHMENT_SHOPIFY_NORMALIZATION_ATTRIBUTE_NAMES["fabric"],
        DATA_ENRICHMENT_SHOPIFY_NORMALIZATION_ATTRIBUTE_NAMES["material"],
    )
    return {
        "version": str(raw.get("version") or ""),
        "normalization_terms": {
            "availability_terms": {
                key: list(values)
                for key, values in DATA_ENRICHMENT_AVAILABILITY_TERMS.items()
            },
            "color_families": color_families,
            "gender_terms": {
                key: list(values)
                for key, values in DATA_ENRICHMENT_GENDER_ALIASES.items()
            },
            "material_terms": material_terms,
            "seo_stopwords": list(DATA_ENRICHMENT_SEO_STOPWORDS),
            "size_systems": size_systems,
        },
        "attributes_by_handle": attribute_lookup,
    }


@lru_cache(maxsize=16)
def load_taxonomy_index(path: Path) -> TaxonomyIndex:
    raw = load_json_dict(path)
    rows: list[dict[str, object]] = []
    exact_lookup: dict[str, dict[str, object]] = {}
    leaf_lookup: dict[str, list[dict[str, object]]] = {}
    id_lookup: dict[str, dict[str, object]] = {}
    for vertical in object_list(raw.get("verticals")):
        if not isinstance(vertical, dict):
            continue
        for category in object_list(vertical.get("categories")):
            if not isinstance(category, dict):
                continue
            category_id = str(category.get("id") or "").strip()
            category_path = clean_text(category.get("full_name"))
            normalized_path = normalize_category_path(category_path)
            leaf = normalize_category_path(category.get("name"))
            if not category_id or not category_path or not normalized_path:
                continue
            row = {
                "category_id": category_id,
                "category_path": category_path,
                "normalized_path": normalized_path,
                "leaf": leaf,
                "attribute_handles": [
                    str(item.get("handle") or "").replace("-", "_")
                    for item in object_list(category.get("attributes"))
                    if isinstance(item, dict) and str(item.get("handle") or "").strip()
                ],
            }
            row["path_match_tokens"] = set(tokenize_text(row["category_path"]))
            row["attribute_match_tokens"] = category_attribute_match_tokens(row)
            rows.append(row)
            exact_lookup[normalized_path] = row
            if leaf:
                leaf_lookup.setdefault(leaf, []).append(row)
            id_lookup[category_id] = row
    return TaxonomyIndex(
        version=str(raw.get("version") or ""),
        categories=tuple(rows),
        exact_lookup=exact_lookup,
        leaf_lookup={key: tuple(value) for key, value in leaf_lookup.items()},
        id_lookup=id_lookup,
    )


def attribute_by_name(
    attributes: list[dict[str, object]], name: str
) -> dict[str, object]:
    normalized_name = str(name or "").strip().casefold()
    for item in attributes:
        if str(item.get("name") or "").strip().casefold() == normalized_name:
            values = [
                str(value.get("name") or "")
                for value in object_list(item.get("values"))
                if isinstance(value, dict) and str(value.get("name") or "").strip()
            ]
            return {
                "name": str(item.get("name") or ""),
                "handle": str(item.get("handle") or ""),
                "values": values,
            }
    return {}


def shopify_material_terms(
    attributes: list[dict[str, object]], *names: str
) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    for name in names:
        attribute = attribute_by_name(attributes, name)
        for value in object_list(attribute.get("values")):
            cleaned = clean_text(value).casefold()
            if cleaned:
                values.setdefault(cleaned, [cleaned])
    return values


def shopify_size_systems(attribute: dict[str, object]) -> dict[str, object]:
    aliases: dict[str, str] = {}
    alpha_values: set[str] = set()
    numeric_values: set[str] = set()
    for value in object_list(attribute.get("values")):
        cleaned = clean_text(value)
        if not cleaned:
            continue
        match = re.search(r"\(([A-Za-z0-9]+)\)\s*$", cleaned)
        canonical = match.group(1).upper() if match else ""
        if canonical:
            aliases[cleaned.casefold()] = canonical
            base_name = clean_text(re.sub(r"\s*\([A-Za-z0-9]+\)\s*$", "", cleaned))
            if base_name:
                aliases[base_name.casefold()] = canonical
            if re.fullmatch(r"[A-Z]{1,4}|\d+XL", canonical):
                alpha_values.add(canonical.casefold())
            elif canonical.isdigit():
                numeric_values.add(canonical.casefold())
        if cleaned.casefold() == "one size":
            aliases[cleaned.casefold()] = "OS"
            alpha_values.add("os")
        if cleaned.isdigit():
            numeric_values.add(cleaned.casefold())
    return {
        "aliases": aliases,
        "systems": {
            "alpha": sorted(alpha_values),
            "numeric": sorted(numeric_values),
        },
    }


def category_match_payload(
    item: dict[str, object], *, score: float, source: str
) -> dict[str, object]:
    return {
        "category_id": item.get("category_id") or "",
        "category_path": item.get("category_path") or "",
        "score": round(float(score), 3),
        "source": source,
        "taxonomy_reference": taxonomy_reference_payload(item) or {},
        "taxonomy_version": DATA_ENRICHMENT_TAXONOMY_VERSION,
    }


def taxonomy_reference_payload(item: dict[str, object]) -> dict[str, object] | None:
    if not item:
        return None
    return {
        "category_id": item.get("category_id") or "",
        "category_path": item.get("category_path") or "",
        "attribute_handles": list(item.get("attribute_handles") or []),
        "taxonomy_version": DATA_ENRICHMENT_TAXONOMY_VERSION,
    }


def pool_tokens(
    data: dict[str, object], candidate_value_loader, *keys: str
) -> set[str]:
    tokens: set[str] = set()
    for key in keys:
        for value in candidate_value_loader(data, key):
            tokens.update(tokenize_text(value))
    return tokens


def category_attribute_match_tokens(item: dict[str, object]) -> set[str]:
    return set(
        tokenize_text(
            " ".join(str(handle) for handle in item.get("attribute_handles") or [])
        )
    )


def weighted_overlap(source_tokens: set[str], category_tokens: set[str]) -> float:
    if not source_tokens or not category_tokens:
        return 0.0
    overlap = source_tokens & category_tokens
    if not overlap:
        return 0.0
    return len(overlap) / len(source_tokens)


def load_json_dict(path: Path) -> dict[str, object]:
    with Path(path).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Data enrichment JSON must be an object: {path}")
    return payload


def object_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []
