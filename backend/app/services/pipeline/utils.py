"""Utility functions for pipeline processing."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bs4 import BeautifulSoup


def _elapsed_ms(started_at: float) -> int:
    """Calculate elapsed milliseconds from a start time."""
    return max(0, int(round((time.perf_counter() - started_at) * 1000)))


def _compact_dict(payload: dict) -> dict:
    """Remove None, empty string, empty list, and empty dict values."""
    return {
        key: value for key, value in payload.items() if value not in (None, "", [], {})
    }


# ---------------------------------------------------------------------------
# Shared HTML parsing — CPU-bound, always offloaded from the async event loop
# ---------------------------------------------------------------------------


def _parse_html_sync(html: str) -> "BeautifulSoup":
    """Parse HTML into a BeautifulSoup object (synchronous, CPU-bound).

    This is the **single** canonical HTML parse function for the pipeline.
    It must never be called directly from an ``async`` function — use
    :func:`parse_html` instead.
    """
    from bs4 import BeautifulSoup as _BS

    return _BS(html, "html.parser")


async def parse_html(html: str) -> "BeautifulSoup":
    """Parse HTML into a BeautifulSoup object, offloaded to a thread.

    All pipeline code that needs a parsed DOM should call this function
    rather than constructing ``BeautifulSoup`` directly.  Offloading the
    CPU-heavy parse to ``asyncio.to_thread`` prevents event-loop starvation
    under concurrent load.
    """
    return await asyncio.to_thread(_parse_html_sync, html)
