# Adapter registry — resolves URL/HTML to the right platform adapter.
from __future__ import annotations

from functools import lru_cache
from importlib import import_module
import logging

from app.services.adapters.base import AdapterResult, BaseAdapter
from app.services.acquisition_plan import AcquisitionPlan
from app.services.platform_policy import configured_adapter_names, is_job_platform_signal

logger = logging.getLogger(__name__)

_ADAPTER_FACTORIES: dict[str, tuple[str, str]] = {
    "amazon": ("app.services.adapters.amazon", "AmazonAdapter"),
    "belk": ("app.services.adapters.belk", "BelkAdapter"),
    "walmart": ("app.services.adapters.walmart", "WalmartAdapter"),
    "ebay": ("app.services.adapters.ebay", "EbayAdapter"),
    "adp": ("app.services.adapters.adp", "ADPAdapter"),
    "icims": ("app.services.adapters.icims", "ICIMSAdapter"),
    "oracle_hcm": ("app.services.adapters.oracle_hcm", "OracleHCMAdapter"),
    "paycom": ("app.services.adapters.paycom", "PaycomAdapter"),
    "ultipro_ukg": ("app.services.adapters.ultipro", "UltiProAdapter"),
    "workday": ("app.services.adapters.workday", "WorkdayAdapter"),
    "saashr": ("app.services.adapters.saashr", "SaaSHRAdapter"),
    "jibe": ("app.services.adapters.jibe", "JibeAdapter"),
    "indeed": ("app.services.adapters.indeed", "IndeedAdapter"),
    "linkedin": ("app.services.adapters.linkedin", "LinkedInAdapter"),
    "myntra": ("app.services.adapters.myntra", "MyntraAdapter"),
    "nike": ("app.services.adapters.nike", "NikeAdapter"),
    "greenhouse": ("app.services.adapters.greenhouse", "GreenhouseAdapter"),
    "remotive": ("app.services.adapters.remotive", "RemotiveAdapter"),
    "remoteok": ("app.services.adapters.remoteok", "RemoteOkAdapter"),
    "shopify": ("app.services.adapters.shopify", "ShopifyAdapter"),
}


def available_adapter_names() -> tuple[str, ...]:
    return tuple(sorted(_ADAPTER_FACTORIES))


def _build_adapter(adapter_name: str) -> BaseAdapter | None:
    target = _ADAPTER_FACTORIES.get(adapter_name)
    if target is None:
        return None
    module_name, class_name = target
    module = import_module(module_name)
    factory = getattr(module, class_name)
    return factory()


@lru_cache(maxsize=1)
def registered_adapters() -> tuple[BaseAdapter, ...]:
    adapters: list[BaseAdapter] = []
    unknown: list[str] = []
    for adapter_name in configured_adapter_names():
        adapter = _build_adapter(adapter_name)
        if adapter is None:
            unknown.append(adapter_name)
            continue
        adapters.append(adapter)

    if unknown:
        logger.warning(
            "Skipping unknown adapter names from registry config: %s", sorted(unknown)
        )

    # Signal-based Shopify should remain last even if config order drifts.
    adapters.sort(key=lambda adapter: adapter.name == "shopify")
    return tuple(adapters)


async def resolve_adapter(url: str, html: str) -> BaseAdapter | None:
    """Return the first adapter that can handle this URL/HTML, or None."""
    for adapter in registered_adapters():
        if await adapter.can_handle(url, html):
            return adapter
    return None


async def normalize_adapter_acquisition_url(url: str | None) -> str | None:
    requested_url = str(url or "").strip()
    if not requested_url:
        return url
    adapter = await resolve_adapter(requested_url, "")
    if adapter is None:
        return url
    return adapter.normalize_acquisition_url(url)


async def run_adapter(
    url: str, html: str, surface: str | None
) -> AdapterResult | None:
    """Convenience: resolve and run adapter in one call."""
    adapter = await resolve_adapter(url, html)
    if adapter is None:
        return None
    normalized_surface = str(surface or "")
    if not _surface_allows_adapter(adapter, normalized_surface):
        return None
    try:
        return await adapter.extract(url, html, normalized_surface)
    except Exception:
        logger.warning(
            "Adapter %s failed open for %s surface=%s",
            adapter.name,
            url,
            surface,
            exc_info=True,
        )
        return None


def _surface_allows_adapter(adapter: BaseAdapter, surface: str | None) -> bool:
    normalized_surface = str(surface or "").strip().lower()
    if not normalized_surface:
        return True
    is_job_adapter = is_job_platform_signal(
        platform_family=adapter.platform_family,
        adapter_hint=adapter.name,
    )
    if normalized_surface.startswith("job_"):
        return is_job_adapter
    return not is_job_adapter


async def try_blocked_adapter_recovery(
    url: str,
    plan: AcquisitionPlan,
    *,
    proxy_list: list[str] | None = None,
) -> AdapterResult | None:
    """Attempt limited recovery for blocked pages using public platform endpoints.

    This is intentionally narrow. It does not try to defeat anti-bot pages in
    general; it only uses known public data endpoints when a platform supports
    them directly.
    """
    if not plan.adapter_recovery_enabled:
        return None

    recovery_adapters = [
        adapter
        for adapter in registered_adapters()
        if hasattr(adapter, "try_public_endpoint")
    ]
    proxies = [proxy.strip() for proxy in (proxy_list or []) if proxy and proxy.strip()]
    proxy_attempts = [*proxies] if proxies else [None]
    for proxy in proxy_attempts:
        for adapter in recovery_adapters:
            try:
                records = await adapter.try_public_endpoint(
                    url,
                    html="",
                    surface=plan.surface,
                    proxy=proxy,
                )
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
            return adapter._result(
                records,
                source_type=f"{adapter.name}_adapter_recovery",
            )
    return None
