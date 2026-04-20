from __future__ import annotations

import asyncio
import json
import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.acquisition.runtime import NetworkPayloadReadResult
from app.services.config.network_capture import (
    ENDPOINT_TYPE_PATH_TOKENS,
    GRAPHQL_PATH_TOKENS,
    HIGH_VALUE_NETWORK_ENDPOINT_TYPES,
    HIGH_VALUE_NETWORK_PAYLOAD_BUDGET_MULTIPLIER,
    NETWORK_PAYLOAD_NOISE_URL_RE,
)
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.platform_policy import classify_network_endpoint_family

logger = logging.getLogger(__name__)

_MAX_CAPTURED_NETWORK_PAYLOADS = (
    crawler_runtime_settings.browser_capture_max_network_payloads
)
_MAX_CAPTURED_NETWORK_PAYLOAD_BYTES = (
    crawler_runtime_settings.browser_capture_max_network_payload_bytes
)
_MAX_TOTAL_CAPTURED_NETWORK_PAYLOAD_BYTES = (
    crawler_runtime_settings.browser_capture_total_network_payload_bytes
)
_NETWORK_CAPTURE_QUEUE_SIZE = _MAX_CAPTURED_NETWORK_PAYLOADS * 2
_NETWORK_CAPTURE_WORKERS = 4
_NETWORK_PAYLOAD_STREAMING_CONTENT_TYPES = (
    "text/x-component",
)
_NETWORK_PAYLOAD_JSON_CONTENT_TYPE_HINTS = (
    "application/json",
    "application/trpc+json",
    "application/graphql-response+json",
)
_NETWORK_PAYLOAD_URL_HINTS = (
    ".json",
    "__flight__",
    "_rsc=",
)


@dataclass(slots=True)
class BrowserNetworkCaptureSummary:
    payloads: list[dict[str, object]]
    network_payload_count: int
    captured_network_payload_bytes: int
    malformed_network_payloads: int
    network_payload_read_failures: int
    closed_network_payloads: int
    skipped_oversized_network_payloads: int
    dropped_payload_events: int


