from __future__ import annotations

from app.services.pipeline.core import _is_error_page_record


def test_is_error_page_record_detects_locked_page_copy():
    assert _is_error_page_record(
        {
            "title": "Your account is locked.",
            "description": "This candidate has already applied for the selected opportunity.",
        }
    )


def test_is_error_page_record_ignores_real_job_content():
    assert not _is_error_page_record(
        {
            "title": "Senior Backend Engineer",
            "description": "Build distributed crawler services and data pipelines.",
        }
    )
