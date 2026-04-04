from __future__ import annotations

from app.schemas.crawl import _sanitize_proxy_item


def test_sanitize_proxy_item_masks_all_url_fields_and_removes_secrets():
    sanitized = _sanitize_proxy_item(
        {
            "url": "http://user:pass@proxy.example.com:8080",
            "proxy": "http://user:pass@proxy.example.com:8080",
            "proxy_url": "http://user:pass@proxy.example.com:8080",
            "server": "http://user:pass@proxy.example.com:8080",
            "token": "secret-token",
            "password": "secret-password",
        }
    )

    assert sanitized == {
        "url": "http://***:***@proxy.example.com:8080",
        "proxy": "http://***:***@proxy.example.com:8080",
        "proxy_url": "http://***:***@proxy.example.com:8080",
        "server": "http://***:***@proxy.example.com:8080",
    }
