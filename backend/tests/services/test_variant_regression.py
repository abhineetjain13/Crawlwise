from __future__ import annotations

from bs4 import BeautifulSoup

from app.services.extract.detail_dom_extractor import extract_variants_from_dom
from app.services.extract.variant_record_normalization import normalize_variant_record


def _dom_variants(html: str, page_url: str = "https://example.com/pdp/item") -> dict[str, object]:
    return extract_variants_from_dom(
        BeautifulSoup(html, "html.parser"),
        page_url=page_url,
    )


def test_dom_variant_extraction_does_not_use_whole_page_nav_as_color() -> None:
    record = _dom_variants(
        """
        <html>
          <body>
            <nav class="tabs color-selector">
              <a href="/pl/ceiling-lights">Overview</a>
              <a href="/pl/ceiling-lights/reviews">Reviews</a>
              <a href="/pl/ceiling-lights/specifications">Specifications</a>
            </nav>
          </body>
        </html>
        """,
        page_url="https://www.lowes.com/pd/minka-lavery-light/123",
    )

    assert record == {}


def test_dom_variant_extraction_filters_review_and_share_controls() -> None:
    record = _dom_variants(
        """
        <main class="product-detail">
          <fieldset class="color-selector">
            <legend>Color</legend>
            <button aria-label="Black"></button>
            <button aria-label="Silver"></button>
            <button>Share</button>
            <button>Print</button>
            <button>2 reviews</button>
            <button>Show More</button>
          </fieldset>
        </main>
        """,
        page_url="https://www.bhphotovideo.com/c/product/123/camera.html",
    )

    colors = {row.get("color") for row in record.get("variants", [])}
    assert colors == {"Black", "Silver"}
    assert colors.isdisjoint({"Share", "Print", "2 reviews", "Show More"})


def test_dom_variant_extraction_filters_protection_plan_controls() -> None:
    record = _dom_variants(
        """
        <main class="product-detail">
          <fieldset class="color-selector">
            <legend>Color</legend>
            <button>Walnut</button>
            <button>Oak</button>
            <button>5 Year Protection Plan</button>
            <button>See Details Details</button>
          </fieldset>
        </main>
        """,
        page_url="https://www.wayfair.com/furniture/pdp/table.html",
    )

    colors = {row.get("color") for row in record.get("variants", [])}
    assert colors == {"Walnut", "Oak"}


def test_normalize_variant_record_drops_long_condition_prose() -> None:
    record: dict[str, object] = {
        "variants": [
            {
                "condition": (
                    "Excellent screen with minor signs of wear visible only "
                    "from close inspection"
                )
            },
            {
                "condition": (
                    "Fair body with visible scratches and marks from daily "
                    "use over time"
                )
            },
        ]
    }

    normalize_variant_record(record)

    assert "variants" not in record


def test_normalize_variant_record_strips_dom_validation_marker() -> None:
    record: dict[str, object] = {
        "variants": [{"color": "Black", "_validated": True}],
    }

    normalize_variant_record(record)

    assert record["variants"] == [{"color": "Black"}]
