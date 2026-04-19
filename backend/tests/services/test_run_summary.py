from __future__ import annotations

from app.services.run_summary import as_int


def test_as_int_handles_common_scalar_types_without_stringifying() -> None:
    assert as_int(None) == 0
    assert as_int(True) == 1
    assert as_int(False) == 0
    assert as_int(5.7) == 5
    assert as_int(" 9 ") == 9
    assert as_int("5.7") == 5
    assert as_int(b" 11.9 ") == 11
    assert as_int(object()) == 0
