from __future__ import annotations

from app.services.semantic_detail_extractor import extract_semantic_detail_data


def test_extract_semantic_detail_data_empty_html_includes_aggregates_key():
    result = extract_semantic_detail_data("")

    assert result == {
        "sections": {},
        "specifications": {},
        "promoted_fields": {},
        "coverage": {},
        "aggregates": {},
        "table_groups": [],
    }