class BrowserNetworkCapture:
    def __init__(
        self,
        *,
        surface: str,
        should_capture_payload: Any | None = None,
        classify_endpoint: Any | None = None,
        read_payload_body: Any | None = None,
    ) -> None:
        self._surface = surface
        self._should_capture_payload = should_capture_payload or should_capture_network_payload
        self._classify_endpoint = classify_endpoint or classify_network_endpoint
        self._read_payload_body = read_payload_body or read_network_payload_body
        self._lock = asyncio.Lock()
        self._payloads: list[dict[str, object]] = []
        self._queue: asyncio.Queue[Any | None] = asyncio.Queue(
            maxsize=max(1, _NETWORK_CAPTURE_QUEUE_SIZE)
        )
        self._workers: list[asyncio.Task[None]] = []
        self._closed = False
        self._closing = False
        self._listener_attached = False
        self._summary: BrowserNetworkCaptureSummary | None = None
        self._malformed_payloads = 0
        self._payload_read_failures = 0
        self._payload_closed_failures = 0
        self._oversized_payloads = 0
        self._captured_bytes = 0
        self._dropped_payload_events = 0

    def attach(self, page: Any) -> None:
        if self._listener_attached:
            return
        self._workers = [
            asyncio.create_task(self._capture_worker())
            for _ in range(
                max(1, min(_NETWORK_CAPTURE_WORKERS, _MAX_CAPTURED_NETWORK_PAYLOADS))
            )
        ]
        page.on("response", self._schedule_capture)
        self._listener_attached = True

    async def close(self, page: Any) -> BrowserNetworkCaptureSummary:
        if self._summary is not None:
            return self._summary
        remove_listener = getattr(page, "remove_listener", None)
        if callable(remove_listener):
            try:
                remove_listener("response", self._schedule_capture)
            except Exception as exc:
                if is_response_closed_error(exc):
                    logger.debug("Browser response listener detach skipped (page already closed)")
                else:
                    logger.warning(
                        "Failed to detach browser response listener: %s: %s",
                        type(exc).__name__,
                        exc,
                    )
        self._listener_attached = False
        if self._workers:
            await asyncio.sleep(0)
            join_timeout_seconds = _queue_join_timeout_seconds()
            try:
                await asyncio.wait_for(
                    self._queue.join(),
                    timeout=join_timeout_seconds,
                )
            except asyncio.TimeoutError:
                self._closing = True
                logger.warning(
                    "Browser capture queue join timed out after %ss; "
                    "cancelling workers and draining queue",
                    join_timeout_seconds,
                )
                for worker in self._workers:
                    worker.cancel()
                while not self._queue.empty():
                    try:
                        self._queue.get_nowait()
                        self._queue.task_done()
                    except asyncio.QueueEmpty:
                        break
            else:
                self._closing = True
            for _ in self._workers:
                try:
                    self._queue.put_nowait(None)
                except asyncio.QueueFull:
                    pass
            await asyncio.gather(*self._workers, return_exceptions=True)
            self._workers.clear()
        self._closed = True
        async with self._lock:
            self._summary = BrowserNetworkCaptureSummary(
                payloads=list(self._payloads[:_MAX_CAPTURED_NETWORK_PAYLOADS]),
                network_payload_count=len(self._payloads),
                captured_network_payload_bytes=self._captured_bytes,
                malformed_network_payloads=self._malformed_payloads,
                network_payload_read_failures=self._payload_read_failures,
                closed_network_payloads=self._payload_closed_failures,
                skipped_oversized_network_payloads=self._oversized_payloads,
                dropped_payload_events=self._dropped_payload_events,
            )
        return self._summary

    def _schedule_capture(self, response: Any) -> None:
        if self._closing:
            return
        try:
            self._queue.put_nowait(response)
        except asyncio.QueueFull:
            self._dropped_payload_events += 1

    async def _capture_worker(self) -> None:
        while True:
            response = await self._queue.get()
            try:
                if response is None:
                    return
                await self._capture_response(response)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.debug(
                    "Failed to capture browser network payload",
                    exc_info=True,
                )
            finally:
                self._queue.task_done()

    async def _capture_response(self, response: Any) -> None:
        content_type = str(response.headers.get("content-type", "") or "").lower()
        endpoint_info = self._classify_endpoint(
            response_url=response.url,
            surface=self._surface,
        )
        if not self._should_capture_payload(
            url=response.url,
            content_type=content_type,
            headers=response.headers,
            captured_count=len(self._payloads),
            captured_bytes=self._captured_bytes,
            surface=self._surface,
            endpoint_info=endpoint_info,
        ):
            return
        body_result = await self._read_payload_body(
            response,
            surface=self._surface,
            endpoint_info=endpoint_info,
        )
        if body_result.outcome == "response_closed":
            async with self._lock:
                self._payload_closed_failures += 1
            return
        if body_result.outcome == "too_large":
            async with self._lock:
                self._oversized_payloads += 1
            return
        if body_result.outcome == "read_error":
            async with self._lock:
                self._payload_read_failures += 1
            return
        body_bytes = body_result.body
        if body_bytes is None:
            return
        payload = _decode_network_payload(
            body_bytes,
            content_type=content_type,
        )
        if payload is None:
            async with self._lock:
                self._malformed_payloads += 1
            return
        async with self._lock:
            if not self._should_capture_payload(
                url=response.url,
                content_type=content_type,
                headers=response.headers,
                captured_count=len(self._payloads),
                captured_bytes=self._captured_bytes,
                surface=self._surface,
                endpoint_info=endpoint_info,
            ):
                return
            if (
                self._captured_bytes + len(body_bytes)
                > _MAX_TOTAL_CAPTURED_NETWORK_PAYLOAD_BYTES
            ):
                self._oversized_payloads += 1
                return
            self._payloads.append(
                {
                    "url": response.url,
                    "method": getattr(response.request, "method", "GET"),
                    "status": int(getattr(response, "status", 0) or 0),
                    "content_type": content_type,
                    "endpoint_type": endpoint_info["type"],
                    "endpoint_family": endpoint_info["family"],
                    "body": payload,
                }
            )
            self._captured_bytes += len(body_bytes)


