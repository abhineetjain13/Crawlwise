# Tests for ADP adapter.
from __future__ import annotations

import pytest
from app.services.adapters.adp import ADPAdapter


@pytest.mark.asyncio
async def test_adp_can_handle_real_family_url() -> None:
    adapter = ADPAdapter()
    assert await adapter.can_handle(
        "https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html?cid=14fa7571-bfac-427f-aa18-9488391d4c5e",
        "",
    )


@pytest.mark.asyncio
async def test_adp_extracts_listing_rows() -> None:
    adapter = ADPAdapter()
    html = """
    <html><body>
      <div class="current-openings-item" id="job_item_view_main_div_9202663521477_1">
        <div class="current-openings-details">
          <sdf-link id="lblTitle_9202663521477_1">MEDICAL ASSISTANT</sdf-link>
          <label class="current-opening-location-item"><span>MIDTOWN MEDICAL, New York, NY, US</span></label>
          <span class="current-opening-post-date">5 days ago</span>
        </div>
        <div class="current-openings-actions">
          <div id="job_item_reff_chevron-right9202663521477_1"></div>
        </div>
      </div>
    </body></html>
    """
    result = await adapter.extract(
        "https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html?cid=tenant&ccId=19000101_000001&type=MP&lang=en_US&selectedMenuKey=CurrentOpenings",
        html,
        "job_listing",
    )

    assert len(result.records) == 1
    assert result.records[0]["title"] == "MEDICAL ASSISTANT"
    assert result.records[0]["location"] == "MIDTOWN MEDICAL, New York, NY, US"
    assert result.records[0]["posted_date"] == "5 days ago"
    assert result.records[0]["job_id"] == "9202663521477_1"
    assert result.records[0]["url"].endswith("&jobId=9202663521477_1#9202663521477_1")
    assert result.records[0]["apply_url"] == result.records[0]["url"]


@pytest.mark.asyncio
async def test_adp_extracts_detail_record() -> None:
    adapter = ADPAdapter()
    html = """
    <html><body>
      <h1>MEDICAL ASSISTANT</h1>
      <label class="current-opening-location-item"><span>MIDTOWN MEDICAL, New York, NY, US</span></label>
      <span class="current-opening-post-date">5 days ago</span>
      <div>
        Requisition ID: 1393
        Apply
        Salary Range: $51,000.00 To $60,000.00 Annually
        Health Center Inc. is a NYC based healthcare organization with ambulatory care facilities.
        Duties and responsibilities:
        Reviews patient schedule.
        BackApply
      </div>
    </body></html>
    """
    result = await adapter.extract(
        "https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html?cid=tenant&ccId=19000101_000001&type=MP&lang=en_US&selectedMenuKey=CurrentOpenings&jobId=582883",
        html,
        "job_detail",
    )

    assert len(result.records) == 1
    assert result.records[0]["title"] == "MEDICAL ASSISTANT"
    assert result.records[0]["location"] == "MIDTOWN MEDICAL, New York, NY, US"
    assert result.records[0]["posted_date"] == "5 days ago"
    assert result.records[0]["requisition_id"] == "1393"
    assert result.records[0]["job_id"] == "582883"
    assert result.records[0]["salary"] == "$51,000.00 To $60,000.00 Annually"
    assert "Health Center Inc." in result.records[0]["description"]
    assert result.records[0]["apply_url"].endswith("&jobId=582883#582883")
