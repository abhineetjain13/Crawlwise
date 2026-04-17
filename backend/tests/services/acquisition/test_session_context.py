from __future__ import annotations

from app.services.acquisition.session_context import SessionContext


def test_merge_playwright_cookies_replaces_existing_cookie_by_name_and_domain() -> None:
    context = SessionContext()

    context.merge_playwright_cookies(
        [
            {"name": "sid", "domain": ".example.com", "value": "one"},
            {"name": "lang", "domain": ".example.com", "value": "en"},
        ]
    )
    context.merge_playwright_cookies(
        [
            {"name": "sid", "domain": ".example.com", "value": "two", "path": "/"},
        ]
    )

    cookies = sorted(
        context.playwright_cookies,
        key=lambda cookie: (cookie.get("name", ""), cookie.get("domain", "")),
    )
    assert cookies == [
        {"name": "lang", "domain": ".example.com", "value": "en"},
        {"name": "sid", "domain": ".example.com", "value": "two", "path": "/"},
    ]


def test_session_context_diagnostics_counts_keyed_playwright_cookies() -> None:
    context = SessionContext(cookies={"a": "1"})
    context.merge_playwright_cookies(
        [
            {"name": "sid", "domain": ".example.com", "value": "one"},
            {"name": "sid", "domain": ".example.com", "value": "two"},
        ]
    )

    diagnostics = context.to_diagnostics()

    assert diagnostics["cookie_count"] == 2
