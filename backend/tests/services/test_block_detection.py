from __future__ import annotations

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
