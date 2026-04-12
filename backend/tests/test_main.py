from __future__ import annotations

from fastapi import Request
from fastapi.responses import Response

from app.main import _sanitize_header_value, correlation_middleware


async def test_correlation_middleware_strips_crlf_from_request_id_header(
    monkeypatch,
) -> None:
    async def _call_next(request: Request) -> Response:
        assert request is not None
        return Response(status_code=204)

    monkeypatch.setattr("app.main.settings.request_id_header", "X-Request-ID")

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"x-request-id", b"abc\r\nx-injected: 1")],
        }
    )

    response = await correlation_middleware(request, _call_next)

    assert response.headers["X-Request-ID"] == "abcx-injected: 1"


async def test_correlation_middleware_strips_crlf_from_configured_header_name(
    monkeypatch,
) -> None:
    async def _call_next(request: Request) -> Response:
        assert request is not None
        return Response(status_code=204)

    monkeypatch.setattr("app.main.settings.request_id_header", "X-Request-ID\r\nSet-Cookie")

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"x-request-idset-cookie", b"req-123")],
        }
    )

    response = await correlation_middleware(request, _call_next)

    assert response.headers["X-Request-IDSet-Cookie"] == "req-123"


def test_sanitize_header_value_removes_crlf_characters() -> None:
    assert _sanitize_header_value("abc\r\ndef\nxyz") == "abcdefxyz"


def test_sanitize_header_value_preserves_safe_content() -> None:
    assert _sanitize_header_value("req-123_ABC") == "req-123_ABC"
