from __future__ import annotations

import json
from json import loads as parse_json
from typing import Any

from app.services.config.llm_runtime import llm_runtime_settings
from app.services.extraction_html_helpers import prune_html_tree
from app.services.structured_sources import harvest_js_state_objects, parse_json_ld
from bs4 import BeautifulSoup, Tag


def extract_structured_data(html_text: str) -> dict[str, object]:
    soup = BeautifulSoup(html_text, "html.parser")
    structured: dict[str, object] = {}

    def _append_structured_item(type_name: str, item: dict[str, object]) -> None:
        existing = structured.get(type_name)
        if isinstance(existing, list):
            existing.append(item)
        else:
            structured[type_name] = [item]

    for item in parse_json_ld(soup):
        if isinstance(item, dict) and item.get("@type"):
            type_name = str(item["@type"]).split("/")[-1]
            _append_structured_item(type_name, item)
    for key, value in harvest_js_state_objects(soup, html_text).items():
        if key == "__NEXT_DATA__" and isinstance(value, dict):
            structured[key] = value
    return structured


def truncate_html(
    html_text: str,
    limit: int,
    *,
    anchors: list[str] | None = None,
) -> str:
    if limit <= 0:
        return ""
    pruned = render_html_text(_prune_html_for_llm(html_text))
    if len(pruned) <= limit:
        return pruned
    focused = _focus_html_context(pruned, anchors or [])
    return (focused or pruned)[:limit]


def render_html_text(value: str) -> str:
    soup = BeautifulSoup(str(value or ""), "html.parser")
    for node in soup.find_all("br"):
        node.replace_with("\n")
    lines: list[str] = []
    seen: set[str] = set()
    block_tags = [
        tag.strip()
        for tag in llm_runtime_settings.html_render_block_tags.split(",")
        if tag.strip()
    ]
    for node in soup.find_all(block_tags):
        text = "\n".join(
            line.strip()
            for line in node.get_text(separator="\n", strip=True).splitlines()
            if line.strip()
        ).strip()
        if not text:
            continue
        lowered = " ".join(text.lower().split())
        if lowered in seen:
            continue
        seen.add(lowered)
        lines.append(text)
    if lines:
        return "\n".join(lines)
    return "\n".join(
        line.strip()
        for line in soup.get_text(separator="\n", strip=True).splitlines()
        if line.strip()
    ).strip()


def safe_truncate_for_prompt(
    value: object,
    max_str_len: int = llm_runtime_settings.prompt_safe_truncate_max_str_len,
    max_list_items: int = llm_runtime_settings.prompt_safe_truncate_max_list_items,
) -> object:
    if isinstance(value, str):
        return value[:max_str_len] + "..." if len(value) > max_str_len else value
    if isinstance(value, list):
        truncated = [
            safe_truncate_for_prompt(
                item,
                max_str_len=max_str_len,
                max_list_items=max_list_items,
            )
            for item in value[:max_list_items]
        ]
        if len(value) > max_list_items:
            truncated.append(f"... ({len(value) - max_list_items} more items)")
        return truncated
    if isinstance(value, dict):
        return {
            str(key): safe_truncate_for_prompt(
                item,
                max_str_len=max_str_len,
                max_list_items=max_list_items,
            )
            for key, item in value.items()
        }
    return value


def truncate_json_literal(value: Any, limit: int) -> str:
    compact = _compact_json_value(value)
    rendered = json.dumps(compact, default=str)
    if len(rendered) <= limit:
        return rendered
    if isinstance(compact, dict):
        trimmed: dict[str, Any] = {}
        for key, item in compact.items():
            candidate = {**trimmed, key: item}
            if len(json.dumps(candidate, default=str)) > limit:
                break
            trimmed[key] = item
        return json.dumps(trimmed, default=str)
    if isinstance(compact, list):
        trimmed_list: list[Any] = []
        for item in compact:
            candidate_list = [*trimmed_list, item]
            if len(json.dumps(candidate_list, default=str)) > limit:
                break
            trimmed_list.append(item)
        return json.dumps(trimmed_list, default=str)
    return json.dumps(str(compact)[: max(0, limit - 2)], default=str)


