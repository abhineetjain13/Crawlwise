from __future__ import annotations

import json
from pathlib import Path


CONFIG_DIR = Path("backend/app/services/config")
CONFIG_FILES = (
    "extraction_rules.exports.json",
    "field_mappings.exports.json",
    "selectors.exports.json",
)
FIELD_MAPPING_KEYS = {
    "CANONICAL_SCHEMAS",
    "COLLECTION_KEYS",
    "DATALAYER_ECOMMERCE_FIELD_MAP",
    "ECOMMERCE_ONLY_FIELDS",
    "FIELD_ALIASES",
    "INTERNAL_ONLY_FIELDS",
    "JOB_ONLY_FIELDS",
    "PROMPT_REGISTRY",
}


def _load_json(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a top-level JSON object")
    return {str(key): value for key, value in data.items()}


def _preferred_owner(key: str) -> str:
    if key in FIELD_MAPPING_KEYS:
        return "field_mappings.exports.json"
    upper_key = key.upper()
    if any(token in upper_key for token in ("SELECTOR", "SELECTORS", "XPATH", "CSS_QUERY")):
        return "selectors.exports.json"
    return "extraction_rules.exports.json"


def main() -> None:
    payloads = {
        name: _load_json(CONFIG_DIR / name)
        for name in CONFIG_FILES
    }
    deduped = {name: {} for name in CONFIG_FILES}

    for name in CONFIG_FILES:
        for key, value in payloads[name].items():
            if key.startswith("_"):
                continue
            owners = [
                owner
                for owner in CONFIG_FILES
                if key in payloads[owner] and not key.startswith("_")
            ]
            preferred = _preferred_owner(key)
            owner = preferred if preferred in owners else owners[0]
            if owner == name:
                deduped[name][key] = value

    for name in CONFIG_FILES:
        path = CONFIG_DIR / name
        path.write_text(
            json.dumps(deduped[name], indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
