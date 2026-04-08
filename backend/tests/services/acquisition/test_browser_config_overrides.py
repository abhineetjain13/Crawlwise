# Integration tests for per-domain listing readiness overrides
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.services.config.selectors import LISTING_READINESS_OVERRIDES


class FakePage:
    """Mock page object for testing listing readiness."""
    
    def __init__(self, url: str, selector_counts: dict[str, int]):
        self.url = url
        self._selector_counts = selector_counts
        self.timeout_calls: list[int] = []
    
    def locator(self, selector: str):
        count = self._selector_counts.get(selector, 0)
        return FakeLocator(count)
    
    async def wait_for_timeout(self, value: int):
        self.timeout_calls.append(value)
    
    async def evaluate(self, _script: str):
        return {
            "link_count": 10,
            "cardish_count": 5,
            "text_length": 1000,
            "html_length": 5000,
            "loading": False,
        }


class FakeLocator:
    """Mock locator for selector counting."""
    
    def __init__(self, count: int):
        self._count = count
    
    async def count(self):
        return self._count


@pytest.mark.asyncio
async def test_oracle_hcm_override_uses_configured_selectors(monkeypatch):
    """
    Feature: extraction-pipeline-improvements, Property 11: Configuration-Driven Selector Lookup
    
    Integration test for Oracle HCM override (Task 6.1).
    Validates: Requirements 5.3, 5.4, 5.5
    
    Verifies that Oracle HCM listing pages use the configured selectors from
    LISTING_READINESS_OVERRIDES instead of hardcoded domain checks.
    """
    from app.services.acquisition.browser_client import _wait_for_listing_readiness
    
    # Oracle HCM URL
    oracle_url = "https://candidateexperience.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/requisitions"
    
    # Verify configuration exists
    assert "candidateexperience.oraclecloud.com" in LISTING_READINESS_OVERRIDES
    oracle_config = LISTING_READINESS_OVERRIDES["candidateexperience.oraclecloud.com"]
    assert "a[href*='/job/']" in oracle_config["selectors"]
    assert oracle_config["max_wait_ms"] == 25000
    
    # Create page with Oracle HCM selector matching
    page = FakePage(
        url=oracle_url,
        selector_counts={
            "a[href*='/job/']": 8,  # Oracle-specific selector from config
        }
    )
    
    # Mock constants
    monkeypatch.setattr("app.services.acquisition.browser_client.LISTING_READINESS_POLL_MS", 100)
    monkeypatch.setattr("app.services.acquisition.browser_client.LISTING_READINESS_MAX_WAIT_MS", 5000)
    monkeypatch.setattr("app.services.acquisition.browser_client.LISTING_MIN_ITEMS", 5)
    
    # Call the function
    result = await _wait_for_listing_readiness(page, "job_listing")
    
    # Verify it used the configured selector
    assert result is not None
    assert result["ready"] is True
    assert result["selector"] == "a[href*='/job/']"
    assert result["count"] == 8


@pytest.mark.asyncio
async def test_adp_override_uses_configured_selectors(monkeypatch):
    """
    Integration test for ADP override (Task 6.2).
    Validates: Requirements 5.2, 5.3
    
    Verifies that ADP listing pages use the configured selectors from
    LISTING_READINESS_OVERRIDES instead of hardcoded domain checks.
    """
    from app.services.acquisition.browser_client import _wait_for_listing_readiness
    
    # ADP URL
    adp_url = "https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html"
    
    # Verify configuration exists
    assert "workforcenow.adp.com" in LISTING_READINESS_OVERRIDES
    adp_config = LISTING_READINESS_OVERRIDES["workforcenow.adp.com"]
    assert ".current-openings-item" in adp_config["selectors"]
    assert "[id^='lblTitle_']" in adp_config["selectors"]
    assert adp_config["max_wait_ms"] == 20000
    
    # Create page with ADP selector matching
    page = FakePage(
        url=adp_url,
        selector_counts={
            ".current-openings-item": 12,  # ADP-specific selector from config
            "[id^='lblTitle_']": 12,
        }
    )
    
    # Mock constants
    monkeypatch.setattr("app.services.acquisition.browser_client.LISTING_READINESS_POLL_MS", 100)
    monkeypatch.setattr("app.services.acquisition.browser_client.LISTING_READINESS_MAX_WAIT_MS", 5000)
    monkeypatch.setattr("app.services.acquisition.browser_client.LISTING_MIN_ITEMS", 5)
    
    # Call the function
    result = await _wait_for_listing_readiness(page, "job_listing")
    
    # Verify it used the configured selector
    assert result is not None
    assert result["ready"] is True
    assert result["selector"] == ".current-openings-item"
    assert result["count"] == 12


