# Basic schema smoke tests.
from __future__ import annotations

from datetime import UTC, datetime

from app.schemas.crawl import CrawlRunResponse


def test_smoke() -> None:
    assert True


def test_crawl_run_response_masks_sensitive_settings() -> None:
    payload = CrawlRunResponse.model_validate(
        {
            "id": 1,
            "user_id": 1,
            "run_type": "crawl",
            "url": "https://example.com",
            "status": "completed",
            "surface": "ecommerce_detail",
            "settings": {
                "proxy_list": ["http://user:secret@proxy.example:8080"],
                "proxy": "http://alice:token@proxy2.example:8181",
                "llm_config_snapshot": {
                    "general": {
                        "provider": "groq",
                        "api_key_encrypted": "secret-ciphertext",
                    }
                },
            },
            "requested_fields": [],
            "result_summary": {},
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
            "completed_at": datetime.now(UTC),
        }
    )

    assert payload.settings["proxy_list"] == ["http://***:***@proxy.example:8080"]
    assert payload.settings["proxy"] == "http://***:***@proxy2.example:8181"
    assert payload.settings["llm_config_snapshot"]["general"]["provider"] == "groq"
    assert "api_key_encrypted" not in payload.settings["llm_config_snapshot"]["general"]
