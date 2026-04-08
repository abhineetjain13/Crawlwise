from app.services.crawl_metadata import _clean_candidate_text, refresh_record_commit_metadata


class _DummyRecord:
    def __init__(self) -> None:
        self.source_trace = {}
        self.discovered_data = {}
        self.data = {}


class _DummyRun:
    def __init__(self) -> None:
        self.surface = "ecommerce_detail"
        self.requested_fields = []


def test_clean_candidate_text_preserves_zero_and_false():
    assert _clean_candidate_text(0) == "0"
    assert _clean_candidate_text(False) == "False"
    assert _clean_candidate_text(None) == ""


def test_refresh_record_commit_metadata_uses_cleaned_value_consistently():
    record = _DummyRecord()
    run = _DummyRun()

    refresh_record_commit_metadata(
        record,
        run=run,
        field_name="title",
        value="  Hello   world  ",
    )

    discovery_value = record.source_trace["field_discovery"]["title"]["value"]
    committed_value = record.source_trace["committed_fields"]["title"]["value"]
    assert discovery_value == "Hello world"
    assert committed_value == "Hello world"
