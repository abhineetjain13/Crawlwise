from __future__ import annotations

from app.services.pipeline.trace_builders import _build_manifest_trace


def test_build_manifest_trace_scrubs_network_payload_sensitive_values():
    manifest = _build_manifest_trace(
        html="<html><body><h1>ok</h1></body></html>",
        xhr_payloads=[
            {
                "url": "https://api.example.com/data",
                "status": 200,
                "headers": {
                    "authorization": "Bearer abcdefghijklmnopqrstuvwxyz0123456789"
                },
                "body": {
                    "email": "person@example.com",
                    "token": "abcdefghijklmnopqrstuvwxyz0123456789",
                    "note": "Contact person@example.com with Bearer abcdefghijklmnopqrstuvwxyz0123456789",
                },
            }
        ],
        adapter_records=[],
    )

    row = manifest["network_payloads"][0]
    assert row["headers"]["authorization"] == "[REDACTED]"
    assert row["body"]["email"] == "[REDACTED]"
    assert row["body"]["token"] == "[REDACTED]"
    assert "[REDACTED]" in row["body"]["note"]


def test_build_manifest_trace_scrubs_session_and_cookie_payload_keys():
    manifest = _build_manifest_trace(
        html="<html><body><h1>ok</h1></body></html>",
        xhr_payloads=[
            {
                "url": "https://api.example.com/data",
                "status": 200,
                "headers": {
                    "Set-Cookie": "x=1",
                    "content-type": "application/json",
                    "X-Session-ID": "abc123",
                },
                "body": {
                    "session_id": "abc123",
                    "sessionid": "abc123",
                    "__session": "abc123",
                },
            }
        ],
        adapter_records=[],
    )

    row = manifest["network_payloads"][0]
    assert row["headers"]["Set-Cookie"] == "[REDACTED]"
    assert row["headers"]["X-Session-ID"] == "[REDACTED]"
    assert row["headers"]["content-type"] == "application/json"
    assert row["body"]["session_id"] == "[REDACTED]"
    assert row["body"]["sessionid"] == "[REDACTED]"
    assert row["body"]["__session"] == "[REDACTED]"
