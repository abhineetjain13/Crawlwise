# Adapter registry — resolves URL/HTML to the right platform adapter.
from __future__ import annotations

import logging

from app.services.adapters.amazon import AmazonAdapter
from app.services.adapters.adp import ADPAdapter
from app.services.adapters.base import AdapterResult, BaseAdapter
from app.services.adapters.ebay import EbayAdapter
from app.services.adapters.greenhouse import GreenhouseAdapter
from app.services.adapters.icims import ICIMSAdapter
from app.services.adapters.indeed import IndeedAdapter
from app.services.adapters.jibe import JibeAdapter
from app.services.adapters.linkedin import LinkedInAdapter
from app.services.adapters.oracle_hcm import OracleHCMAdapter
from app.services.adapters.paycom import PaycomAdapter
from app.services.adapters.remotive import RemotiveAdapter
from app.services.adapters.saashr import SaaSHRAdapter
from app.services.adapters.shopify import ShopifyAdapter
from app.services.adapters.walmart import WalmartAdapter

# Order matters: domain-matched adapters first, signal-based (Shopify) last.
_ADAPTERS: list[BaseAdapter] = [
    AmazonAdapter(),
    WalmartAdapter(),
    EbayAdapter(),
    ADPAdapter(),
    ICIMSAdapter(),
    OracleHCMAdapter(),
    PaycomAdapter(),
    SaaSHRAdapter(),
    JibeAdapter(),
    IndeedAdapter(),
    LinkedInAdapter(),
    GreenhouseAdapter(),
    RemotiveAdapter(),
    ShopifyAdapter(),  # last — uses HTML signals, not domain matching
]

logger = logging.getLogger(__name__)


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


async def try_blocked_adapter_recovery(
    url: str,
    surface: str,
    *,
    proxy_list: list[str] | None = None,
) -> AdapterResult | None:
    """Attempt limited recovery for blocked pages using public platform endpoints.

    This is intentionally narrow. It does not try to defeat anti-bot pages in
    general; it only uses known public data endpoints when a platform supports
    them directly.
    """
    if surface not in {"ecommerce_listing", "ecommerce_detail", "job_listing", "job_detail"}:
        return None

    shopify = ShopifyAdapter()
    jibe = JibeAdapter()
    oracle_hcm = OracleHCMAdapter()
    proxies = [proxy.strip() for proxy in (proxy_list or []) if proxy and proxy.strip()] or [None]
    for proxy in proxies:
        try:
            records = await oracle_hcm.try_public_endpoint(url, "", surface, proxy=proxy)
        except Exception as exc:
            logger.debug("Oracle HCM recovery proxy failed for %s via %s: %s", url, proxy or "direct", exc)
            records = []
        if records:
            return AdapterResult(
                records=records,
                source_type="oracle_hcm_adapter_recovery",
                adapter_name=oracle_hcm.name,
            )
        try:
            records = await jibe.try_public_endpoint(url, "", surface, proxy=proxy)
        except Exception as exc:
            logger.debug("Jibe recovery proxy failed for %s via %s: %s", url, proxy or "direct", exc)
            records = []
        if records:
            return AdapterResult(
                records=records,
                source_type="jibe_adapter_recovery",
                adapter_name=jibe.name,
            )
        try:
            records = await shopify.try_public_endpoint(url, surface, proxy=proxy)
        except Exception as exc:
            logger.debug("Shopify recovery proxy failed for %s via %s: %s", url, proxy or "direct", exc)
            continue
        if not records:
            continue
        return AdapterResult(
            records=records,
            source_type="shopify_adapter_recovery",
            adapter_name=shopify.name,
        )
    return None
