"""Regression: filter analytics / ticker-like keys from dynamic intelligence fields."""

from __future__ import annotations

import pytest
from app.services.extract.service import (
    _dynamic_field_name_is_schema_slug_noise,
    _dynamic_field_name_is_valid,
    _dynamic_value_is_bare_ticker_symbol,
)


@pytest.mark.parametrize(
    "name",
    [
        "xrp",
        "elp158",
        "e150d_en",
        "el_ab_12",
        "c1234",
        "ab12c_def",
    ],
)
def test_schema_slug_names_rejected(name: str) -> None:
    assert _dynamic_field_name_is_schema_slug_noise(name)
    assert not _dynamic_field_name_is_valid(name)


@pytest.mark.parametrize(
    "name",
    [
        "material",
        "weight_grams",
        "screen_size",
        "battery_life",
    ],
)
def test_reasonable_spec_names_accepted(name: str) -> None:
    assert not _dynamic_field_name_is_schema_slug_noise(name)
    assert _dynamic_field_name_is_valid(name)


def test_bare_ticker_value_gate() -> None:
    assert _dynamic_value_is_bare_ticker_symbol("XRP")
    assert _dynamic_value_is_bare_ticker_symbol("btc")
    assert not _dynamic_value_is_bare_ticker_symbol("XRP/USDT pair")
    assert not _dynamic_value_is_bare_ticker_symbol("")