def enforce_token_limit(
    text: str,
    limit: int = llm_runtime_settings.prompt_token_limit,
) -> str:
    char_limit = limit * llm_runtime_settings.prompt_token_char_multiplier
    if len(text) <= char_limit:
        return text
    suffix = "\n\n[TRUNCATED DUE TO TOKEN LIMIT]"
    budget = max(0, char_limit - len(suffix))
    sections = text.split("\n\n")
    kept: list[str] = []
    used = 0
    for section in sections:
        separator = 0 if not kept else 2
        section_len = len(section)
        if used + separator + section_len <= budget:
            kept.append(section)
            used += separator + section_len
            continue
        remaining = budget - used - separator
        if remaining > 0:
            trimmed = trim_prompt_section(section, remaining)
            if trimmed:
                kept.append(trimmed)
        break
    if not kept:
        return suffix.strip()
    return "\n\n".join(kept) + suffix


def trim_prompt_section(section: str, budget: int) -> str:
    if budget <= 0:
        return ""
    placeholder = "[TRUNCATED]"
    if len(section) <= budget:
        return section
    if "\n" not in section:
        return section[:budget]
    header, body = section.split("\n", 1)
    preserved_header = header[:budget]
    if len(preserved_header) >= budget:
        return preserved_header
    remainder_budget = budget - len(preserved_header) - 1
    if remainder_budget <= 0:
        return preserved_header
    trimmed_body = trim_prompt_section_body(body, remainder_budget, placeholder)
    if not trimmed_body:
        return preserved_header
    return f"{preserved_header}\n{trimmed_body}"


def trim_prompt_section_body(body: str, budget: int, placeholder: str) -> str:
    if budget <= 0:
        return ""
    stripped = body.strip()
    if len(stripped) <= budget:
        return stripped
    if stripped.startswith(("{", "[")):
        if len(stripped) <= llm_runtime_settings.prompt_json_reparse_max_chars:
            try:
                parsed = parse_json(stripped)
            except json.JSONDecodeError:
                return _truncate_structured_text(stripped, budget, placeholder)
            else:
                return truncate_json_literal(parsed, budget)
        return _truncate_structured_text(stripped, budget, placeholder)
    if budget <= len(placeholder):
        return placeholder[:budget]
    return stripped[: budget - len(placeholder)].rstrip() + placeholder


def stringify_prompt_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, indent=2, default=str)


def _load_prune_stripped_tags() -> frozenset[str]:
    return frozenset(
        tag.strip()
        for tag in llm_runtime_settings.html_prune_stripped_tags.split(",")
        if tag.strip()
    )


def _load_prune_preserved_script_types() -> frozenset[str]:
    return frozenset(
        t.strip().lower()
        for t in llm_runtime_settings.html_prune_preserved_script_types.split(",")
        if t.strip()
    )


def _load_prune_preserved_attrs() -> frozenset[str]:
    return frozenset(
        attr.strip()
        for attr in llm_runtime_settings.html_prune_preserved_attrs.split(",")
        if attr.strip()
    )


def _load_prune_preserved_script_ids() -> frozenset[str]:
    return frozenset(
        sid.strip()
        for sid in llm_runtime_settings.html_prune_preserved_script_ids.split(",")
        if sid.strip()
    )


def _load_prune_strip_attr_prefixes() -> tuple[str, ...]:
    return tuple(
        prefix.strip().lower()
        for prefix in llm_runtime_settings.html_prune_strip_attr_prefixes.split(",")
        if prefix.strip()
    )


def _load_prune_preserved_data_attr_prefixes() -> tuple[str, ...]:
    return tuple(
        prefix.strip().lower()
        for prefix in llm_runtime_settings.html_prune_preserved_data_attr_prefixes.split(
            ","
        )
        if prefix.strip()
    )


def _prune_html_for_llm(html_text: str) -> str:
    stripped_tags = _load_prune_stripped_tags()
    preserved_script_types = _load_prune_preserved_script_types()
    preserved_attrs = _load_prune_preserved_attrs()
    preserved_data_prefixes = _load_prune_preserved_data_attr_prefixes()
    preserved_script_ids = _load_prune_preserved_script_ids()
    strip_attr_prefixes = _load_prune_strip_attr_prefixes()

    def _preserve_tag(tag: Tag) -> bool:
        if tag.name != "script":
            return False
        script_type = str(tag.get("type") or "").strip().lower()
        return (
            script_type in preserved_script_types
            or str(tag.get("id") or "") in preserved_script_ids
        )

    def _keep_attr(key: str, _value: object) -> bool:
        return key in preserved_attrs or not _should_strip_llm_attr(
            key,
            strip_attr_prefixes=strip_attr_prefixes,
            preserved_data_prefixes=preserved_data_prefixes,
        )

    soup = prune_html_tree(
        BeautifulSoup(html_text, "html.parser"),
        drop_tags=set(stripped_tags),
        attr_filter=_keep_attr,
        preserve_tag=_preserve_tag,
    )
    for tag in soup.find_all(True):
        if tag.get("style"):
            del tag["style"]
    return str(soup)


