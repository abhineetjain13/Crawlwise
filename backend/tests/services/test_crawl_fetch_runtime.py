from __future__ import annotations

from types import SimpleNamespace

from app.services.crawl_fetch_runtime import (
    _MAX_CAPTURED_NETWORK_PAYLOAD_BYTES,
    _read_network_payload_body,
    _should_capture_network_payload,
)


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body
        self.body_calls = 0

    async def body(self) -> bytes:
        self.body_calls += 1
        return self._body


def test_should_capture_network_payload_skips_noise_and_large_declared_payloads() -> None:
    assert not _should_capture_network_payload(
        url="https://example.com/telemetry/events",
        content_type="application/json",
        headers={},
        captured_count=0,
    )
    assert not _should_capture_network_payload(
        url="https://example.com/api/products",
        content_type="application/json",
        headers={"content-length": str(_MAX_CAPTURED_NETWORK_PAYLOAD_BYTES + 1)},
        captured_count=0,
    )
    assert _should_capture_network_payload(
        url="https://example.com/api/products",
        content_type="application/json",
        headers={"content-length": "512"},
        captured_count=0,
    )


async def test_read_network_payload_body_rejects_oversized_body_before_decode() -> None:
    response = _FakeResponse(b"x" * (_MAX_CAPTURED_NETWORK_PAYLOAD_BYTES + 1))

    body = await _read_network_payload_body(response)

    assert body is None
    assert response.body_calls == 1
