from __future__ import annotations

from app.core.telemetry import reset_correlation_id, set_correlation_id
from app.services._batch_runtime import _with_correlation_tag


def test_with_correlation_tag_prefixes_message_when_context_present():
    token = set_correlation_id("abc123def456")
    try:
        tagged = _with_correlation_tag("Pipeline started")
    finally:
        reset_correlation_id(token)

    assert tagged == "[corr=abc123def456] Pipeline started"


def test_with_correlation_tag_keeps_existing_prefix():
    token = set_correlation_id("abc123def456")
    try:
        tagged = _with_correlation_tag("[corr=abc123def456] already tagged")
    finally:
        reset_correlation_id(token)

    assert tagged == "[corr=abc123def456] already tagged"
