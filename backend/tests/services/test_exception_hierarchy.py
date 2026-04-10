from __future__ import annotations

from app.services.acquisition.acquirer import ProxyPoolExhausted
from app.services.exceptions import (
    AcquisitionError,
    CrawlerError,
    ProxyPoolExhaustedError,
)


def test_proxy_pool_exhausted_uses_unified_hierarchy():
    err = ProxyPoolExhausted("proxy pool exhausted")
    assert isinstance(err, ProxyPoolExhaustedError)
    assert isinstance(err, AcquisitionError)
    assert isinstance(err, CrawlerError)
