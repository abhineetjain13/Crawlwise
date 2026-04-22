from __future__ import annotations

from bs4 import BeautifulSoup

from app.services.field_value_dom import (
    extract_heading_sections,
    extract_page_images,
    extract_selector_values,
    requested_content_extractability,
)


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


def test_extract_page_images_keeps_main_gallery_carousel_images_on_detail_pages() -> None:
    soup = BeautifulSoup(
        """
        <html>
          <body>
            <main>
              <section class="product-gallery carousel">
                <a href="/products/widget-prime?view=2">
                  <img src="/images/gallery-2.jpg" alt="Widget Prime side view" />
                </a>
              </section>
            </main>
          </body>
        </html>
        """,
        "html.parser",
    )

    images = extract_page_images(
        soup,
        "https://example.com/products/widget-prime",
        exclude_linked_detail_images=True,
        surface="ecommerce_detail",
    )

    assert images == ["https://example.com/images/gallery-2.jpg"]


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


def test_extract_page_images_filters_payment_svgs_outside_product_gallery() -> None:
    soup = BeautifulSoup(
        """
        <html>
          <body>
            <section class="secure-payment">
              <img src="https://cdn.example.com/assets/amex.svg" alt="American Express" />
              <img src="https://cdn.example.com/assets/paypal.svg" alt="PayPal" />
            </section>
            <main>
              <section class="product-gallery">
                <img src="https://cdn.example.com/products/widget-main.jpg?width=1200" alt="Widget Prime front view" />
              </section>
            </main>
          </body>
        </html>
        """,
        "html.parser",
    )

    images = extract_page_images(soup, "https://example.com/products/widget-prime")

    assert images == ["https://cdn.example.com/products/widget-main.jpg?width=1200"]


def test_extract_heading_sections_follows_aria_controls_panels() -> None:
    soup = BeautifulSoup(
        """
        <html>
          <body>
            <button aria-controls="materials-panel">Materials</button>
            <section id="materials-panel">
              <p>Full-grain leather upper with mesh lining.</p>
            </section>
          </body>
        </html>
        """,
        "html.parser",
    )

    sections = extract_heading_sections(soup)

    assert sections == {"Materials": "Full-grain leather upper with mesh lining."}


def test_extract_heading_sections_reads_details_summary_content() -> None:
    soup = BeautifulSoup(
        """
        <html>
          <body>
            <details>
              <summary>Description</summary>
              <div>Built for long mileage and wet-weather traction.</div>
            </details>
          </body>
        </html>
        """,
        "html.parser",
    )

    sections = extract_heading_sections(soup)

    assert sections == {"Description": "Built for long mileage and wet-weather traction."}


def test_extract_heading_sections_reads_nested_wrapped_accordion_content() -> None:
    soup = BeautifulSoup(
        """
        <html>
          <body>
            <div class="accordion-item">
              <button>Specifications</button>
              <div class="accordion-item__body">
                <div class="rich-content">
                  Rubber outsole with a reinforced toe cap.
                </div>
              </div>
            </div>
          </body>
        </html>
        """,
        "html.parser",
    )

    sections = extract_heading_sections(soup)

    assert sections == {
        "Specifications": "Rubber outsole with a reinforced toe cap."
    }


def test_extract_heading_sections_keeps_adjacent_heading_sections_bound_to_their_own_content() -> None:
    soup = BeautifulSoup(
        """
        <html>
          <body>
            <div class="product-specification">
              <h2 class="product-details-title">Product Specifications</h2>
              <table class="spec-table">
                <tbody>
                  <tr><td>Storage</td><td>Dry Place</td></tr>
                  <tr><td>Grade</td><td>Medicine Grade</td></tr>
                </tbody>
              </table>
              <h2 class="coy-details-title">Company Details</h2>
              <div class="seo-content">
                <div>Lyotex Lifesciences Private Limited manufactures botanical extracts.</div>
              </div>
              <div class="business-details">
                <div class="detail-row">
                  <div class="info-block">
                    <div class="info-rt">
                      <p>Business Type</p>
                      <p>Manufacturer, Supplier, Trading Company</p>
                    </div>
                  </div>
                  <div class="info-block">
                    <div class="info-rt">
                      <p>GST NO</p>
                      <p>27AAECL9071B1ZK</p>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </body>
        </html>
        """,
        "html.parser",
    )

    sections = extract_heading_sections(soup)

    assert sections["Product Specifications"] == "Storage Dry Place Grade Medicine Grade"
    assert sections["Company Details"].startswith(
        "Lyotex Lifesciences Private Limited manufactures botanical extracts."
    )
    assert "Business Type Manufacturer, Supplier, Trading Company" in sections["Company Details"]
    assert "GST NO 27AAECL9071B1ZK" in sections["Company Details"]


