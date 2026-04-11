# Tests for HTML source parsing helpers.
from __future__ import annotations

import pytest

from app.services.extract import source_parsers
from app.services.extract.source_parsers import parse_page_sources


def test_parse_page_sources_json_ld():
    html = """
    <html><body>
    <script type="application/ld+json">
    {"@type": "Product", "name": "Widget", "price": "19.99"}
    </script>
    </body></html>
    """
    page_sources = parse_page_sources(html)
    assert len(page_sources["json_ld"]) == 1
    assert page_sources["json_ld"][0]["name"] == "Widget"


def test_parse_page_sources_json_ld_flattens_graph():
    html = """
    <html><body>
    <script type="application/ld+json">
    {"@graph":[{"@type":"BreadcrumbList","name":"Breadcrumbs"},{"@type":"Product","name":"Graph Widget"}]}
    </script>
    </body></html>
    """
    page_sources = parse_page_sources(html)
    assert len(page_sources["json_ld"]) == 2
    assert any(item.get("name") == "Graph Widget" for item in page_sources["json_ld"])


def test_parse_page_sources_json_ld_with_trailing_semicolon():
    html = """
    <html><body>
    <script type="application/ld+json">
    {"@type": "Product", "name": "Widget", "offers": {"price": "19.99"}};
    </script>
    </body></html>
    """
    page_sources = parse_page_sources(html)
    assert len(page_sources["json_ld"]) == 1
    assert page_sources["json_ld"][0]["name"] == "Widget"


def test_parse_page_sources_json_ld_invalid_json():
    page_sources = parse_page_sources(
        '<html><body><script type="application/ld+json">not valid json{</script></body></html>'
    )
    assert page_sources["json_ld"] == []


def test_parse_page_sources_next_data():
    html = """
    <html><body>
    <script id="__NEXT_DATA__">{"props":{"pageProps":{"product":{"name":"NextWidget"}}}}</script>
    </body></html>
    """
    page_sources = parse_page_sources(html)
    assert page_sources["next_data"]["props"]["pageProps"]["product"]["name"] == "NextWidget"


def test_parse_page_sources_hydrated_state_backfills_next_data():
    html = """
    <html><body>
    <script>window.__INITIAL_STATE__ = {"props":{"pageProps":{"product":{"name":"HydratedWidget"}}}}</script>
    </body></html>
    """
    page_sources = parse_page_sources(html)
    assert len(page_sources["hydrated_states"]) == 1
    assert page_sources["hydrated_states"][0]["props"]["pageProps"]["product"]["name"] == "HydratedWidget"
    assert page_sources["next_data"]["_hydrated_states"] == page_sources["hydrated_states"]


def test_parse_page_sources_hydrated_assignment_preserves_semicolon_in_string():
    html = """
    <html><body>
    <script>
    window.__INITIAL_STATE__ = {"props":{"message":"Hydrated;Widget","items":[1,2,3]}};
    window.__OTHER_STATE__ = {"ok": true};
    </script>
    </body></html>
    """
    page_sources = parse_page_sources(html)
    assert page_sources["hydrated_states"][0]["props"]["message"] == "Hydrated;Widget"


def test_parse_page_sources_microdata():
    html = """
    <html><body>
    <div itemscope itemtype="http://schema.org/Product">
        <span itemprop="name">Micro Product</span>
        <span itemprop="price" content="29.99">$29.99</span>
    </div>
    </body></html>
    """
    page_sources = parse_page_sources(html)
    assert page_sources["microdata"][0]["name"] == "Micro Product"
    assert page_sources["microdata"][0]["price"] == "$29.99"


def test_parse_page_sources_open_graph():
    html = """
    <html><body>
    <meta property="og:title" content="OG Widget" />
    <meta property="og:image" content="https://cdn.example.com/widget.jpg" />
    </body></html>
    """
    page_sources = parse_page_sources(html)
    assert page_sources["open_graph"]["og:title"] == "OG Widget"
    assert page_sources["open_graph"]["og:image"] == "https://cdn.example.com/widget.jpg"


def test_parse_page_sources_tables():
    html = """
    <html><body>
    <table>
        <tr><th>Name</th><th>Price</th></tr>
        <tr><td>Widget A</td><td>$10</td></tr>
        <tr><td>Widget B</td><td>$20</td></tr>
    </table>
    </body></html>
    """
    page_sources = parse_page_sources(html)
    assert len(page_sources["tables"]) == 1
    assert [header["text"] for header in page_sources["tables"][0]["headers"]] == ["Name", "Price"]
    assert page_sources["tables"][0]["rows"][1]["cells"][1]["text"] == "$20"


def test_parse_page_sources_empty_html():
    page_sources = parse_page_sources("")
    assert page_sources["json_ld"] == []
    assert page_sources["next_data"] is None
    assert page_sources["microdata"] == []
    assert page_sources["tables"] == []


def test_parse_page_sources_embedded_json_from_data_attribute():
    html = """
    <html><body>
    <div data-product='{"name":"Attr Widget","price":"19.99"}'></div>
    </body></html>
    """
    page_sources = parse_page_sources(html)
    assert page_sources["embedded_json"][0]["_blob_family"] == "product_json"
    assert page_sources["embedded_json"][0]["_blob_origin"] == "data_attr"
    assert page_sources["embedded_json"][0]["_blob_payload"]["name"] == "Attr Widget"


