from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.adapters.greenhouse import GreenhouseAdapter


@pytest.mark.asyncio
async def test_greenhouse_adapter_extracts_detail_from_public_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = GreenhouseAdapter()

    async def fake_request_json(url: str, *, timeout_seconds: float = 0, **_: object):
        assert "boards/greenhouse/jobs/7704699" in url
        assert timeout_seconds == 10
        return {
            "absolute_url": "https://job-boards.greenhouse.io/greenhouse/jobs/7704699?gh_jid=7704699",
            "title": "Manager, Engineering",
            "company_name": "Greenhouse",
            "location": {"name": "Ontario"},
            "first_published": "2026-04-09T10:05:53-04:00",
            "content": "<p>Lead the reporting and analytics engineering domain.</p><h2>What you’ll do</h2><ul><li>Lead and mentor engineers.</li></ul><h2>You should have</h2><ul><li>5+ years of engineering experience.</li></ul>",
        }

    monkeypatch.setattr(adapter, "_request_json", fake_request_json)

    result = await adapter.extract(
        "https://job-boards.greenhouse.io/greenhouse/jobs/7704699?gh_jid=7704699",
        "<html></html>",
        "job_detail",
    )

    assert len(result.records) == 1
    record = result.records[0]
    assert record["title"] == "Manager, Engineering"
    assert record["company"] == "Greenhouse"
    assert record["location"] == "Ontario"
    assert record["apply_url"] == "https://job-boards.greenhouse.io/greenhouse/jobs/7704699?gh_jid=7704699"
    assert "Lead and mentor engineers." in record["responsibilities"]
    assert "5+ years of engineering experience." in record["qualifications"]


def test_greenhouse_adapter_normalizes_numeric_pay_ranges_and_strong_sections() -> None:
    adapter = GreenhouseAdapter()

    salary = adapter._normalize_pay_range(
        {
            "currency_type": {"name": "USD"},
            "min_cents": 150000,
            "max_cents": Decimal("250000"),
            "title": "yearly",
        }
    )
    sections = adapter._extract_sections_from_html(
        """
        <div>
          <strong>What you'll do</strong>
          <p>Build systems.</p>
          <strong>You should have</strong>
          <p>5+ years.</p>
        </div>
        """
    )

    assert salary == "USD 1500 - 2500 yearly"
    assert sections["responsibilities"] == "Build systems."
    assert sections["qualifications"] == "5+ years."
