from __future__ import annotations

from contextvars import ContextVar, Token
from uuid import uuid4

_correlation_id_ctx: ContextVar[str | None] = ContextVar(
    "correlation_id", default=None
)


def generate_correlation_id() -> str:
    return uuid4().hex[:16]


def get_correlation_id() -> str | None:
    return _correlation_id_ctx.get()


def set_correlation_id(correlation_id: str | None) -> Token[str | None]:
    return _correlation_id_ctx.set(correlation_id)


def reset_correlation_id(token: Token[str | None]) -> None:
    _correlation_id_ctx.reset(token)
