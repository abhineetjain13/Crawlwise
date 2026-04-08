from __future__ import annotations

from app.services._batch_runtime import RunControlSignal
from app.services.acquisition.acquirer import ProxyPoolExhausted
from app.services.exceptions import (
    AcquisitionError,
    CrawlerError,
    ProxyPoolExhaustedError,
    RunControlError,
)


def test_proxy_pool_exhausted_uses_unified_hierarchy():
    err = ProxyPoolExhausted("proxy pool exhausted")
    assert isinstance(err, ProxyPoolExhaustedError)
    assert isinstance(err, AcquisitionError)
    assert isinstance(err, CrawlerError)


def test_run_control_signal_uses_unified_hierarchy():
    err = RunControlSignal("pause")
    assert isinstance(err, RunControlError)
    assert isinstance(err, CrawlerError)
