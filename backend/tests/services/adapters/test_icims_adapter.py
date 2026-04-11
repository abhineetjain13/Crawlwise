# Tests for iCIMS adapter.
from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
from app.services.adapters.icims import ICIMSAdapter


@pytest.mark.asyncio
async def test_icims_can_handle_real_family_url() -> None:
    adapter = ICIMSAdapter()
    assert await adapter.can_handle(
        "https://ehccareers-emory.icims.com/jobs/search?pr=0&searchRelation=keyword_all",
        "",
    )


@pytest.mark.asyncio
async def test_icims_extracts_listing_from_ajax_endpoint() -> None:
    adapter = ICIMSAdapter()
    html = """
    <html><body>
      <script>var listingUrl = "/ajax/joblisting/?num_items=100&offset=0";</script>
    </body></html>
    """
    response_text = """
    <div class="iCIMS_Job">
      <a href="/jobs/1234/software-engineer/job">Software Engineer</a>
      <div class="iCIMS_JobLocation">Atlanta, GA</div>
      <div class="iCIMS_JobCategory">Engineering</div>
      <div class="iCIMS_JobDate">Apr 6, 2026</div>
    </div>
    """
    with patch("app.services.adapters.base.BaseAdapter._request_text", return_value=response_text):
        result = await adapter.extract(
            "https://ehccareers-emory.icims.com/jobs/search?pr=0&searchRelation=keyword_all",
            html,
            "job_listing",
        )

    assert len(result.records) == 1
    assert result.records[0]["title"] == "Software Engineer"
    assert result.records[0]["location"] == "Atlanta, GA"
    assert result.records[0]["department"] == "Engineering"
    assert result.records[0]["posted_date"] == "Apr 6, 2026"
    assert result.records[0]["url"] == "https://ehccareers-emory.icims.com/jobs/1234/software-engineer/job"


@pytest.mark.asyncio
async def test_icims_follows_embedded_iframe_board() -> None:
    adapter = ICIMSAdapter()
    html = """
    <html><body>
      <iframe src="https://example.icims.com/jobs/search?pr=0&searchRelation=keyword_all&in_iframe=1"></iframe>
    </body></html>
    """
    response_text = """
    <html><body>
      <div class="iCIMS_JobsTable">
        <div class="row">
          <div class="col-xs-12 title">
            <a class="iCIMS_Anchor" href="/jobs/987/platform-engineer/job?in_iframe=1">
              <span class="sr-only field-label">Posting Job Title</span>
              <h3>Platform Engineer</h3>
            </a>
          </div>
          <div class="col-xs-12 description">Build critical platform systems.</div>
          <div class="col-xs-12 additionalFields">
            <dl class="iCIMS_JobHeaderGroup">
              <div class="iCIMS_JobHeaderTag">
                <dt class="iCIMS_JobHeaderField">Division</dt>
                <dd class="iCIMS_JobHeaderData"><span>Infrastructure</span></dd>
              </div>
              <div class="iCIMS_JobHeaderTag">
                <dt class="iCIMS_JobHeaderField">Campus Location</dt>
                <dd class="iCIMS_JobHeaderData"><span>Remote</span></dd>
              </div>
              <div class="iCIMS_JobHeaderTag">
                <dt class="iCIMS_JobHeaderField">Job Type</dt>
                <dd class="iCIMS_JobHeaderData"><span>Regular Full-Time</span></dd>
              </div>
              <div class="iCIMS_JobHeaderTag">
                <dt class="iCIMS_JobHeaderField">Job Number</dt>
                <dd class="iCIMS_JobHeaderData"><span>987</span></dd>
              </div>
              <div class="iCIMS_JobHeaderTag">
                <dt class="iCIMS_JobHeaderField">Job Category</dt>
                <dd class="iCIMS_JobHeaderData"><span>Engineering</span></dd>
              </div>
            </dl>
          </div>
        </div>
      </div>
    </body></html>
    """
    with patch("app.services.adapters.base.BaseAdapter._request_text", return_value=response_text):
        result = await adapter.extract("https://example.icims.com/jobs/search", html, "job_listing")

    assert len(result.records) == 1
    assert result.records[0]["title"] == "Platform Engineer"
    assert result.records[0]["location"] == "Remote"
    assert result.records[0]["company"] == "Infrastructure"
    assert result.records[0]["job_type"] == "Regular Full-Time"
    assert result.records[0]["job_id"] == "987"
    assert result.records[0]["department"] == "Engineering"
    assert result.records[0]["url"] == "https://example.icims.com/jobs/987/platform-engineer/job"


@pytest.mark.asyncio
async def test_icims_extracts_detail_record() -> None:
    adapter = ICIMSAdapter()
    html = """
    <html><body>
      <h1>Senior Data Engineer</h1>
      <div class="iCIMS_JobLocation">Remote</div>
      <div class="iCIMS_JobContent">Build ingestion systems.</div>
    </body></html>
    """
    result = await adapter.extract(
        "https://example.icims.com/jobs/123/senior-data-engineer/job",
        html,
        "job_detail",
    )

    assert len(result.records) == 1
    assert result.records[0]["title"] == "Senior Data Engineer"
    assert result.records[0]["location"] == "Remote"
    assert result.records[0]["description"] == "Build ingestion systems."


@pytest.mark.asyncio
async def test_icims_extracts_detail_record_from_embedded_iframe() -> None:
    adapter = ICIMSAdapter()
    shell_html = """
    <html><body>
      <div id="icims_iframe">
        <iframe src="/jobs/123/senior-data-engineer/job?in_iframe=1"></iframe>
      </div>
      <h1>Careers at Example Health</h1>
    </body></html>
    """
    response_text = """
    <html><body>
      <h1>Senior Data Engineer</h1>
      <div class="iCIMS_JobLocation">Remote</div>
      <div class="iCIMS_JobContent">Build ingestion systems.</div>
      <div class="iCIMS_JobHeaderTag">
        <dt class="iCIMS_JobHeaderField">Job Number</dt>
        <dd class="iCIMS_JobHeaderData"><span>123</span></dd>
      </div>
    </body></html>
    """

    with patch("app.services.adapters.base.BaseAdapter._request_text", return_value=response_text):
        result = await adapter.extract(
            "https://example.icims.com/jobs/123/senior-data-engineer/job",
            shell_html,
            "job_detail",
        )

    assert len(result.records) == 1
    assert result.records[0]["title"] == "Senior Data Engineer"
    assert result.records[0]["location"] == "Remote"
    assert result.records[0]["description"] == "Build ingestion systems."
    assert result.records[0]["job_id"] == "123"
