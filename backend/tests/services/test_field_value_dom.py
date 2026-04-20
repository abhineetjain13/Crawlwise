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


def test_extract_page_images_dedupes_cdn_resized_variants_and_keeps_highest_resolution() -> None:
    soup = BeautifulSoup(
        """
        <html>
          <body>
            <img src="https://cdn.example.com/products/widget.jpg?width=100&height=100" />
            <img src="https://cdn.example.com/products/widget.jpg?width=1200&height=1200" />
            <img src="https://cdn.example.com/products/widget_200x200.jpg" />
            <img src="https://cdn.example.com/products/widget_alt.jpg?width=900" />
          </body>
        </html>
        """,
        "html.parser",
    )

    images = extract_page_images(soup, "https://example.com/products/widget")

    assert images == [
        "https://cdn.example.com/products/widget.jpg?width=1200&height=1200",
        "https://cdn.example.com/products/widget_alt.jpg?width=900",
    ]


def test_extract_page_images_preserves_non_resize_query_params_when_deduping() -> None:
    soup = BeautifulSoup(
        """
        <html>
          <body>
            <img src="https://cdn.example.com/products/widget.jpg?variant=red&width=200" />
            <img src="https://cdn.example.com/products/widget.jpg?variant=blue&width=200" />
          </body>
        </html>
        """,
        "html.parser",
    )

    images = extract_page_images(soup, "https://example.com/products/widget")

    assert images == [
        "https://cdn.example.com/products/widget.jpg?variant=red&width=200",
        "https://cdn.example.com/products/widget.jpg?variant=blue&width=200",
    ]


def test_extract_page_images_prefers_gallery_media_and_filters_tracking_assets() -> None:
    soup = BeautifulSoup(
        """
        <html>
          <body>
            <section class="product-gallery">
              <picture>
                <source srcset="https://cdn.example.com/products/widget-main.jpg?width=1200 1200w" />
                <img src="https://cdn.example.com/products/widget-main.jpg?width=640" alt="Widget Prime front view" width="640" height="640" />
              </picture>
              <img src="https://cdn.example.com/products/widget-side.jpg?width=900" alt="Widget Prime side view" width="600" height="600" />
            </section>
            <img src="https://cdn.example.com/tracking/pixel.gif" alt="tracking pixel" width="1" height="1" />
            <img src="https://cdn.example.com/assets/logo.png" alt="Brand logo" width="120" height="40" />
          </body>
        </html>
        """,
        "html.parser",
    )

    images = extract_page_images(soup, "https://example.com/products/widget-prime")

    assert images == [
        "https://cdn.example.com/products/widget-main.jpg?width=1200",
        "https://cdn.example.com/products/widget-side.jpg?width=900",
    ]
