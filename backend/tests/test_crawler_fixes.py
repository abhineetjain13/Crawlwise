from __future__ import annotations
import re
import pytest
from app.services.normalizers import _extract_positive_number
from app.services.extract.listing_card_extractor import _clean_price_text
from app.services.extract.candidate_processing import _contains_unresolved_template_value
from app.services.config.extraction_rules import NORMALIZATION_RULES

def test_european_number_parsing():
    # Fix 3: Robust European number parsing
    assert _extract_positive_number("1.499,99") == 1499.99
    assert _extract_positive_number("14,99") == 14.99
    assert _extract_positive_number("12.345,67") == 12345.67
    assert _extract_positive_number("1.234,56") == 1234.56

def test_listing_card_last_match_price():
    # Fix 2: Last Match in DOM Strings
    # String contains old price then new price
    raw_text = "Was $99.99 Now $79.99"
    assert _clean_price_text(raw_text) == "$79.99"
    
    # Another case: multiple prices in a line
    raw_text_2 = "List: $100 Sale: $80 Final: $75"
    assert _clean_price_text(raw_text_2) == "$75"

def test_modern_template_leaks():
    # Fix 4: Catch Modern Frontend Template Leaks
    assert _contains_unresolved_template_value("{{ product.name }}") is True
    assert _contains_unresolved_template_value("[[ item.price ]]") is True
    assert _contains_unresolved_template_value("<% out.name %>") is True
    assert _contains_unresolved_template_value("{% if show %}...{% endif %}") is True
    assert _contains_unresolved_template_value("Normal title") is False


def test_normalization_rules_include_extended_noisy_attribute_tokens():
    tokens = set(NORMALIZATION_RULES["noisy_product_attribute_key_tokens"])

    assert {
        "address",
        "compliance",
        "email",
        "importer",
        "manufacturer",
        "responsible",
        "trade_name",
    }.issubset(tokens)
