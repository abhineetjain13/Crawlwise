from __future__ import annotations

import pytest

from app.models.llm import LLMConfig
from app.services._batch_runtime import process_run
from app.services.acquisition.acquirer import AcquisitionResult
from app.services.crawl_crud import get_run_records
from app.services.llm_config_service import resolve_run_config, snapshot_active_configs


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
    create_test_run,
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

    run = await create_test_run(
        url="https://example.com/products/snapshot-widget",
        surface="ecommerce_detail",
    )

    assert run.settings["llm_config_snapshot"]["general"]["model"] == "llama"
    assert run.settings["extraction_runtime_snapshot"]["selector_self_heal"]["enabled"] is False


@pytest.mark.asyncio
async def test_resolve_run_config_prefers_stamped_snapshot(
    db_session,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
    create_test_run,
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
    run = await create_test_run(
        url="https://example.com/products/snapshot-widget",
        surface="ecommerce_detail",
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
    create_test_run,
    patch_settings,
) -> None:
    async def _empty_snapshot(_session):
        return {}

    monkeypatch.setattr(
        "app.services.crawl_crud.snapshot_active_configs",
        _empty_snapshot,
    )
    patch_settings(
        selector_self_heal_enabled=True,
        selector_self_heal_min_confidence=0.91,
    )
    run = await create_test_run(
        url="https://example.com/products/snapshot-widget",
        surface="ecommerce_detail",
    )
    patch_settings(
        selector_self_heal_enabled=False,
        selector_self_heal_min_confidence=0.12,
    )

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


@pytest.mark.asyncio
async def test_snapshot_active_configs_includes_direct_record_extraction(
    db_session,
) -> None:
    db_session.add(
        LLMConfig(
            provider="groq",
            model="llama",
            api_key_encrypted="enc",
            task_type="direct_record_extraction",
            is_active=True,
        )
    )
    await db_session.commit()

    snapshot = await snapshot_active_configs(db_session)

    assert snapshot["direct_record_extraction"]["task_type"] == "direct_record_extraction"


def test_runtime_settings_reject_invalid_llm_confidence_threshold() -> None:
    from app.services.config.runtime_settings import CrawlerRuntimeSettings

    with pytest.raises(ValueError, match="llm_confidence_threshold must be between 0 and 1"):
        CrawlerRuntimeSettings(llm_confidence_threshold=1.2)


def test_runtime_settings_balanced_profile_defaults_longer_challenge_wait() -> None:
    from app.services.config.runtime_settings import CrawlerRuntimeSettings

    settings = CrawlerRuntimeSettings()

    assert settings.performance_profile == "BALANCED"
    assert settings.challenge_wait_max_seconds == 15


def test_runtime_settings_default_url_timeout_includes_acquisition_slack() -> None:
    from app.services.config.runtime_settings import CrawlerRuntimeSettings

    settings = CrawlerRuntimeSettings(
        url_process_timeout_seconds=20,
        acquisition_attempt_timeout_seconds=30,
        url_process_timeout_buffer_seconds=12,
    )

    assert settings.default_url_process_timeout_seconds() == 42.0