def should_capture_network_payload(
    *,
    url: str,
    content_type: str,
    headers: dict[str, object] | Any,
    captured_count: int,
    captured_bytes: int = 0,
    surface: str = "",
    endpoint_info: dict[str, str] | None = None,
) -> bool:
    lowered_url = str(url or "").lower()
    if not _is_supported_network_payload_content_type(
        content_type=content_type,
        lowered_url=lowered_url,
    ):
        return False
    if captured_count >= _MAX_CAPTURED_NETWORK_PAYLOADS:
        return False
    if NETWORK_PAYLOAD_NOISE_URL_RE.search(lowered_url):
        return False
    payload_budget = _network_payload_byte_budget(
        url=url,
        surface=surface,
        endpoint_info=endpoint_info,
    )
    content_length = (
        None if has_chunked_transfer_encoding(headers) else coerce_content_length(headers)
    )
    if content_length is not None and content_length > payload_budget:
        return False
    if (
        content_length is not None
        and captured_bytes + content_length > _MAX_TOTAL_CAPTURED_NETWORK_PAYLOAD_BYTES
    ):
        return False
    if captured_bytes >= _MAX_TOTAL_CAPTURED_NETWORK_PAYLOAD_BYTES:
        return False
    return True


def _is_supported_network_payload_content_type(
    *,
    content_type: str,
    lowered_url: str,
) -> bool:
    normalized_content_type = str(content_type or "").strip().lower()
    if "json" in normalized_content_type:
        return True
    if any(token in normalized_content_type for token in _NETWORK_PAYLOAD_JSON_CONTENT_TYPE_HINTS):
        return True
    if any(token in lowered_url for token in _NETWORK_PAYLOAD_URL_HINTS):
        return True
    return any(
        token in normalized_content_type
        for token in _NETWORK_PAYLOAD_STREAMING_CONTENT_TYPES
    )


def _decode_network_payload(
    body_bytes: bytes,
    *,
    content_type: str,
) -> object | None:
    text = body_bytes.decode("utf-8", errors="replace")
    normalized_content_type = str(content_type or "").strip().lower()
    if any(
        token in normalized_content_type
        for token in _NETWORK_PAYLOAD_STREAMING_CONTENT_TYPES
    ):
        return _decode_rsc_payload(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _decode_rsc_payload(text: str) -> object | None:
    decoder = json.JSONDecoder()
    payloads: list[object] = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parsed = _decode_rsc_line(line, decoder=decoder)
        if parsed is not None:
            payloads.append(parsed)
    if not payloads:
        return None
    if len(payloads) == 1:
        return payloads[0]
    return payloads


def _decode_rsc_line(
    line: str,
    *,
    decoder: json.JSONDecoder,
) -> object | None:
    candidates = [line]
    colon_index = line.find(":")
    if colon_index >= 0:
        suffix = line[colon_index + 1 :].strip()
        if suffix:
            candidates.append(suffix)
    for candidate in candidates:
        start_index = next(
            (index for index, char in enumerate(candidate) if char in "[{\""),
            -1,
        )
        if start_index < 0:
            continue
        fragment = candidate[start_index:]
        try:
            parsed, _ = decoder.raw_decode(fragment)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, (dict, list)):
            return parsed
    return None


def classify_network_endpoint(*, response_url: str, surface: str) -> dict[str, str]:
    lowered_url = str(response_url or "").strip().lower()
    normalized_surface = str(surface or "").strip().lower()
    family = classify_network_endpoint_family(response_url)

    endpoint_type = "generic_json"
    if any(token in lowered_url for token in GRAPHQL_PATH_TOKENS):
        endpoint_type = "graphql"
    else:
        surface_tokens = ENDPOINT_TYPE_PATH_TOKENS.get(normalized_surface, {})
        for etype, tokens in surface_tokens.items():
            if any(token in lowered_url for token in tokens):
                endpoint_type = etype
                break
    return {"type": endpoint_type, "family": family}