@pytest.mark.asyncio
async def test_generic_listing_page_without_override(monkeypatch):
    """
    Integration test for generic listing page (not in overrides).
    
    Verifies that listing pages not in LISTING_READINESS_OVERRIDES use
    default selectors without any domain-specific configuration.
    """
    from app.services.acquisition.browser_client import _wait_for_listing_readiness
    
    # Generic job listing URL (not in overrides)
    generic_url = "https://example.com/careers"
    
    # Verify this domain is NOT in overrides
    assert "example.com" not in LISTING_READINESS_OVERRIDES
    
    # Create page with generic job card selector
    page = FakePage(
        url=generic_url,
        selector_counts={
            ".job-card": 15,  # Generic selector
        }
    )
    
    # Mock constants and default selectors
    monkeypatch.setattr("app.services.acquisition.browser_client.LISTING_READINESS_POLL_MS", 100)
    monkeypatch.setattr("app.services.acquisition.browser_client.LISTING_READINESS_MAX_WAIT_MS", 5000)
    monkeypatch.setattr("app.services.acquisition.browser_client.LISTING_MIN_ITEMS", 5)
    monkeypatch.setattr("app.services.acquisition.browser_client.CARD_SELECTORS_JOBS", [".job-card"])
    
    # Call the function
    result = await _wait_for_listing_readiness(page, "job_listing")
    
    # Verify it used the default selector
    assert result is not None
    assert result["ready"] is True
    assert result["selector"] == ".job-card"
    assert result["count"] == 15


@pytest.mark.asyncio
async def test_oracle_hcm_override_applies_max_wait_ms(monkeypatch):
    """
    Verifies that Oracle HCM override configuration includes the correct max_wait_ms value.
    Validates: Requirement 5.5
    
    This test verifies that the override configuration is properly defined with
    the correct max_wait_ms value that will be used by _wait_for_listing_readiness.
    """
    # Verify the override configuration has the correct max_wait_ms
    oracle_config = LISTING_READINESS_OVERRIDES["candidateexperience.oraclecloud.com"]
    assert oracle_config["max_wait_ms"] == 25000
    
    # Verify it's higher than the default
    from app.services.acquisition.browser_client import LISTING_READINESS_MAX_WAIT_MS
    assert oracle_config["max_wait_ms"] > LISTING_READINESS_MAX_WAIT_MS


@pytest.mark.asyncio
async def test_adp_override_applies_max_wait_ms(monkeypatch):
    """
    Verifies that ADP override configuration includes the correct max_wait_ms value.
    Validates: Requirement 5.5
    
    This test verifies that the override configuration is properly defined with
    the correct max_wait_ms value that will be used by _wait_for_listing_readiness.
    """
    # Verify the override configuration has the correct max_wait_ms
    adp_config = LISTING_READINESS_OVERRIDES["workforcenow.adp.com"]
    assert adp_config["max_wait_ms"] == 20000
    
    # Verify it's higher than the default
    from app.services.acquisition.browser_client import LISTING_READINESS_MAX_WAIT_MS
    assert adp_config["max_wait_ms"] > LISTING_READINESS_MAX_WAIT_MS
