from __future__ import annotations

import ast
from pathlib import Path
import re

from app.services.pipeline_config import CANONICAL_SCHEMAS, FIELD_ALIASES, SALARY_RANGE_REGEX


REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICES_DIR = REPO_ROOT / "backend" / "app" / "services"
PROTECTED_KNOWLEDGE_FILES = {
    "canonical_schemas.json",
    "field_aliases.json",
    "collection_keys.json",
    "card_selectors.json",
    "normalization_rules.json",
    "verdict_rules.json",
    "requested_field_aliases.json",
    "extraction_rules.json",
}
ALLOWED_KNOWLEDGE_LOADERS = {
    SERVICES_DIR / "pipeline_config.py",
    SERVICES_DIR / "knowledge_base" / "store.py",
}
DISALLOWED_INLINE_KNOWLEDGE_NAMES = {
    "_NON_LISTING_PATH_TOKENS",
    "_HUB_PATH_SEGMENTS",
    "_WEAK_LISTING_METADATA_FIELDS",
    "_GA_DATA_LAYER_KEYS",
    "_TITLE_NOISE_TOKENS",
    "CURRENCY_CODES",
    "_CURRENCY_SYMBOL_MAP",
    "_COLOR_NOISE_TOKENS",
    "_SIZE_NOISE_TOKENS",
}


def test_knowledge_base_json_files_are_only_loaded_through_config_modules():
    offenders: list[str] = []

    for path in (REPO_ROOT / "backend" / "app").rglob("*.py"):
        if path in ALLOWED_KNOWLEDGE_LOADERS:
            continue
        text = path.read_text(encoding="utf-8")
        for filename in PROTECTED_KNOWLEDGE_FILES:
            if filename in text:
                offenders.append(f"{path.relative_to(REPO_ROOT)} references {filename}")

    assert offenders == [], (
        "Knowledge-base JSON should be loaded only through pipeline_config.py or "
        "knowledge_base/store.py.\n" + "\n".join(offenders)
    )


def test_services_do_not_define_top_level_inline_field_alias_maps():
    field_names = {
        field
        for fields in CANONICAL_SCHEMAS.values()
        for field in fields
    } | set(FIELD_ALIASES.keys())
    offenders: list[str] = []

    for path in SERVICES_DIR.rglob("*.py"):
        if path in ALLOWED_KNOWLEDGE_LOADERS:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            if not isinstance(value, ast.Dict):
                continue

            keys: list[str] = []
            list_like_values = True
            string_only_values = True
            for key_node, value_node in zip(value.keys, value.values):
                if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
                    keys.append(key_node.value)
                else:
                    keys.append("")
                if not isinstance(value_node, (ast.List, ast.Tuple, ast.Set)):
                    list_like_values = False
                    break
                for item in value_node.elts:
                    if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
                        string_only_values = False
                        break
                if not string_only_values:
                    break

            overlapping_keys = sorted({key for key in keys if key in field_names})
            if list_like_values and string_only_values and len(overlapping_keys) >= 2:
                offenders.append(
                    f"{path.relative_to(REPO_ROOT)} defines inline field map for {', '.join(overlapping_keys)}"
                )

    assert offenders == [], (
        "Field alias/schema knowledge should live in knowledge_base JSON, not "
        "top-level Python maps.\n" + "\n".join(offenders)
    )


def test_services_do_not_define_disallowed_inline_knowledge_constants():
    offenders: list[str] = []

    for path in SERVICES_DIR.rglob("*.py"):
        if path in ALLOWED_KNOWLEDGE_LOADERS:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
            else:
                continue
            for target in targets:
                if isinstance(target, ast.Name) and target.id in DISALLOWED_INLINE_KNOWLEDGE_NAMES:
                    offenders.append(f"{path.relative_to(REPO_ROOT)} defines {target.id}")

    assert offenders == [], (
        "These knowledge constants must come from the JSON-backed config layer, not "
        "be redefined in service modules.\n" + "\n".join(offenders)
    )


def test_salary_range_regex_expands_currency_placeholders():
    assert "__CURRENCY_SYMBOL_CLASS__" not in SALARY_RANGE_REGEX
    assert "__CURRENCY_CODE_ALT__" not in SALARY_RANGE_REGEX
    assert "¥" in SALARY_RANGE_REGEX
    assert "(?i:" not in SALARY_RANGE_REGEX
    assert re.search(SALARY_RANGE_REGEX, "¥120,000 - ¥140,000 / month")
    assert re.search(SALARY_RANGE_REGEX, "usd 80k to usd 100k")
