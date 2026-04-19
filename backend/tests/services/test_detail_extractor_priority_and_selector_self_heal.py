from __future__ import annotations

from bs4 import BeautifulSoup
from selectolax.lexbor import LexborHTMLParser

from app.services.detail_extractor import _apply_dom_fallbacks, _materialize_record
from app.services.selector_self_heal import reduce_html_for_selector_synthesis


def test_materialize_record_prefers_higher_priority_source_even_when_candidates_arrive_out_of_order() -> None:
    record = _materialize_record(
        page_url="https://example.com/products/widget-prime",
        surface="ecommerce_detail",
        requested_fields=["title", "price"],
        fields=["title", "price"],
        candidates={
            "title": ["Widget Prime"],
            "price": ["999.99", "19.99"],
        },
        candidate_sources={
            "title": ["dom_h1"],
            "price": ["dom_text", "adapter"],
        },
        field_sources={
            "title": ["dom_h1"],
            "price": ["dom_text", "adapter"],
        },
        extraction_runtime_snapshot=None,
        tier_name="dom",
        completed_tiers=["authoritative", "dom"],
    )

    assert record["title"] == "Widget Prime"
    assert record["price"] == "19.99"
    assert "dom_text" in str(record["_field_sources"]["price"])
    assert "adapter" in str(record["_field_sources"]["price"])
    assert record["_source"] == "adapter"


def test_dom_fallbacks_do_not_fabricate_discount_percentage_from_unrelated_body_text() -> None:
    html = """
    <html>
      <body>
        <main>
          <h1>Elowen Wide Leg Jumpsuit</h1>
          <p>Composition: 100% cotton. Care at 30 degrees. Free shipping over 50.</p>
          <span class="price">£149.00</span>
        </main>
      </body>
    </html>
    """
    candidates: dict[str, list[object]] = {}
    candidate_sources: dict[str, list[str]] = {}
    field_sources: dict[str, list[str]] = {}

    _apply_dom_fallbacks(
        LexborHTMLParser(html),
        BeautifulSoup(html, "html.parser"),
        "https://www.phase-eight.com/product/elowen-wide-leg-jumpsuit-10022060230.html",
        "ecommerce_detail",
        ["title", "price", "discount_percentage"],
        candidates,
        candidate_sources,
        field_sources,
    )

    assert "discount_percentage" not in candidates
    assert "discount_percentage" not in field_sources


def test_reduce_html_for_selector_synthesis_keeps_valid_content_focused_html() -> None:
    nav_noise = "".join(
        f"<a href='/collections/widgets/{index}'>Noise {index}</a>"
        for index in range(9_000)
    )
    html = f"""
    <html>
      <body>
        <nav>{nav_noise}</nav>
        <main id="product-detail">
          <article class="product">
            <h1>Widget Prime</h1>
            <div class="custom-specs">Rubber outsole, reinforced toe cap.</div>
          </article>
        </main>
        <script>window.__NOISE__ = true;</script>
      </body>
    </html>
    """

    reduced = reduce_html_for_selector_synthesis(html)
    parsed = BeautifulSoup(reduced, "html.parser")
    main = parsed.find("main", attrs={"id": "product-detail"})

    assert len(reduced) <= 200_000
    assert parsed.find("nav") is None
    assert parsed.find("script") is None
    assert main is not None
    assert main.find("article", attrs={"class": "product"}) is not None
    assert "Widget Prime" in main.get_text(" ", strip=True)
    assert "Rubber outsole, reinforced toe cap." in main.get_text(" ", strip=True)
