from __future__ import annotations

import pytest

from app.services._batch_runtime import process_run
from app.services.acquisition.acquirer import AcquisitionResult
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.crawl_crud import create_crawl_run, get_run_records
from app.services.domain_memory_service import load_domain_memory, save_domain_memory


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


@pytest.mark.asyncio
async def test_process_run_self_heals_selectors_and_reuses_domain_memory_without_second_llm_call(
    db_session,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_enabled = crawler_runtime_settings.selector_self_heal_enabled
    original_threshold = crawler_runtime_settings.selector_self_heal_min_confidence
    crawler_runtime_settings.selector_self_heal_enabled = True
    crawler_runtime_settings.selector_self_heal_min_confidence = 0.8
    llm_calls: list[list[str]] = []
    try:
        first_run = await create_crawl_run(
            db_session,
            test_user.id,
            {
                "run_type": "crawl",
                "url": "https://example.com/products/self-heal-widget",
                "surface": "ecommerce_detail",
                "additional_fields": ["specifications"],
                "settings": {"llm_enabled": True},
            },
        )
        second_run = await create_crawl_run(
            db_session,
            test_user.id,
            {
                "run_type": "crawl",
                "url": "https://example.com/products/self-heal-widget",
                "surface": "ecommerce_detail",
                "additional_fields": ["specifications"],
                "settings": {"llm_enabled": True},
            },
        )

        async def _fake_acquire(request):
            return AcquisitionResult(
                request=request,
                final_url=request.url,
                html="""
                <html>
                  <body>
                    <h1>Self Heal Widget</h1>
                    <div class="custom-specs">Rubber outsole, reinforced toe cap.</div>
                  </body>
                </html>
                """,
                method="test",
                status_code=200,
            )

        async def _fake_discover_xpath_candidates(
            session,
            *,
            run_id,
            domain,
            url,
            html_text,
            missing_fields,
            existing_values,
        ):
            del session, run_id, domain, url, html_text, existing_values
            llm_calls.append(list(missing_fields))
            return (
                [
                    {
                        "field_name": "specifications",
                        "xpath": "//div[contains(concat(' ', normalize-space(@class), ' '), ' custom-specs ')]",
                    }
                ],
                None,
            )

        monkeypatch.setattr("app.services.pipeline.core.acquire", _fake_acquire)
        monkeypatch.setattr(
            "app.services.selector_self_heal.discover_xpath_candidates",
            _fake_discover_xpath_candidates,
        )

        await process_run(db_session, first_run.id)
        await process_run(db_session, second_run.id)

        first_rows, first_total = await get_run_records(db_session, first_run.id, 1, 20)
        second_rows, second_total = await get_run_records(db_session, second_run.id, 1, 20)
        memory = await load_domain_memory(
            db_session,
            domain="example.com",
            surface="ecommerce_detail",
        )

        assert first_total == 1
        assert second_total == 1
        assert first_rows[0].data["specifications"] == "Rubber outsole, reinforced toe cap."
        assert second_rows[0].data["specifications"] == "Rubber outsole, reinforced toe cap."
        assert first_rows[0].source_trace["extraction"]["self_heal"]["mode"] == "selector_synthesis"
        assert (
            second_rows[0].source_trace["field_discovery"]["specifications"]["value"]
            == "Rubber outsole, reinforced toe cap."
        )
        assert llm_calls == [["specifications"]]
        assert memory is not None
        assert any(
            row.get("field_name") == "specifications"
            for row in memory.selectors.get("rules", [])
        )
    finally:
        crawler_runtime_settings.selector_self_heal_enabled = original_enabled
        crawler_runtime_settings.selector_self_heal_min_confidence = original_threshold
