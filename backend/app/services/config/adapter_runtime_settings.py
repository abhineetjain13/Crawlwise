from __future__ import annotations

from pydantic import model_validator
from pydantic_settings import BaseSettings

from app.services.config._module_exports import make_getattr, module_dir
from app.services.config.runtime_settings import _settings_config


class AdapterRuntimeSettings(BaseSettings):
    """Typed env-backed runtime settings for adapter-specific heuristics."""

    model_config = _settings_config(env_prefix="ADAPTER_RUNTIME_")

    shopify_request_timeout_seconds: int = 6
    shopify_catalog_limit: int = 250
    shopify_max_products: int = 500
    shopify_max_option_axis_count: int = 3
    icims_pagination_timeout_seconds: int = 15
    icims_page_size: int = 100
    icims_max_offset: int = 1000
    icims_title_min_length: int = 3

    @model_validator(mode="after")
    def _validate(self) -> AdapterRuntimeSettings:
        if self.shopify_request_timeout_seconds <= 0:
            raise ValueError("shopify_request_timeout_seconds must be > 0")
        if self.shopify_catalog_limit <= 0:
            raise ValueError("shopify_catalog_limit must be > 0")
        if self.shopify_max_products <= 0:
            raise ValueError("shopify_max_products must be > 0")
        if self.shopify_max_option_axis_count <= 0:
            raise ValueError("shopify_max_option_axis_count must be > 0")
        if self.icims_pagination_timeout_seconds <= 0:
            raise ValueError("icims_pagination_timeout_seconds must be > 0")
        if self.icims_page_size <= 0:
            raise ValueError("icims_page_size must be > 0")
        if self.icims_max_offset <= 0:
            raise ValueError("icims_max_offset must be > 0")
        if self.icims_title_min_length <= 0:
            raise ValueError("icims_title_min_length must be > 0")
        if self.icims_max_offset < self.icims_page_size:
            raise ValueError("icims_max_offset must be >= icims_page_size")
        return self


adapter_runtime_settings = AdapterRuntimeSettings()
_EXPORTS = {
    name: name.lower()
    for name in (
        "SHOPIFY_REQUEST_TIMEOUT_SECONDS",
        "SHOPIFY_CATALOG_LIMIT",
        "SHOPIFY_MAX_PRODUCTS",
        "SHOPIFY_MAX_OPTION_AXIS_COUNT",
        "ICIMS_PAGINATION_TIMEOUT_SECONDS",
        "ICIMS_PAGE_SIZE",
        "ICIMS_MAX_OFFSET",
        "ICIMS_TITLE_MIN_LENGTH",
    )
}

__all__ = sorted([*(_EXPORTS.keys()), "AdapterRuntimeSettings", "adapter_runtime_settings"])

__getattr__ = make_getattr(
    attr_exports=_EXPORTS,
    settings_obj=adapter_runtime_settings,
)


def __dir__() -> list[str]:
    return module_dir(globals(), __all__)
