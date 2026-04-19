from __future__ import annotations

from bs4 import BeautifulSoup

from app.services.field_value_dom import extract_page_images


def test_extract_page_images_excludes_linked_job_detail_images_by_surface() -> None:
    soup = BeautifulSoup(
        """
        <html>
          <body>
            <a href="/careers/software-engineer">
              <img src="/images/job-card.jpg" />
            </a>
            <img src="/images/hero.jpg" />
          </body>
        </html>
        """,
        "html.parser",
    )

    images = extract_page_images(
        soup,
        "https://example.com/jobs",
        exclude_linked_detail_images=True,
        surface="job_detail",
    )

    assert images == ["https://example.com/images/hero.jpg"]


def test_extract_page_images_excludes_linked_product_detail_images_by_surface() -> None:
    soup = BeautifulSoup(
        """
        <html>
          <body>
            <a href="/products/widget-prime">
              <img src="/images/product-card.jpg" />
            </a>
            <img src="/images/gallery.jpg" />
          </body>
        </html>
        """,
        "html.parser",
    )

    images = extract_page_images(
        soup,
        "https://example.com/collections/widgets",
        exclude_linked_detail_images=True,
        surface="ecommerce_detail",
    )

    assert images == ["https://example.com/images/gallery.jpg"]
