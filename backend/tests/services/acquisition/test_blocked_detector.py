# Tests for blocked/challenge page detection.
from __future__ import annotations

from app.services.acquisition.blocked_detector import detect_blocked_page


def test_empty_page_is_blocked():
    result = detect_blocked_page("")
    assert result.is_blocked
    assert result.reason == "empty_or_too_short"


def test_short_page_is_blocked():
    result = detect_blocked_page("<html><body>tiny</body></html>")
    assert result.is_blocked
    assert result.reason == "empty_or_too_short"


def test_normal_page_is_not_blocked():
    html = "<html><head><title>Product Page</title></head><body>" + "<p>content</p>" * 50 + "</body></html>"
    result = detect_blocked_page(html)
    assert not result.is_blocked


def test_access_denied_title():
    html = """
    <html><head><title>Access Denied</title></head>
    <body><p>You do not have permission to access this resource.</p>
    """ + "x" * 200 + "</body></html>"
    result = detect_blocked_page(html)
    assert result.is_blocked
    assert "blocked_title" in result.reason


def test_robot_or_human_challenge():
    html = """
    <html><head><title>Robot or human?</title></head>
    <body><div>Please verify you are a human</div>
    """ + "x" * 200 + "</body></html>"
    result = detect_blocked_page(html)
    assert result.is_blocked


def test_perimeterx_detected():
    html = """
    <html><head><title>Press & Hold</title></head>
    <body><div class="px-captcha"></div>
    <script src="https://client.perimeterx.net/main.js"></script>
    """ + "x" * 200 + "</body></html>"
    result = detect_blocked_page(html)
    assert result.is_blocked
    assert result.provider == "perimeterx"


def test_cloudflare_challenge():
    html = """
    <html><head><title>Just a moment...</title></head>
    <body><div>Checking if the site connection is secure</div>
    <div class="cf-challenge"></div>
    """ + "x" * 200 + "</body></html>"
    result = detect_blocked_page(html)
    assert result.is_blocked
    assert result.provider in ("cloudflare", "cf-challenge", "cf-browser-verification")


def test_walmart_robot_check():
    html = """
    <html><head><title>Robot or human?</title></head>
    <body><h1>Robot or human?</h1>
    <p>Please complete the CAPTCHA to continue</p>
    <script src="https://cdn.perimeterx.net/px.js"></script>
    """ + "x" * 200 + "</body></html>"
    result = detect_blocked_page(html)
    assert result.is_blocked
    assert result.reason


def test_kasada_challenge_detected():
    html = (
        '<html><head></head><body>'
        '<script>window.KPSDK={};KPSDK.now=Date.now;</script>'
        '<script src="/ips.js"></script>'
        '</body></html>'
    )
    result = detect_blocked_page(html)
    assert result.is_blocked
    assert result.provider == "kasada"


def test_akamai_cdn_page_not_blocked():
    """A normal page served via Akamai CDN should NOT be flagged as blocked."""
    html = (
        '<html><head><title>Product Page</title></head><body>'
        + '<p>Real product content</p>' * 30
        + '<script src="https://cdn.akamaized.net/bundle.js"></script>'
        + '</body></html>'
    )
    result = detect_blocked_page(html)
    assert not result.is_blocked


def test_provider_marker_still_blocks_with_structural_signals_present():
    html = (
        "<html><head><title>Welcome</title></head><body>"
        + ("<script></script>" * 4)
        + "<div class='dd-modal'>Please wait</div>"
        + "</body></html>"
    )
    result = detect_blocked_page(html)
    assert result.is_blocked
    assert result.provider == "datadome"
