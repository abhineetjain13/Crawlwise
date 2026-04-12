from __future__ import annotations

import json


def normalize_json_candidate(value: object) -> str | None:
    candidate = str(value or "").strip()
    if not candidate:
        return None
    if candidate.endswith(";"):
        candidate = candidate[:-1].rstrip()
    if candidate[:1] not in "{[":
        return None
    return candidate


def extract_balanced_json_fragment(text: object) -> str:
    source_text = str(text or "")
    candidate = source_text.lstrip()
    if not candidate or candidate[0] not in "{[":
        return ""
    start_index = len(source_text) - len(candidate)
    try:
        _, end_index = json.JSONDecoder().raw_decode(source_text, start_index)
    except json.JSONDecodeError:
        pass
    else:
        return source_text[start_index:end_index]

    closing = "}" if candidate[0] == "{" else "]"
    depth = 0
    in_string = False
    escape = False
    for index, char in enumerate(candidate):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == candidate[0]:
            depth += 1
            continue
        if char == closing:
            depth -= 1
            if depth == 0:
                return candidate[: index + 1]
    return ""


def parse_json_fragment(text: object) -> dict | list | None:
    candidate = normalize_json_candidate(text)
    if candidate is None:
        return None
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, (dict, list)) else None