async def read_network_payload_body(
    response: Any,
    *,
    surface: str = "",
    endpoint_info: dict[str, str] | None = None,
) -> NetworkPayloadReadResult:
    try:
        body_bytes = await response.body()
    except Exception as exc:
        if is_response_closed_error(exc):
            return NetworkPayloadReadResult(
                body=None,
                outcome="response_closed",
                error=f"{type(exc).__name__}: {exc}",
            )
        return NetworkPayloadReadResult(
            body=None,
            outcome="read_error",
            error=f"{type(exc).__name__}: {exc}",
        )
    payload_budget = _network_payload_byte_budget(
        url=str(getattr(response, "url", "") or ""),
        surface=surface,
        endpoint_info=endpoint_info,
    )
    if len(body_bytes) > payload_budget:
        return NetworkPayloadReadResult(body=None, outcome="too_large")
    return NetworkPayloadReadResult(body=body_bytes, outcome="read")
async def capture_browser_screenshot(page: Any) -> str:
    """Capture a browser screenshot to a temporary PNG file and return its path.

    The returned `temp_path` lives under `temp_dir`
    (`settings.artifacts_dir/tmp/browser_screenshots`). The caller owns that file
    and must delete it after use. If that lifecycle becomes hard to manage,
    consider returning PNG bytes instead or adding a periodic cleanup sweep for
    `settings.artifacts_dir/tmp/browser_screenshots`.
    """
    temp_dir = Path(settings.artifacts_dir) / "tmp" / "browser_screenshots"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=".png",
            dir=temp_dir,
        ) as handle:
            temp_path = Path(handle.name)
        await page.screenshot(path=temp_path, full_page=True, type="png")
        if temp_path.is_file() and temp_path.stat().st_size > 0:
            return str(temp_path)
    except Exception:
        logger.debug("Browser screenshot capture failed", exc_info=True)
    if temp_path is not None:
        temp_path.unlink(missing_ok=True)
    return ""


def coerce_content_length(headers: dict[str, object] | Any) -> int | None:
    if not headers:
        return None
    raw_value = headers.get("content-length")
    try:
        parsed = int(str(raw_value or "").strip())
    except (TypeError, ValueError):
        return None
    return max(0, parsed)


def has_chunked_transfer_encoding(headers: dict[str, object] | Any) -> bool:
    if not headers:
        return False
    raw_value = headers.get("transfer-encoding")
    normalized = str(raw_value or "").strip().lower()
    if not normalized:
        return False
    return any(token.strip() == "chunked" for token in normalized.split(","))


def _queue_join_timeout_seconds() -> float:
    return max(
        0.1,
        float(crawler_runtime_settings.browser_capture_queue_join_timeout_ms) / 1000,
    )


def is_response_closed_error(exc: Exception) -> bool:
    class_name = type(exc).__name__.lower()
    message = str(exc or "").lower()
    return (
        "targetclosed" in class_name
        or "target closed" in message
        or "page closed" in message
        or "browser has been closed" in message
    )


def _network_payload_byte_budget(
    *,
    url: str,
    surface: str,
    endpoint_info: dict[str, str] | None = None,
) -> int:
    resolved_endpoint = endpoint_info or classify_network_endpoint(
        response_url=url,
        surface=surface,
    )
    budget = _MAX_CAPTURED_NETWORK_PAYLOAD_BYTES
    if resolved_endpoint.get("type") in HIGH_VALUE_NETWORK_ENDPOINT_TYPES:
        budget *= HIGH_VALUE_NETWORK_PAYLOAD_BUDGET_MULTIPLIER
    return min(budget, _MAX_TOTAL_CAPTURED_NETWORK_PAYLOAD_BYTES)


__all__ = [
    "BrowserNetworkCapture",
    "BrowserNetworkCaptureSummary",
    "_MAX_CAPTURED_NETWORK_PAYLOADS",
    "_MAX_CAPTURED_NETWORK_PAYLOAD_BYTES",
    "_NETWORK_CAPTURE_QUEUE_SIZE",
    "_NETWORK_CAPTURE_WORKERS",
    "capture_browser_screenshot",
    "classify_network_endpoint",
    "coerce_content_length",
    "has_chunked_transfer_encoding",
    "read_network_payload_body",
    "should_capture_network_payload",
]
