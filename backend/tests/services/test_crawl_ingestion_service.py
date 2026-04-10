from __future__ import annotations

import pytest

from app.services.crawl_ingestion_service import (
    build_csv_crawl_payload,
    create_crawl_run_from_csv,
    create_crawl_run_from_payload,
    prepare_crawl_create_payload,
)


def test_prepare_crawl_create_payload_injects_batch_urls() -> None:
    payload = {
        "run_type": "batch",
        "urls": ["https://example.com/1", "https://example.com/2"],
        "settings": {"max_pages": 2},
    }

    prepared = prepare_crawl_create_payload(payload)

    assert prepared["settings"]["urls"] == payload["urls"]
    assert prepared["settings"]["max_pages"] == 2


def test_build_csv_crawl_payload_parses_urls_and_settings() -> None:
    data, url_count = build_csv_crawl_payload(
        csv_content="url\nhttps://example.com/1\nhttps://example.com/2\n",
        surface="ecommerce_detail",
        additional_fields=" brand , price ",
        settings_json='{"max_pages": 3}',
    )

    assert url_count == 2
    assert data["run_type"] == "csv"
    assert data["url"] == "https://example.com/1"
    assert data["urls"] == [
        "https://example.com/1",
        "https://example.com/2",
    ]
    assert data["settings"]["max_pages"] == 3
    assert data["settings"]["csv_content"].startswith("url")
    assert data["additional_fields"] == ["brand", "price"]


def test_build_csv_crawl_payload_rejects_invalid_settings_json() -> None:
    bad_settings = '{"max_pages":"secret-token","api_key":"abc"}'

    with pytest.raises(ValueError, match="_parse_settings_json failed to decode settings JSON") as exc_info:
        build_csv_crawl_payload(
            csv_content="url\nhttps://example.com/1\n",
            surface="ecommerce_detail",
            settings_json='{"max_pages":',
        )

    assert bad_settings not in str(exc_info.value)


def test_build_csv_crawl_payload_rejects_non_object_settings_json() -> None:
    with pytest.raises(ValueError, match="_parse_settings_json expected a JSON object, got list") as exc_info:
        build_csv_crawl_payload(
            csv_content="url\nhttps://example.com/1\n",
            surface="ecommerce_detail",
            settings_json='["not", "an", "object"]',
        )

    assert '["not", "an", "object"]' not in str(exc_info.value)


@pytest.mark.asyncio
async def test_create_crawl_run_from_payload_delegates_to_services(monkeypatch):
    captured = {}

    class _Run:
        id = 77

    async def _fake_create_crawl_run(session, user_id, payload):
        captured["session"] = session
        captured["user_id"] = user_id
        captured["payload"] = payload
        return _Run()

    async def _fake_dispatch_run(session, run):
        captured["dispatch_session"] = session
        captured["dispatch_run"] = run
        return run

    monkeypatch.setattr(
        "app.services.crawl_ingestion_service.create_crawl_run", _fake_create_crawl_run
    )
    monkeypatch.setattr(
        "app.services.crawl_ingestion_service.dispatch_run", _fake_dispatch_run
    )

    session = object()
    payload = {
        "run_type": "batch",
        "urls": ["https://example.com/a"],
        "settings": {},
    }

    run = await create_crawl_run_from_payload(session, 5, payload)

    assert run.id == 77
    assert captured["session"] is session
    assert captured["user_id"] == 5
    assert captured["payload"]["settings"]["urls"] == ["https://example.com/a"]
    assert captured["dispatch_session"] is session
    assert captured["dispatch_run"].id == 77


@pytest.mark.asyncio
async def test_create_crawl_run_from_csv_returns_url_count(monkeypatch):
    captured = {}

    class _Run:
        id = 91

    async def _fake_create_crawl_run(session, user_id, payload):
        captured["payload"] = payload
        return _Run()

    async def _fake_dispatch_run(session, run):
        captured["run"] = run
        return run

    monkeypatch.setattr(
        "app.services.crawl_ingestion_service.create_crawl_run", _fake_create_crawl_run
    )
    monkeypatch.setattr(
        "app.services.crawl_ingestion_service.dispatch_run", _fake_dispatch_run
    )

    run, url_count = await create_crawl_run_from_csv(
        object(),
        9,
        csv_content="https://example.com/1\nhttps://example.com/2\n",
        surface="ecommerce_detail",
        settings_json="{}",
    )

    assert run.id == 91
    assert url_count == 2
    assert captured["payload"]["urls"] == [
        "https://example.com/1",
        "https://example.com/2",
    ]
