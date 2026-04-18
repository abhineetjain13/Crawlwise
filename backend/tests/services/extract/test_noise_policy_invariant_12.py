from __future__ import annotations

from bs4 import BeautifulSoup

from app.services.extract.noise_policy import (
    is_noisy_product_attribute_entry,
    sanitize_detail_field_value,
)
from app.services.extract.service import extract_candidates


def test_page_native_size_and_availability_labels_survive_detail_noise_filter() -> None:
    assert sanitize_detail_field_value("size", "Select size") == ("Select size", None)
    assert sanitize_detail_field_value("availability", "Availability") == (
        "Availability",
        None,
    )


def test_page_native_color_label_survives_detail_noise_filter() -> None:
    assert sanitize_detail_field_value("color", "Select color") == (
        "Select color",
        None,
    )


def test_noise_rules_still_reject_css_and_footer_chrome_context() -> None:
    soup = BeautifulSoup(
        """
        <html>
          <body>
            <footer class="site-footer">
              <a href="/stores">Check availability in store</a>
            </footer>
          </body>
        </html>
        """,
        "html.parser",
    )
    footer_link = soup.select_one("footer a")

    assert footer_link is not None
    assert is_noisy_product_attribute_entry(
        "material",
        "padding: 8px; margin: 0; display: block;",
    )
    assert is_noisy_product_attribute_entry(
        "stores",
        footer_link.get_text(" ", strip=True),
    )


def test_extract_surfaces_availability_label_instead_of_dropping_the_field() -> None:
    html = """
    <html>
      <body>
        <h1>Example Jacket</h1>
        <div class="availability">Availability</div>
      </body>
    </html>
    """

    candidates, _ = extract_candidates(
        "https://example.com/products/jacket",
        "ecommerce_detail",
        html,
        None,
        [],
    )

    assert "availability" in candidates, "Expected 'availability' field in candidates"
    assert len(candidates["availability"]) > 0, "Expected at least one availability candidate"
    assert candidates["availability"][0]["value"] == "Availability"


def test_untouched_pollution_rules_keep_rejecting_same_noise() -> None:
    assert sanitize_detail_field_value("title", "Add to cart")[0] is None
    assert sanitize_detail_field_value("brand", "Home > Designer")[0] is None
