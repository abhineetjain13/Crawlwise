from __future__ import annotations

import re
from pathlib import Path

from app.services.config.extraction_rules import SALARY_RANGE_REGEX
from app.services.config.field_mappings import CANONICAL_SCHEMAS, FIELD_ALIASES

REPO_ROOT = Path(__file__).resolve().parents[2]
def test_salary_range_regex_expands_currency_placeholders():
    assert "__CURRENCY_SYMBOL_CLASS__" not in SALARY_RANGE_REGEX
    assert "__CURRENCY_CODE_ALT__" not in SALARY_RANGE_REGEX
    assert "¥" in SALARY_RANGE_REGEX
    assert "(?i:" not in SALARY_RANGE_REGEX
    assert re.search(SALARY_RANGE_REGEX, "¥120,000 - ¥140,000 / month")
    assert re.search(SALARY_RANGE_REGEX, "usd 80k to usd 100k")
    assert re.search(SALARY_RANGE_REGEX, "C$120k - C$140k / year")


def test_field_mapping_modules_export_schema_and_alias_data():
    assert "ecommerce_detail" in CANONICAL_SCHEMAS
    assert "title" in FIELD_ALIASES
