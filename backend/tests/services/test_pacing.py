from __future__ import annotations

from app.services.acquisition.pacing import _normalized_host


def test_normalized_host_preserves_port_information() -> None:
    assert _normalized_host("https://example.com:8443/path?q=1") == "example.com:8443"
    assert _normalized_host("example.com:8443") == "example.com:8443"