def test_extract_heading_sections_resolves_anchor_hash_accordion_panels() -> None:
    soup = BeautifulSoup(
        """
        <html>
          <body>
            <div id="accordion">
              <div class="card">
                <div role="tab" id="headingOne" class="card-header">
                  <h5 class="mb-0 accordianheading">
                    <a data-toggle="collapse" data-parent="#accordion" href="#collapseOne" aria-expanded="true" aria-controls="collapseOne">
                      Product Details
                    </a>
                  </h5>
                </div>
                <div id="collapseOne" role="tabpanel" aria-labelledby="headingOne" class="collapse show">
                  <div class="card-block">
                    <p><b>Material &amp; Care:</b><br>Premium Heavy Gauge Fabric</p>
                  </div>
                </div>
              </div>
              <div class="card">
                <div role="tab" id="headingTwo" class="card-header">
                  <h5 class="mb-0 accordianheading">
                    <a data-toggle="collapse" data-parent="#accordion" href="#collapseTwo" aria-expanded="false" aria-controls="collapseTwo">
                      Product Description
                    </a>
                  </h5>
                </div>
                <div id="collapseTwo" role="tabpanel" aria-labelledby="headingTwo" class="collapse">
                  <div class="card-block">
                    <p>Official Licensed Superman Oversized T-Shirt.</p>
                  </div>
                </div>
              </div>
              <div class="card">
                <div role="tab" id="headingArtist" class="card-header">
                  <h5 class="mb-0 accordianheading">
                    <a data-toggle="collapse" data-parent="#accordion" href="#collapseArtist" aria-expanded="false" aria-controls="collapseArtist">
                      Artist's Details
                    </a>
                  </h5>
                </div>
                <div id="collapseArtist" role="tabpanel" aria-labelledby="headingArtist" class="collapse">
                  <div class="card-block">
                    <p>Suit up with Justice League merchandise.</p>
                  </div>
                </div>
              </div>
            </div>
          </body>
        </html>
        """,
        "html.parser",
    )

    sections = extract_heading_sections(soup)

    assert sections["Product Details"] == "Material & Care: Premium Heavy Gauge Fabric"
    assert sections["Product Description"] == "Official Licensed Superman Oversized T-Shirt."
    assert sections["Artist's Details"] == "Suit up with Justice League merchandise."


def test_extract_heading_sections_skips_review_and_index_panels() -> None:
    soup = BeautifulSoup(
        """
        <html>
          <body>
            <button aria-controls="details-index">Check the details</button>
            <section id="details-index">
              <a href="#summary">Product summary</a>
              <a href="#specs">General Specifications</a>
              <a href="#manual">Owner's Manual</a>
            </section>
            <button aria-controls="reviews-panel">Reviews</button>
            <section id="reviews-panel">
              <p>Review this product</p>
            </section>
          </body>
        </html>
        """,
        "html.parser",
    )

    sections = extract_heading_sections(soup)

    assert sections == {}


def test_requested_content_extractability_ignores_arbitrary_heading_labels() -> None:
    soup = BeautifulSoup(
        """
        <html>
          <body>
            <section>
              <h2>Batman Wayne Industries</h2>
              <p>Relaxed fit cotton shirt with oversized graphic print.</p>
            </section>
            <section>
              <h2>Description</h2>
              <p>Garment dyed cotton with a camp collar.</p>
            </section>
          </body>
        </html>
        """,
        "html.parser",
    )

    extractability = requested_content_extractability(
        soup,
        surface="ecommerce_detail",
        requested_fields=None,
    )

    assert "batman_wayne_industries" not in extractability["extractable_fields"]
    assert extractability["section_fields"] == ["description"]


def test_requested_content_extractability_keeps_explicit_requested_section_labels() -> None:
    soup = BeautifulSoup(
        """
        <html>
          <body>
            <section>
              <h2>Features &amp; Benefits</h2>
              <p>NITROFOAM midsole with PUMAGRIP outsole.</p>
            </section>
          </body>
        </html>
        """,
        "html.parser",
    )

    extractability = requested_content_extractability(
        soup,
        surface="ecommerce_detail",
        requested_fields=["Features & Benefits"],
    )

    assert extractability["matched_requested_fields"] == ["features_benefits"]
    assert "features_benefits" in extractability["extractable_fields"]


def test_extract_heading_sections_does_not_map_action_labels_to_product_title() -> None:
    soup = BeautifulSoup(
        """
        <html>
          <body>
            <main>
              <h1>CONTRAST RIBBED T-SHIRT WITH RUFFLES</h1>
              <ul class="product-detail-actions product-detail-info__product-actions">
                <li class="product-detail-actions__action">
                  <button class="product-detail-size-guide-action product-detail-actions__action-button">
                    <span>Product Measurements</span>
                  </button>
                </li>
                <li class="product-detail-actions__action product-detail-actions__clevercare">
                  <button class="product-detail-actions__action-button">
                    Composition, care &amp; origin
                  </button>
                </li>
              </ul>
            </main>
            <div class="product-detail-composition product-detail-view__detailed-composition">
              <ul>
                <li class="product-detail-composition__item product-detail-composition__part">
                  <span class="product-detail-composition__part-name">OUTER SHELL</span>
                  <ul>
                    <li class="product-detail-composition__item product-detail-composition__area">
                      <span class="product-detail-composition__part-name">MAIN FABRIC</span>
                      <ul><li>96% cotton</li><li>4% elastane</li></ul>
                    </li>
                  </ul>
                </li>
              </ul>
            </div>
          </body>
        </html>
        """,
        "html.parser",
    )

    sections = extract_heading_sections(soup)

    assert sections == {
        "Composition": "OUTER SHELL: MAIN FABRIC: 96% cotton; 4% elastane"
    }


def test_extract_heading_sections_skips_non_material_fallback_text_in_composition_container() -> None:
    soup = BeautifulSoup(
        """
        <html>
          <body>
            <main><h1>Widget Prime</h1></main>
            <div class="product-detail-composition product-detail-view__detailed-composition">
              Delivery in 3-5 business days. See the size guide for measurements.
            </div>
          </body>
        </html>
        """,
        "html.parser",
    )

    sections = extract_heading_sections(soup)

    assert "Composition" not in sections


def test_extract_selector_values_skips_long_text_section_indexes() -> None:
    soup = BeautifulSoup(
        """
        <html>
          <body>
            <section id="specifications">
              <h2>Check the details</h2>
              <button>Product summary</button>
              <button>General Specifications</button>
              <button>Owner's Manual</button>
            </section>
          </body>
        </html>
        """,
        "html.parser",
    )

    values = extract_selector_values(
        soup,
        "#specifications",
        "specifications",
        "https://example.com/products/widget-prime",
    )

    assert values == []
