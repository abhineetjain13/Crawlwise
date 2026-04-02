# Deterministic HTTP acquisition client with optional proxy support.
from __future__ import annotations

from curl_cffi import requests


async def fetch_html(url: str, proxy: str | None = None) -> str:
    """Fetch HTML via curl_cffi with Chrome TLS impersonation.

    Args:
        url: Target URL.
        proxy: Optional proxy URL (e.g. "http://user:pass@host:port").
    """
    kwargs: dict = {"impersonate": "chrome110", "timeout": 20}
    if proxy:
        kwargs["proxies"] = {"http": proxy, "https": proxy}
    response = requests.get(url, **kwargs)
    response.raise_for_status()
    return response.text
