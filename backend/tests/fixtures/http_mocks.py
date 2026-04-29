from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any


class FakeBodyResponse:
    def __init__(
        self,
        body: bytes | None = None,
        *,
        error: Exception | None = None,
        url: str = "https://example.com/api/data.json",
        headers: dict[str, str] | None = None,
    ) -> None:
        self._body = body
        self._error = error
        self.url = url
        self.body_calls = 0
        self.headers = headers or {}

    async def body(self) -> bytes:
        self.body_calls += 1
        if self._error is not None:
            raise self._error
        return self._body or b""


class FakeTextResponse:
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text


class FakeAsyncClient:
    def __init__(self, response_factory: Callable[[str], Awaitable[Any]]) -> None:
        self._response_factory = response_factory

    async def __aenter__(self) -> "FakeAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def get(self, url: str) -> Any:
        return await self._response_factory(url)
