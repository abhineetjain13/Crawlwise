from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

from app.services.config.runtime_settings import crawler_runtime_settings

logger = logging.getLogger(__name__)

_SOCKS_VERSION = 5
_SOCKS_CMD_CONNECT = 1
_SOCKS_AUTH_NONE = 0
_SOCKS_AUTH_USERPASS = 2
_SOCKS_AUTH_NO_ACCEPTABLE = 0xFF
_SOCKS_ATYP_IPV4 = 1
_SOCKS_ATYP_DOMAIN = 3
_SOCKS_ATYP_IPV6 = 4
_SOCKS_REPLY_GENERAL_FAILURE = 1
_SOCKS_REPLY_COMMAND_NOT_SUPPORTED = 7
_BRIDGE_COUNTERS = {
    "opened": 0,
    "closed": 0,
    "failures": 0,
}


class _ClientNotifiedSocksError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Socks5UpstreamProxy:
    scheme: str
    host: str
    port: int
    username: str
    password: str


def parse_socks5_upstream_proxy(proxy_url: str | None) -> Socks5UpstreamProxy | None:
    raw_proxy = str(proxy_url or "").strip()
    if not raw_proxy:
        return None
    parsed = urlparse(raw_proxy)
    scheme = str(parsed.scheme or "").strip().lower()
    if scheme not in {"socks5", "socks5h"}:
        return None
    if not parsed.hostname or parsed.port is None:
        return None
    username = unquote(str(parsed.username or ""))
    password = unquote(str(parsed.password or ""))
    if not username and not password:
        return None
    return Socks5UpstreamProxy(
        scheme=scheme,
        host=str(parsed.hostname),
        port=int(parsed.port),
        username=username,
        password=password,
    )


class Socks5AuthBridge:
    def __init__(self, upstream: Socks5UpstreamProxy) -> None:
        self.upstream = upstream
        self._server: asyncio.AbstractServer | None = None
        self._server_url: str | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self._start_lock = asyncio.Lock()

    async def start(self) -> str:
        async with self._start_lock:
            if self._server is not None and self._server_url is not None:
                return self._server_url
            server = await asyncio.start_server(
                self._handle_client,
                host="127.0.0.1",
                port=0,
            )
            sockets = list(server.sockets or [])
            if not sockets:
                server.close()
                await server.wait_closed()
                _BRIDGE_COUNTERS["failures"] += 1
                raise RuntimeError("SOCKS5 auth bridge failed to bind a local socket")
            port = int(sockets[0].getsockname()[1])
            self._server = server
            self._server_url = f"socks5://127.0.0.1:{port}"
            _BRIDGE_COUNTERS["opened"] += 1
            return self._server_url

    async def close(self) -> None:
        server = self._server
        self._server = None
        self._server_url = None
        if server is not None:
            server.close()
            await server.wait_closed()
            _BRIDGE_COUNTERS["closed"] += 1
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._tasks.add(task)
        upstream_reader: asyncio.StreamReader | None = None
        upstream_writer: asyncio.StreamWriter | None = None
        try:
            request = await asyncio.wait_for(
                _read_client_request(reader, writer),
                timeout=float(
                    crawler_runtime_settings.browser_proxy_bridge_first_byte_timeout_seconds
                ),
            )
            upstream_reader, upstream_writer = await asyncio.wait_for(
                asyncio.open_connection(
                    self.upstream.host,
                    self.upstream.port,
                ),
                timeout=float(
                    crawler_runtime_settings.browser_proxy_bridge_connect_timeout_seconds
                ),
            )
            await asyncio.wait_for(
                _authenticate_upstream(
                    upstream_reader,
                    upstream_writer,
                    upstream=self.upstream,
                ),
                timeout=float(
                    crawler_runtime_settings.browser_proxy_bridge_auth_timeout_seconds
                ),
            )
            upstream_writer.write(request.raw_request)
            await upstream_writer.drain()
            response = await asyncio.wait_for(
                _read_socks5_response(upstream_reader),
                timeout=float(
                    crawler_runtime_settings.browser_proxy_bridge_first_byte_timeout_seconds
                ),
            )
            writer.write(response)
            await writer.drain()
            if response[1] != 0:
                return
            await asyncio.gather(
                _relay_stream(reader, upstream_writer),
                _relay_stream(upstream_reader, writer),
            )
        except asyncio.CancelledError:
            raise
        except _ClientNotifiedSocksError:
            _BRIDGE_COUNTERS["failures"] += 1
            logger.debug("SOCKS5 auth bridge rejected client request", exc_info=True)
        except Exception:
            _BRIDGE_COUNTERS["failures"] += 1
            logger.debug("SOCKS5 auth bridge request failed", exc_info=True)
            with contextlib.suppress(Exception):
                writer.write(_failure_response(_SOCKS_REPLY_GENERAL_FAILURE))
                await writer.drain()
        finally:
            if task is not None:
                self._tasks.discard(task)
            if upstream_writer is not None:
                upstream_writer.close()
                with contextlib.suppress(Exception):
                    await upstream_writer.wait_closed()
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()