def test_parse_page_sources_rejects_generic_config_data_attribute_blob():
    html = """
    <html><body>
    <div data-config='{"title":"Cookie Banner","theme":"light"}'></div>
    </body></html>
    """
    page_sources = parse_page_sources(html)
    assert page_sources["embedded_json"] == []


def test_parse_page_sources_embedded_json_keeps_raw_product_script_with_family():
    html = """
    <html><body>
    <script id="product-json">
    {"product":{"name":"Widget","price":"19.99","brand":"Acme"}}
    </script>
    </body></html>
    """
    page_sources = parse_page_sources(html)
    assert len(page_sources["embedded_json"]) == 1
    assert page_sources["embedded_json"][0]["_blob_family"] == "product_json"
    assert page_sources["embedded_json"][0]["_blob_origin"] == "script"
    assert page_sources["embedded_json"][0]["_blob_payload"]["product"]["name"] == "Widget"


def test_parse_page_sources_deduplicates_application_json_between_hydrated_and_embedded():
    html = """
    <html><body>
    <script id="state" type="application/json">
    {"product":{"title":"Embedded Widget"}}
    </script>
    </body></html>
    """
    page_sources = parse_page_sources(html)
    assert len(page_sources["hydrated_states"]) == 1
    assert page_sources["hydrated_states"][0]["product"]["title"] == "Embedded Widget"
    assert page_sources["embedded_json"] == []


def test_parse_page_sources_hydrated_state_from_react_create_element_props():
    html = """
    <html><body>
    <script>
    ReactDOM.hydrate(
      React.createElement(App, {
        "searchStore": {
          "works": [
            {"title": "Book A", "workUrl": "book-a", "buyNowPrice": 4.99},
            {"title": "Book B", "workUrl": "book-b", "buyNowPrice": 5.99}
          ]
        }
      }),
      document.getElementById("root")
    );
    </script>
    </body></html>
    """
    page_sources = parse_page_sources(html)
    assert page_sources["hydrated_states"][0]["searchStore"]["works"][0]["title"] == "Book A"


def test_parse_page_sources_react_create_element_props_stops_at_current_call():
    html = """
    <html><body>
    <script>
    ReactDOM.hydrate(
      React.createElement(App, {
        "searchStore": {
          "works": [
            {"title": "Book A", "meta": {"pages": 120}}
          ]
        }
      }),
      document.getElementById("root")
    );
    React.createElement(Footer, {"footer": true});
    </script>
    </body></html>
    """
    page_sources = parse_page_sources(html)
    assert len(page_sources["hydrated_states"]) == 1
    assert page_sources["hydrated_states"][0]["searchStore"]["works"][0]["title"] == "Book A"


def test_parse_page_sources_react_create_element_props_preserves_single_quoted_commas():
    html = """
    <html><body>
    <script>
    ReactDOM.hydrate(
      React.createElement(App, {"title": "Widget", "meta": {"ok": true}}, 'Widget, Deluxe'),
      document.getElementById("root")
    );
    </script>
    </body></html>
    """
    page_sources = parse_page_sources(html)
    assert page_sources["hydrated_states"][0]["title"] == "Widget"


def test_parse_page_sources_react_create_element_props_handles_nested_template_expression_braces():
    html = """
    <html><body>
    <script>
    ReactDOM.hydrate(
      React.createElement(
        App,
        {"title": "Widget"},
        `price-${formatPrice({ amount: 10, currency: { code: "USD" } })}`,
        document.body
      ),
      document.getElementById("root")
    );
    </script>
    </body></html>
    """
    page_sources = parse_page_sources(html)
    assert page_sources["hydrated_states"][0]["title"] == "Widget"


def test_parse_page_sources_uses_pure_sync_json_parsing(monkeypatch: pytest.MonkeyPatch):
    html = """
    <html><body>
    <script id="__NEXT_DATA__">{"props":{"pageProps":{"product":{"name":"NextWidget"}}}}</script>
    <script>
    dataLayer.push({
        "ecommerce": {
            "items": [
                {
                    "price": 19.99,
                    "currency": "USD"
                }
            ]
        }
    });
    </script>
    </body></html>
    """

    def _unexpected_async_usage(*_args, **_kwargs):
        raise AssertionError("sync parser should not spin up asyncio helpers")

    monkeypatch.setattr(source_parsers.asyncio, "run", _unexpected_async_usage)
    monkeypatch.setattr(source_parsers.asyncio, "to_thread", _unexpected_async_usage)

    page_sources = parse_page_sources(html)

    assert page_sources["next_data"]["props"]["pageProps"]["product"]["name"] == "NextWidget"
    assert page_sources["datalayer"]["price"] == 19.99


@pytest.mark.asyncio
async def test_parse_page_sources_async_offloads_sync_parser(
    monkeypatch: pytest.MonkeyPatch,
):
    html = """
    <html><body>
    <script type="application/ld+json">
    {"@type": "Product", "name": "Async Widget", "price": "19.99"}
    </script>
    </body></html>
    """
    captured: list[tuple[object, tuple[object, ...], dict[str, object]]] = []
    real_parse_page_sources = source_parsers.parse_page_sources

    async def _fake_to_thread(func, *args, **kwargs):
        captured.append((func, args, kwargs))
        return func(*args, **kwargs)

    monkeypatch.setattr(source_parsers.asyncio, "to_thread", _fake_to_thread)

    page_sources = await source_parsers.parse_page_sources_async(html)

    assert captured
    assert captured[0][0] is real_parse_page_sources
    assert page_sources["json_ld"][0]["name"] == "Async Widget"
