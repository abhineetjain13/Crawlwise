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


def test_classify_blocked_page_detects_kasada_kpsdk_shell() -> None:
    html = """
    <html>
      <head></head>
      <body>
        <script>window.KPSDK={};KPSDK.start=Date.now();</script>
        <script src="/kpsdk/149e9513/2d206a39/ips.js?KP_UIDz=abc"></script>
        <iframe src="javascript:;" style="display:none"></iframe>
      </body>
    </html>
    """

    classification = classify_blocked_page(html, 200)

    assert classification.blocked is True
    assert classification.outcome == "challenge_page"
    assert "kpsdk" in classification.provider_hits
    assert "kpsdk" in classification.active_provider_hits
    assert "kasada_ips_script" in classification.challenge_element_hits
    assert "kasada_kpsdk_bootstrap" in classification.challenge_element_hits


def test_classify_blocked_page_keeps_perimeterx_evidence_on_403() -> None:
    html = """
    <html>
      <head>
        <title>Access to this page has been denied</title>
        <meta name="description" content="px-captcha" />
        <script src="https://captcha.perimeterx.net/app/captcha.js"></script>
      </head>
      <body>
        <main>Please verify you are a human</main>
      </body>
    </html>
    """

    classification = classify_blocked_page(html, 403)

    assert classification.blocked is True
    assert classification.outcome == "challenge_page"
    assert "http_status:403" in classification.evidence
    assert "perimeterx" in classification.provider_hits
    assert "px-captcha" in classification.provider_hits
    assert "px-captcha" in classification.active_provider_hits


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


def test_classify_blocked_page_preserves_usable_listing_content_despite_vendor_markers() -> None:
    html = """
    <html>
      <head>
        <title>KitchenAid Food Processors</title>
        <script>window.vendor = "akamai";</script>
      </head>
      <body>
        <div class="g-recaptcha"></div>
        <iframe title="captcha"></iframe>
        <main>
          <article>
            <a href="/products/food-processor-1">Food Processor One</a>
            <span>$129.99</span>
          </article>
          <article>
            <a href="/products/food-processor-2">Food Processor Two</a>
            <span>$149.99</span>
          </article>
          <article>
            <a href="/products/food-processor-3">Food Processor Three</a>
            <span>$179.99</span>
          </article>
        </main>
      </body>
    </html>
    """

    classification = classify_blocked_page(html, 200)

    assert classification.blocked is False
    assert "akamai" in classification.provider_hits
    assert "captcha_titled_iframe" in classification.challenge_element_hits


def test_classify_blocked_page_preserves_extractable_content_on_403_without_strong_hits() -> None:
    html = """
    <html>
      <head>
        <title>KitchenAid Food Processors</title>
      </head>
      <body>
        <main>
          <article>
            <a href="/products/food-processor-1">Food Processor One</a>
            <span>$129.99</span>
          </article>
          <article>
            <a href="/products/food-processor-2">Food Processor Two</a>
            <span>$149.99</span>
          </article>
          <article>
            <a href="/products/food-processor-3">Food Processor Three</a>
            <span>$179.99</span>
          </article>
        </main>
      </body>
    </html>
    """

    classification = classify_blocked_page(html, 403)

    assert classification.blocked is False
    assert classification.outcome == "ok"
    assert "http_status:403" in classification.evidence


def test_classify_blocked_page_preserves_extractable_listing_with_captcha_provider_markers_only() -> None:
    html = """
    <html>
      <head><title>adidas Sneakers | Shop Stadium Goods</title></head>
      <body>
        <p>This page is protected by captcha services.</p>
        <script src="https://www.google.com/recaptcha/api.js"></script>
        <script src="https://js.hcaptcha.com/1/api.js"></script>
        <main>
          <article><a href="/products/a">A</a><span>$100</span></article>
          <article><a href="/products/b">B</a><span>$110</span></article>
          <article><a href="/products/c">C</a><span>$120</span></article>
        </main>
      </body>
    </html>
    """

    classification = classify_blocked_page(html, 200)

    assert classification.blocked is False
    assert classification.strong_hits == ["captcha"]
    assert "recaptcha" in classification.provider_hits


def test_classify_blocked_page_blocks_captcha_provider_page_without_extractable_content() -> None:
    html = """
    <html>
      <head><title>Security Check</title></head>
      <body>
        <p>Please complete the captcha to continue.</p>
        <script src="https://www.google.com/recaptcha/api.js"></script>
      </body>
    </html>
    """

    classification = classify_blocked_page(html, 200)

    assert classification.blocked is True
    assert classification.strong_hits == ["captcha"]
    assert "recaptcha" in classification.provider_hits
