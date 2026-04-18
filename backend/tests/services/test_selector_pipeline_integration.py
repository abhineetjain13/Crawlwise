from __future__ import annotations

import pytest

from app.services._batch_runtime import process_run
from app.services.acquisition.acquirer import AcquisitionResult
from app.services.crawl_crud import create_crawl_run, get_run_records
from app.services.domain_memory_service import save_domain_memory


@pytest.mark.asyncio
async def test_process_run_uses_domain_memory_selector_rules(
    db_session,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await save_domain_memory(
        db_session,
        domain="example.com",
        surface="ecommerce_detail",
        selectors={
            "rules": [
                {
                    "id": 1,
                    "field_name": "title",
                    "css_selector": ".custom-title",
                    "source": "manual",
                    "status": "validated",
                    "is_active": True,
                },
                {
                    "id": 2,
                    "field_name": "price",
                    "css_selector": ".custom-price",
                    "source": "manual",
                    "status": "validated",
                    "is_active": True,
                },
            ]
        },
    )
    await db_session.commit()

    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/products/selector-widget",
            "surface": "ecommerce_detail",
        },
    )

    async def _fake_acquire(request):
        return AcquisitionResult(
            request=request,
            final_url=request.url,
            html="""
            <html>
              <body>
                <section class="hero">
                  <div class="custom-title">Selector Widget</div>
                  <div class="custom-price">$19.99</div>
                </section>
              </body>
            </html>
            """,
            method="test",
            status_code=200,
        )

    monkeypatch.setattr("app.services.pipeline.core.acquire", _fake_acquire)

    await process_run(db_session, run.id)
    rows, total = await get_run_records(db_session, run.id, 1, 20)

    assert total == 1
    assert rows[0].data["title"] == "Selector Widget"
    assert rows[0].data["price"] == "19.99"
    assert "dom_selector" in rows[0].source_trace["field_discovery"]["title"]["sources"]
