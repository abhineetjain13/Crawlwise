# Adapter registry — resolves URL/HTML to the right platform adapter.
from __future__ import annotations

from functools import lru_cache
import logging

from app.services.adapters.adp import ADPAdapter
from app.services.adapters.amazon import AmazonAdapter
from app.services.adapters.base import AdapterResult, BaseAdapter
from app.services.adapters.ebay import EbayAdapter
from app.services.adapters.greenhouse import GreenhouseAdapter
from app.services.adapters.icims import ICIMSAdapter
from app.services.adapters.indeed import IndeedAdapter
from app.services.adapters.jibe import JibeAdapter
from app.services.adapters.linkedin import LinkedInAdapter
from app.services.adapters.oracle_hcm import OracleHCMAdapter
from app.services.adapters.paycom import PaycomAdapter
from app.services.adapters.remoteok import RemoteOkAdapter
from app.services.adapters.remotive import RemotiveAdapter
from app.services.adapters.saashr import SaaSHRAdapter
from app.services.adapters.shopify import ShopifyAdapter
from app.services.adapters.walmart import WalmartAdapter
from app.services.config.platform_registry import configured_adapter_names

logger = logging.getLogger(__name__)

_ADAPTER_FACTORIES: dict[str, type[BaseAdapter]] = {
    "amazon": AmazonAdapter,
    "walmart": WalmartAdapter,
    "ebay": EbayAdapter,
    "adp": ADPAdapter,
    "icims": ICIMSAdapter,
    "oracle_hcm": OracleHCMAdapter,
    "paycom": PaycomAdapter,
    "saashr": SaaSHRAdapter,
    "jibe": JibeAdapter,
    "indeed": IndeedAdapter,
    "linkedin": LinkedInAdapter,
    "greenhouse": GreenhouseAdapter,
    "remotive": RemotiveAdapter,
    "remoteok": RemoteOkAdapter,
    "shopify": ShopifyAdapter,
}
@lru_cache(maxsize=1)
def registered_adapters() -> tuple[BaseAdapter, ...]:
    adapters: list[BaseAdapter] = []
    unknown: list[str] = []
    for adapter_name in configured_adapter_names():
        factory = _ADAPTER_FACTORIES.get(adapter_name)
        if factory is None:
            unknown.append(adapter_name)
            continue
        adapters.append(factory())

    if unknown:
        logger.warning("Skipping unknown adapter names from registry config: %s", sorted(unknown))

    # Signal-based Shopify should remain last even if config order drifts.
    adapters.sort(key=lambda adapter: adapter.name == "shopify")
    return tuple(adapters)


async def resolve_adapter(url: str, html: str) -> BaseAdapter | None:
    """Return the first adapter that can handle this URL/HTML, or None."""
    for adapter in registered_adapters():
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

    recovery_adapters = [
        adapter
        for adapter in registered_adapters()
        if hasattr(adapter, "try_public_endpoint")
    ]
    proxies = [proxy.strip() for proxy in (proxy_list or []) if proxy and proxy.strip()] or [None]
    for proxy in proxies:
        for adapter in recovery_adapters:
            try:
                if adapter.name == "shopify":
                    records = await adapter.try_public_endpoint(url, surface, proxy=proxy)
                else:
                    records = await adapter.try_public_endpoint(url, "", surface, proxy=proxy)
            except (RuntimeError, OSError, ValueError, TypeError) as exc:
                logger.debug(
                    "%s recovery proxy failed for %s via %s: %s",
                    adapter.name,
                    url,
                    proxy or "direct",
                    exc,
                )
                continue
            if not records:
                continue
            return AdapterResult(
                records=records,
                source_type=f"{adapter.name}_adapter_recovery",
                adapter_name=adapter.name,
            )
    return None
