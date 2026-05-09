from __future__ import annotations

from bs4 import BeautifulSoup

from app.services.extract.variant_dom_cues import (
    select_variant_nodes,
    variant_node_in_noise_context,
    variant_scope_roots,
)


def test_variant_scope_roots_fail_closed_without_product_scope() -> None:
    soup = BeautifulSoup(
        """
        <html>
          <body>
            <div class="page-tabs">
              <button>Overview</button>
              <button>Specifications</button>
            </div>
          </body>
        </html>
        """,
        "html.parser",
    )

    assert variant_scope_roots(soup) == []


def test_select_variant_nodes_does_not_scan_whole_page_on_scope_miss() -> None:
    soup = BeautifulSoup(
        """
        <html>
          <body>
            <nav>
              <a href="/overview">Overview</a>
              <a href="/reviews">Reviews</a>
            </nav>
          </body>
        </html>
        """,
        "html.parser",
    )

    assert select_variant_nodes(soup, "a[href]") == []


def test_variant_node_in_noise_context_detects_tab_reviews() -> None:
    soup = BeautifulSoup(
        """
        <main class="product-detail">
          <div class="tab-list reviews">
            <button>Black</button>
          </div>
        </main>
        """,
        "html.parser",
    )

    assert variant_node_in_noise_context(soup.select_one("button")) is True
