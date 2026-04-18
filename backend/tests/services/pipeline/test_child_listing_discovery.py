from __future__ import annotations

from bs4 import BeautifulSoup

from app.services.discover import (
    discover_child_listing_candidate,
    discover_child_listing_candidate_from_soup,
    looks_like_category_tile_listing,
)


def test_child_listing_discovery_skips_nav_and_footer_anchors() -> None:
    html = """
    <html>
      <body>
        <nav class="site-nav">
          <a href="/women">Women</a>
        </nav>
        <main>
          <section class="tiles">
            <a href="/women/shoes">Women's shoes</a>
          </section>
        </main>
        <footer class="site-footer">
          <a href="/women/sale">Sale</a>
        </footer>
      </body>
    </html>
    """

    page_url = "https://example.com/women"
    soup = BeautifulSoup(html, "html.parser")

    assert discover_child_listing_candidate_from_soup(soup, page_url=page_url) == (
        "https://example.com/women/shoes"
    )
    assert discover_child_listing_candidate(html, page_url=page_url) == (
        "https://example.com/women/shoes"
    )


def test_category_tile_listing_classifier_keeps_existing_shape_heuristic() -> None:
    records = [
        {
            "title": "Boots icon tile",
            "url": "https://example.com/women/boots",
            "image_url": "data:image/png;base64,abc",
        },
        {
            "title": "Flats icon tile",
            "url": "https://example.com/women/flats",
            "image_url": "https://example.com/icon.png",
        },
    ]

    assert looks_like_category_tile_listing(records)
