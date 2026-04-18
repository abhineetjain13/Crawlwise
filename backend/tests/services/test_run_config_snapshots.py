from __future__ import annotations

import pytest

from app.models.llm import LLMConfig
from app.services._batch_runtime import process_run
from app.services.acquisition.acquirer import AcquisitionResult
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.crawl_crud import create_crawl_run, get_run_records
from app.services.llm_config_service import resolve_run_config


def _detail_html() -> str:
    return """
    <html>
      <body>
        <h1>Snapshot Widget</h1>
        <div class="price">$19.99</div>
      </body>
    </html>
    """


@pytest.mark.asyncio
async def test_create_crawl_run_stamps_llm_and_extraction_snapshots(
    db_session,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _snapshot_configs(_session):
        return {
            "general": {
                "provider": "groq",
                "model": "llama",
                "task_type": "general",
                "id": 7,
                "api_key_encrypted": "enc",
            }
        }

    monkeypatch.setattr(
        "app.services.crawl_crud.snapshot_active_configs",
        _snapshot_configs,
    )

    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/products/snapshot-widget",
            "surface": "ecommerce_detail",
        },
    )

    assert run.settings["llm_config_snapshot"]["general"]["model"] == "llama"
    assert run.settings["extraction_runtime_snapshot"]["selector_self_heal"]["enabled"] is False


@pytest.mark.asyncio
async def test_resolve_run_config_prefers_stamped_snapshot(
    db_session,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _snapshot_configs(_session):
        return {
            "general": {
                "provider": "groq",
                "model": "snapshot-model",
                "task_type": "general",
                "id": 9,
                "api_key_encrypted": "enc",
            }
        }

    monkeypatch.setattr(
        "app.services.crawl_crud.snapshot_active_configs",
        _snapshot_configs,
    )
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/products/snapshot-widget",
            "surface": "ecommerce_detail",
        },
    )
    db_session.add(
        LLMConfig(
            provider="groq",
            model="live-model",
            api_key_encrypted="enc-live",
            task_type="general",
            is_active=True,
        )
    )
    await db_session.commit()

    resolved = await resolve_run_config(
        db_session,
        run_id=run.id,
        task_type="missing_field_extraction",
    )

    assert resolved is not None
    assert resolved["model"] == "snapshot-model"


@pytest.mark.asyncio
async def test_process_run_uses_stamped_selector_self_heal_snapshot(
    db_session,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _empty_snapshot(_session):
        return {}

    monkeypatch.setattr(
        "app.services.crawl_crud.snapshot_active_configs",
        _empty_snapshot,
    )
    original_enabled = crawler_runtime_settings.selector_self_heal_enabled
    original_threshold = crawler_runtime_settings.selector_self_heal_min_confidence
    crawler_runtime_settings.selector_self_heal_enabled = True
    crawler_runtime_settings.selector_self_heal_min_confidence = 0.91
    try:
        run = await create_crawl_run(
            db_session,
            test_user.id,
            {
                "run_type": "crawl",
                "url": "https://example.com/products/snapshot-widget",
                "surface": "ecommerce_detail",
            },
        )
        crawler_runtime_settings.selector_self_heal_enabled = False
        crawler_runtime_settings.selector_self_heal_min_confidence = 0.12

        async def _fake_acquire(request):
            return AcquisitionResult(
                request=request,
                final_url=request.url,
                html=_detail_html(),
                method="test",
                status_code=200,
            )

        monkeypatch.setattr("app.services.pipeline.core.acquire", _fake_acquire)

        await process_run(db_session, run.id)
        rows, total = await get_run_records(db_session, run.id, 1, 20)

        assert total == 1
        assert rows[0].source_trace["extraction"]["self_heal"] == {
            "enabled": True,
            "triggered": False,
            "threshold": 0.91,
        }
    finally:
        crawler_runtime_settings.selector_self_heal_enabled = original_enabled
        crawler_runtime_settings.selector_self_heal_min_confidence = original_threshold
