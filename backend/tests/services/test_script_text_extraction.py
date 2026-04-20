from __future__ import annotations

from bs4 import BeautifulSoup
import pytest

from app.services.script_text_extractor import (
    ScriptTextNode,
    iter_script_text_nodes,
    iter_script_text_nodes_async,
)
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


def test_harvest_js_state_objects_reads_custom_window_state_assignment() -> None:
    html = """
    <html>
      <head>
        <script>
          window.__myx = {"pdpData":{"name":"Myx Widget","id":77}};
        </script>
      </head>
      <body></body>
    </html>
    """

    state_objects = harvest_js_state_objects(
        BeautifulSoup(html, "html.parser"),
        html,
    )

    assert state_objects["__myx"]["pdpData"]["name"] == "Myx Widget"
    assert state_objects["__myx"]["pdpData"]["id"] == 77


@pytest.mark.asyncio
async def test_iter_script_text_nodes_async_matches_sync_output() -> None:
    html = """
    <html>
      <head>
        <script id="alpha" type="application/json">{"ok": true}</script>
        <script>window.answer = 42;</script>
      </head>
    </html>
    """

    expected_rows = [
        ScriptTextNode(
            script_id="alpha",
            script_type="application/json",
            text='{"ok": true}',
        ),
        ScriptTextNode(
            script_id="",
            script_type="",
            text="window.answer = 42;",
        ),
    ]
    async_rows = list(await iter_script_text_nodes_async(html))
    sync_rows = list(iter_script_text_nodes(html))

    assert sync_rows == expected_rows
    assert async_rows == sync_rows
