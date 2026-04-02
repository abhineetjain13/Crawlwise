# Adapter registry — resolves URL/HTML to the right platform adapter.
from __future__ import annotations

from urllib.parse import urlparse

from app.services.adapters.amazon import AmazonAdapter
from app.services.adapters.base import AdapterResult, BaseAdapter
from app.services.adapters.ebay import EbayAdapter
from app.services.adapters.indeed import IndeedAdapter
from app.services.adapters.linkedin import LinkedInAdapter
from app.services.adapters.shopify import ShopifyAdapter
from app.services.adapters.walmart import WalmartAdapter

# Order matters: domain-matched adapters first, signal-based (Shopify) last.
_ADAPTERS: list[BaseAdapter] = [
    AmazonAdapter(),
    WalmartAdapter(),
    EbayAdapter(),
    IndeedAdapter(),
    LinkedInAdapter(),
    ShopifyAdapter(),  # last — uses HTML signals, not domain matching
]


async def resolve_adapter(url: str, html: str) -> BaseAdapter | None:
    """Return the first adapter that can handle this URL/HTML, or None."""
    for adapter in _ADAPTERS:
        if await adapter.can_handle(url, html):
            return adapter
    return None


async def run_adapter(url: str, html: str, surface: str) -> AdapterResult | None:
    """Convenience: resolve and run adapter in one call."""
    adapter = await resolve_adapter(url, html)
    if adapter is None:
        return None
    return await adapter.extract(url, html, surface)
