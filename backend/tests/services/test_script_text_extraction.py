from __future__ import annotations

from bs4 import BeautifulSoup

from app.services.structured_sources import harvest_js_state_objects, parse_embedded_json


def test_harvest_js_state_objects_reads_next_data_script_by_id() -> None:
    html = """
    <html>
      <head>
        <script id="__NEXT_DATA__" type="application/json">
          {"props":{"pageProps":{"product":{"title":"Selector Widget","id":42}}}}
        </script>
      </head>
      <body></body>
    </html>
    """

    state_objects = harvest_js_state_objects(
        BeautifulSoup(html, "html.parser"),
        html,
    )

    assert state_objects["__NEXT_DATA__"]["props"]["pageProps"]["product"]["title"] == (
        "Selector Widget"
    )
    assert state_objects["__NEXT_DATA__"]["props"]["pageProps"]["product"]["id"] == 42


def test_parse_embedded_json_extracts_inline_script_assignment_payloads() -> None:
    html = """
    <html>
      <head>
        <script>
          window.irrelevant = {"ignored": true};
        </script>
        <script>
          var meta = {"product":{"title":"Inline Widget","sku":"IW-7"}};
        </script>
      </head>
      <body></body>
    </html>
    """

    rows = parse_embedded_json(BeautifulSoup(html, "html.parser"), html)

    assert rows == [{"product": {"title": "Inline Widget", "sku": "IW-7"}}]


def test_parse_embedded_json_ignores_inline_script_without_complete_json_terminal() -> None:
    html = """
    <html>
      <head>
        <script>
          var meta = {"product":{"title":"Broken Widget"}}
        </script>
      </head>
      <body></body>
    </html>
    """

    rows = parse_embedded_json(BeautifulSoup(html, "html.parser"), html)

    assert rows == []
