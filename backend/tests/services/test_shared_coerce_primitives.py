from __future__ import annotations

from app.services.shared.coerce_primitives import (
    coerce_int,
    object_dict,
    object_list,
    safe_int,
    string_list,
)


def test_safe_int_covers_normal_null_and_malformed_values() -> None:
    assert safe_int("12") == 12
    assert safe_int("-2") == -2
    assert safe_int(" 12 ", default=0) == 12
    assert safe_int(None, default=7) == 7
    assert safe_int("", default=3) == 3
    assert safe_int("bad", default=None) is None


def test_coerce_int_rejects_bool_and_malformed_values() -> None:
    assert coerce_int(" 12 ") == 12
    assert coerce_int(8) == 8
    assert coerce_int(False, default=9) == 9
    assert coerce_int(True, default=9) == 9
    assert coerce_int("bad", default=4) == 4
    assert coerce_int(None, default=4) == 4


def test_object_container_helpers_only_accept_expected_shapes() -> None:
    assert object_list([1, 2]) == [1, 2]
    assert object_list(("x",)) == []
    assert object_dict({"a": 1}) == {"a": 1}
    assert object_dict([("a", 1)]) == {}


def test_string_list_supports_legacy_call_shapes() -> None:
    assert string_list([" a ", None], strip=True, none_as_empty=True) == ["a", ""]
    assert string_list(("a", 2), accept_iterable=True) == ["a", "2"]
    assert string_list(("a", 2)) == []
    assert string_list("abc", accept_iterable=True) == []
    assert string_list({"a": 1}, accept_iterable=True) == []
