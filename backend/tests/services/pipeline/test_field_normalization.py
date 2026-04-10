from app.services.pipeline.field_normalization import _requested_field_coverage


def test_requested_field_coverage_returns_empty_dict_for_empty_requested_fields():
    assert _requested_field_coverage({"title": "Example"}, []) == {}
