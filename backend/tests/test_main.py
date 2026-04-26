from __future__ import annotations

from fastapi import Request
from fastapi.responses import Response

from app.core.telemetry import install_asyncio_exception_filter
from app.main import (
    _sanitize_header_name,
    _sanitize_header_value,
    correlation_middleware,
)


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

    monkeypatch.setattr(
        "app.main.settings.request_id_header", "X-Request-ID\r\nSet-Cookie"
    )

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"x-request-idset-cookie", b"req-123")],
        }
    )

    response = await correlation_middleware(request, _call_next)

    assert response.headers["X-Request-ID"] != ""


async def test_correlation_middleware_falls_back_for_invalid_configured_header_name(
    monkeypatch,
) -> None:
    async def _call_next(request: Request) -> Response:
        assert request is not None
        return Response(status_code=204)

    monkeypatch.setattr("app.main.settings.request_id_header", "X-Request-ID:Bad")

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"x-request-id", b"req-123")],
        }
    )

    response = await correlation_middleware(request, _call_next)

    assert response.headers["X-Request-ID"] == "req-123"


def test_sanitize_header_value_removes_crlf_characters() -> None:
    assert _sanitize_header_value("abc\r\ndef\nxyz") == "abcdefxyz"


def test_sanitize_header_value_preserves_safe_content() -> None:
    assert _sanitize_header_value("req-123_ABC") == "req-123_ABC"


def test_sanitize_header_name_rejects_invalid_tokens() -> None:
    assert _sanitize_header_name("X-Request-ID:Bad") == "X-Request-ID"


def test_install_asyncio_exception_filter_suppresses_known_pipe_reset() -> None:
    class FakeLoop:
        def __init__(self) -> None:
            self.handler = None
            self.default_calls: list[object] = []

        def get_exception_handler(self):
            return None

        def set_exception_handler(self, handler) -> None:
            self.handler = handler

        def default_exception_handler(self, context) -> None:
            self.default_calls.append(context)

    loop = FakeLoop()
    install_asyncio_exception_filter(loop)  # type: ignore[arg-type]

    assert loop.handler is not None

    loop.handler(
        loop,
        {
            "message": "Exception in callback _ProactorBasePipeTransport._call_connection_lost()",
            "exception": ConnectionResetError(
                10054,
                "An existing connection was forcibly closed by the remote host",
            ),
        },
    )

    assert loop.default_calls == []


def test_install_asyncio_exception_filter_delegates_unknown_errors() -> None:
    class FakeLoop:
        def __init__(self) -> None:
            self.handler = None
            self.default_calls: list[object] = []

        def get_exception_handler(self):
            return None

        def set_exception_handler(self, handler) -> None:
            self.handler = handler

        def default_exception_handler(self, context) -> None:
            self.default_calls.append(context)

    loop = FakeLoop()
    install_asyncio_exception_filter(loop)  # type: ignore[arg-type]

    context = {
        "message": "Exception in callback something_else()",
        "exception": RuntimeError("boom"),
    }
    loop.handler(loop, context)

    assert loop.default_calls == [context]


def test_install_asyncio_exception_filter_preserves_original_context_for_previous_handler() -> None:
    previous_calls: list[object] = []

    class FakeLoop:
        def __init__(self) -> None:
            self.handler = None

        def get_exception_handler(self):
            return lambda inner_loop, context: previous_calls.append((inner_loop, context))

        def set_exception_handler(self, handler) -> None:
            self.handler = handler

        def default_exception_handler(self, context) -> None:
            raise AssertionError("default handler should not run")

    loop = FakeLoop()
    install_asyncio_exception_filter(loop)  # type: ignore[arg-type]

    context = {
        "message": "Exception in callback something_else()",
        "exception": RuntimeError("boom"),
    }
    loop.handler(loop, context)

    assert previous_calls == [(loop, context)]
