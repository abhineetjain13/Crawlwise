from __future__ import annotations

from app.services.publish.metadata import _clean_committed_value
from app.services.publish.review_shaping import _merge_review_bucket_entries


def test_clean_committed_value_uses_extract_owned_text_cleaner() -> None:
    assert _clean_committed_value("  Availability \n ") == "Availability"


def test_merge_review_bucket_entries_uses_extract_owned_fingerprint() -> None:
    merged = _merge_review_bucket_entries(
        [
            {"key": "availability", "value": "Availability", "source": "dom"},
            {"key": "availability", "value": "Availability", "source": "dom"},
        ]
    )

    assert merged == [
        {"key": "availability", "value": "Availability", "source": "dom"}
    ]
