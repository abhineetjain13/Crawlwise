from __future__ import annotations

import inspect

import pytest

from app.services.acquisition import acquirer


def test_requires_browser_first_has_no_hardcoded_tenant_or_platform_host_literals() -> None:
    source = inspect.getsource(acquirer._requires_browser_first)
    assert "workforcenow.adp.com" not in source
    assert "myjobs.adp.com" not in source
    assert "recruiting.adp.com" not in source
    assert "careers.clarkassociatesinc.biz" not in source


def test_requires_browser_first_uses_config_driven_domain_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        acquirer,
        "BROWSER_FIRST_DOMAINS",
        ["careers.clarkassociatesinc.biz"],
    )
    assert acquirer._requires_browser_first(
        "https://careers.clarkassociatesinc.biz/open-roles",
        "job_listing",
    )