def _should_strip_llm_attr(
    attr_name: str,
    *,
    strip_attr_prefixes: tuple[str, ...],
    preserved_data_prefixes: tuple[str, ...],
) -> bool:
    normalized = str(attr_name or "").strip().lower()
    if not normalized:
        return False
    if normalized.startswith("data-") and any(
        normalized.startswith(prefix) for prefix in preserved_data_prefixes
    ):
        return False
    return any(normalized.startswith(prefix) for prefix in strip_attr_prefixes)


def _focus_html_context(rendered_text: str, anchors: list[str]) -> str:
    normalized_anchors = _normalize_html_anchor_terms(anchors)
    if not normalized_anchors:
        return ""
    focused_lines: list[str] = []
    seen: set[str] = set()
    previous_line = ""
    for raw_line in rendered_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lowered = line.lower()
        if not any(anchor in lowered for anchor in normalized_anchors):
            previous_line = line
            continue
        if previous_line and previous_line not in seen:
            focused_lines.append(previous_line)
            seen.add(previous_line)
        if line not in seen:
            focused_lines.append(line)
            seen.add(line)
        previous_line = line
    return "\n".join(focused_lines)


def _normalize_html_anchor_terms(values: list[str]) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for value in values:
        raw = str(value or "").strip().lower()
        if not raw:
            continue
        for candidate in {
            raw,
            raw.replace("_", " "),
            raw.replace("&", "and"),
        }:
            cleaned = " ".join(candidate.split())
            if (
                len(cleaned) < llm_runtime_settings.html_anchor_min_length
                or cleaned in seen
            ):
                continue
            seen.add(cleaned)
            terms.append(cleaned)
    return sorted(terms, key=len, reverse=True)


def _truncate_structured_text(text: str, budget: int, placeholder: str) -> str:
    if budget <= 0:
        return ""
    if len(text) <= budget:
        return text
    if "\n" in text:
        framed = _truncate_structured_lines(text, budget, placeholder)
        if framed:
            return framed
    if budget <= len(placeholder):
        return placeholder[:budget]
    closing = ""
    if text.startswith("{") and budget > len(placeholder) + 1:
        closing = "}"
    elif text.startswith("[") and budget > len(placeholder) + 1:
        closing = "]"
    head_budget = budget - len(placeholder) - len(closing)
    if head_budget <= 0:
        return (placeholder + closing)[:budget]
    return text[:head_budget].rstrip() + placeholder + closing


def _truncate_structured_lines(text: str, budget: int, placeholder: str) -> str:
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    closing = ""
    if text.startswith("{") and text.rstrip().endswith("}"):
        closing = "}"
    elif text.startswith("[") and text.rstrip().endswith("]"):
        closing = "]"
    suffix = f"\n{placeholder}{closing}" if closing else f"\n{placeholder}"
    if len(lines[0]) + len(suffix) > budget:
        return ""
    kept = [lines[0]]
    used = len(lines[0])
    for line in lines[1:]:
        next_used = used + 1 + len(line)
        if next_used + len(suffix) > budget:
            break
        kept.append(line)
        used = next_used
    if len(kept) == len(lines):
        return "\n".join(kept)
    return "\n".join(kept) + suffix


def _compact_json_value(
    value: Any,
    *,
    depth: int = 0,
    max_depth: int = llm_runtime_settings.prompt_compact_json_max_depth,
) -> Any:
    if value in (None, "", [], {}):
        return value
    if depth >= max_depth:
        return _compact_leaf_value(value)
    if isinstance(value, dict):
        compact: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= llm_runtime_settings.prompt_compact_json_max_keys:
                break
            compact[str(key)] = _compact_json_value(
                item,
                depth=depth + 1,
                max_depth=max_depth,
            )
        return compact
    if isinstance(value, list):
        return [
            _compact_json_value(item, depth=depth + 1, max_depth=max_depth)
            for item in value[: llm_runtime_settings.prompt_compact_json_max_list_items]
        ]
    return _compact_leaf_value(value)


def _compact_leaf_value(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        if len(stripped) > llm_runtime_settings.prompt_compact_leaf_string_max_chars:
            return stripped[: llm_runtime_settings.prompt_compact_leaf_string_max_chars]
        return stripped
    return value
