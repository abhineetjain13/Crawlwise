from __future__ import annotations

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
        <script src="https://cdn.example.com/datadome.js"></script>
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
