from __future__ import annotations

from copy import deepcopy

import pytest

from app.services.acquisition.runtime import classify_blocked_page
from app.services.crawl_fetch_runtime import is_blocked_html


def test_is_blocked_html_detects_real_challenge_page() -> None:
    html = """
    <html>
      <head><title>Just a moment...</title></head>
      <body>
        <h1>Checking your browser before accessing the site.</h1>
        <div id="cf-challenge-running">Cloudflare challenge</div>
      </body>
    </html>
    """

    assert is_blocked_html(html, 200) is True


def test_is_blocked_html_ignores_generic_captcha_text_inside_scripts() -> None:
    html = """
    <html>
      <head><title>Careers</title></head>
      <body>
        <h1>Join our team</h1>
        <script>
          var themeConfig = {"captcha":"Captcha","wrong_captcha":"You entered the wrong number in captcha."};
        </script>
        <p>Browse current openings.</p>
      </body>
    </html>
    """

    assert is_blocked_html(html, 200) is False


def test_is_blocked_html_does_not_block_on_provider_marker_alone() -> None:
    html = """
    <html>
      <head>
        <meta name="provider" content="datadome" />
        <title>Widget Prime</title>
      </head>
      <body>
        <h1>Widget Prime</h1>
        <p>Normal product page content with a provider script loaded.</p>
      </body>
    </html>
    """

    classification = classify_blocked_page(html, 200)

    assert classification.blocked is False
    assert "datadome" in classification.provider_hits
    assert classification.challenge_element_hits == []


def test_classify_blocked_page_detects_datadome_captcha_delivery_challenge() -> None:
    html = """
    <html>
      <head><title>autozone.com</title></head>
      <body>
        <script>var dd={"host":"geo.captcha-delivery.com"}</script>
        <script src="https://ct.captcha-delivery.com/c.js"></script>
        <iframe
          src="https://geo.captcha-delivery.com/captcha/?cid=123"
          title="DataDome CAPTCHA"
        ></iframe>
      </body>
    </html>
    """

    classification = classify_blocked_page(html, 200)

    assert classification.blocked is True
    assert classification.outcome == "challenge_page"
    assert "datadome" in classification.provider_hits
    assert "captcha_delivery_iframe" in classification.challenge_element_hits


def test_classify_blocked_page_uses_configured_challenge_element_markers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.acquisition import runtime

    signatures = deepcopy(runtime.BLOCK_SIGNATURES)
    signatures["challenge_elements"] = {
        "iframe_src_markers": {
            "challenge.vendor.test": "vendor_iframe",
        },
        "iframe_title_markers": {},
        "script_src_markers": {},
        "html_markers": {},
    }
    monkeypatch.setattr(runtime, "BLOCK_SIGNATURES", signatures)

    html = """
    <html>
      <head><title>Just a moment...</title></head>
      <body>
        <iframe src="https://challenge.vendor.test/frame"></iframe>
      </body>
    </html>
    """

    classification = classify_blocked_page(html, 200)

    assert classification.blocked is True
    assert "vendor_iframe" in classification.challenge_element_hits
