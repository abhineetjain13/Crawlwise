from __future__ import annotations

from app.services.shared.url_utils import (
    _ensure_scheme,
    _is_placeholder_image_url,
    absolute_url,
    extract_urls,
    same_host,
)


def test_absolute_url_repairs_relative_and_bare_host_values() -> None:
    assert absolute_url("https://example.com/a/page", "../p") == "https://example.com/p"
    assert absolute_url("https://example.com", "cdn.example.com") == (
        "https://cdn.example.com"
    )


def test_ensure_scheme_preserves_relative_and_existing_scheme() -> None:
    assert _ensure_scheme("example.com") == "https://example.com"
    assert _ensure_scheme("/path") == "/path"
    assert _ensure_scheme("javascript:void(0)") == "javascript:void(0)"
    assert _ensure_scheme("http://example.com") == "http://example.com"


def test_same_host_and_extract_urls_trim_malformed_candidates() -> None:
    assert same_host("https://example.com/a", "https://example.com/b")
    assert not same_host("https://example.com/a", "https://other.test/b")
    assert extract_urls(
        "See https://example.com/a), https://example.com/b.",
        "https://example.com",
    ) == ["https://example.com/a", "https://example.com/b"]
    assert extract_urls("https://example.com/ahttps://example.com/b", "https://x") == []


def test_placeholder_images_are_rejected() -> None:
    assert _is_placeholder_image_url("https://via.placeholder.com/100")
    assert extract_urls("https://via.placeholder.com/100", "https://example.com") == []
