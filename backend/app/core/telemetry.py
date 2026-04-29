from __future__ import annotations

import asyncio
import errno
import logging
import sys
import weakref
from collections.abc import MutableMapping
from contextvars import ContextVar, Token
from typing import Any, cast
from uuid import uuid4

structlog: Any | None = None
try:
    import structlog as _structlog
    structlog = _structlog
except ImportError:  # pragma: no cover - optional dependency fallback
    pass

_correlation_id_ctx: ContextVar[str | None] = ContextVar("correlation_id", default=None)
_LOGGING_CONFIGURED = False
_ASYNCIO_EXCEPTION_FILTERS: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, object]" = (
    weakref.WeakKeyDictionary()
)


def _add_correlation_id(
    logger: object,
    method_name: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    del logger, method_name
    correlation_id = get_correlation_id()
    if correlation_id:
        event_dict["correlation_id"] = correlation_id
    return event_dict


def configure_logging() -> None:
    global _LOGGING_CONFIGURED
    if _LOGGING_CONFIGURED:
        return
    if structlog is None:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
            stream=sys.stdout,
        )
        _LOGGING_CONFIGURED = True
        return

    shared_processors = cast(list[Any], [
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        _add_correlation_id,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ])
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root_logger = logging.getLogger()
    if not any(
        isinstance(existing, logging.StreamHandler)
        and getattr(existing, "stream", None) is sys.stdout
        and isinstance(
            getattr(existing, "formatter", None),
            structlog.stdlib.ProcessorFormatter,
        )
        for existing in root_logger.handlers
    ):
        root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            _add_correlation_id,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    _LOGGING_CONFIGURED = True


def _is_known_windows_pipe_reset(
    context: MutableMapping[str, Any],
) -> bool:
    exc = context.get("exception")
    if not isinstance(exc, ConnectionResetError):
        return False
    winerror = getattr(exc, "winerror", None)
    if winerror not in {None, 10054} and getattr(exc, "errno", None) != errno.ECONNRESET:
        return False
    message = str(context.get("message") or "")
    handle = str(context.get("handle") or "")
    probe = f"{message}\n{handle}".lower()
    return "_proactorbasepipetransport._call_connection_lost" in probe


def install_asyncio_exception_filter(
    loop: asyncio.AbstractEventLoop | None = None,
) -> None:
    target_loop = loop or asyncio.get_running_loop()
    if target_loop in _ASYNCIO_EXCEPTION_FILTERS:
        return
    previous_handler = target_loop.get_exception_handler()

    def _handler(
        loop: asyncio.AbstractEventLoop,
        context: MutableMapping[str, Any],
    ) -> None:
        if _is_known_windows_pipe_reset(context):
            logging.getLogger("asyncio").debug(
                "Suppressed benign Windows Proactor pipe reset during transport teardown"
            )
            return
        context_dict = dict(context)
        if previous_handler is not None:
            previous_handler(loop, context_dict)
            return
        loop.default_exception_handler(context_dict)

    target_loop.set_exception_handler(_handler)
    _ASYNCIO_EXCEPTION_FILTERS[target_loop] = _handler


def generate_correlation_id() -> str:
    return uuid4().hex[:16]


def get_correlation_id() -> str | None:
    return _correlation_id_ctx.get()


def set_correlation_id(correlation_id: str | None) -> Token[str | None]:
    return _correlation_id_ctx.set(correlation_id)


def reset_correlation_id(token: Token[str | None]) -> None:
    _correlation_id_ctx.reset(token)