@dataclass(frozen=True, slots=True)
class _Socks5ConnectRequest:
    raw_request: bytes


async def _read_client_request(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> _Socks5ConnectRequest:
    header = await reader.readexactly(2)
    version, method_count = header[0], header[1]
    if version != _SOCKS_VERSION:
        raise ValueError(f"Unsupported SOCKS version: {version}")
    methods = await reader.readexactly(method_count)
    if _SOCKS_AUTH_NONE not in methods:
        writer.write(bytes([_SOCKS_VERSION, _SOCKS_AUTH_NO_ACCEPTABLE]))
        await writer.drain()
        raise _ClientNotifiedSocksError("Browser SOCKS client did not offer no-auth method")
    writer.write(bytes([_SOCKS_VERSION, _SOCKS_AUTH_NONE]))
    await writer.drain()
    request_header = await reader.readexactly(4)
    version, command, _reserved, address_type = request_header
    if version != _SOCKS_VERSION:
        raise ValueError(f"Unsupported SOCKS request version: {version}")
    if command != _SOCKS_CMD_CONNECT:
        writer.write(_failure_response(_SOCKS_REPLY_COMMAND_NOT_SUPPORTED))
        await writer.drain()
        raise _ClientNotifiedSocksError(f"Unsupported SOCKS command: {command}")
    address_bytes = await _read_address_bytes(reader, address_type)
    port_bytes = await reader.readexactly(2)
    return _Socks5ConnectRequest(
        raw_request=request_header + address_bytes + port_bytes
    )


async def _authenticate_upstream(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    *,
    upstream: Socks5UpstreamProxy,
) -> None:
    if upstream.username or upstream.password:
        writer.write(bytes([_SOCKS_VERSION, 1, _SOCKS_AUTH_USERPASS]))
    else:
        writer.write(bytes([_SOCKS_VERSION, 1, _SOCKS_AUTH_NONE]))
    await writer.drain()

    response = await reader.readexactly(2)
    if response[0] != _SOCKS_VERSION:
        raise ValueError(f"Unexpected upstream SOCKS version: {response[0]}")
    method = response[1]
    if method == _SOCKS_AUTH_NONE:
        return
    if method != _SOCKS_AUTH_USERPASS:
        raise ValueError(f"Unsupported upstream SOCKS auth method: {method}")

    username = upstream.username.encode("utf-8")
    password = upstream.password.encode("utf-8")
    if len(username) > 255 or len(password) > 255:
        raise ValueError("SOCKS5 proxy username/password too long")
    writer.write(
        bytes([1, len(username)])
        + username
        + bytes([len(password)])
        + password
    )
    await writer.drain()
    auth_response = await reader.readexactly(2)
    if auth_response[1] != 0:
        raise ValueError("SOCKS5 upstream authentication failed")


async def _read_socks5_response(reader: asyncio.StreamReader) -> bytes:
    header = await reader.readexactly(4)
    _version, _reply, _reserved, address_type = header
    if _version != _SOCKS_VERSION:
        raise ValueError(f"Unexpected upstream SOCKS response version: {_version}")
    address_bytes = await _read_address_bytes(reader, address_type)
    port_bytes = await reader.readexactly(2)
    return header + address_bytes + port_bytes


async def _read_address_bytes(
    reader: asyncio.StreamReader,
    address_type: int,
) -> bytes:
    if address_type == _SOCKS_ATYP_IPV4:
        return await reader.readexactly(4)
    if address_type == _SOCKS_ATYP_IPV6:
        return await reader.readexactly(16)
    if address_type == _SOCKS_ATYP_DOMAIN:
        length_byte = await reader.readexactly(1)
        length = length_byte[0]
        return length_byte + await reader.readexactly(length)
    raise ValueError(f"Unsupported SOCKS address type: {address_type}")


async def _relay_stream(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    try:
        while True:
            chunk = await reader.read(65536)
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()
    finally:
        with contextlib.suppress(Exception):
            writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()


def _failure_response(reply_code: int) -> bytes:
    return bytes(
        [
            _SOCKS_VERSION,
            reply_code,
            0,
            _SOCKS_ATYP_IPV4,
            0,
            0,
            0,
            0,
            0,
            0,
        ]
    )


def bridge_counters() -> dict[str, int]:
    return dict(_BRIDGE_COUNTERS)


def reset_bridge_counters() -> None:
    for key in list(_BRIDGE_COUNTERS):
        _BRIDGE_COUNTERS[key] = 0
