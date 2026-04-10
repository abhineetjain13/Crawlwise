from __future__ import annotations

from unittest.mock import patch

from app.services.semantic_detail_extractor import extract_semantic_detail_data
from hypothesis import given, settings
from hypothesis import strategies as st


def test_extract_semantic_detail_data_empty_html_includes_aggregates_key():
    result = extract_semantic_detail_data("")

    assert result == {
        "sections": {},
        "specifications": {},
        "promoted_fields": {},
        "coverage": {},
        "aggregates": {},
        "table_groups": [],
    }


def test_extract_semantic_detail_data_does_not_treat_overview_as_review_noise():
    html = """
    <html>
      <body>
        <section>
          <h2>Overview</h2>
          <p>Lightweight upper with durable traction for daily trail runs.</p>
        </section>
      </body>
    </html>
    """

    result = extract_semantic_detail_data(html)

    assert result["sections"]["summary"] == "Lightweight upper with durable traction for daily trail runs."


def test_extract_semantic_detail_data_ignores_footer_definition_lists():
    html = """
    <html>
      <body>
        <article>
          <p><b>Reason for vacancy:</b> New headcount</p>
        </article>
        <footer>
          <dl>
            <dt>Company</dt>
            <dd>Leadership</dd>
          </dl>
        </footer>
      </body>
    </html>
    """

    result = extract_semantic_detail_data(html)

    assert result["specifications"]["reason_for_vacancy"] == "New headcount"
    assert "company" not in result["specifications"]


def test_extract_semantic_aggregates_skip_features_specs_when_specs_missing():
    html = """
    <html>
      <body>
        <h2>Highlights</h2>
        <p>Strong mission alignment and public impact.</p>
      </body>
    </html>
    """

    result = extract_semantic_detail_data(html)

    assert "features" in result["aggregates"]
    assert "features_specs" not in result["aggregates"]


def test_extract_semantic_aggregates_do_not_emit_features_specs_when_features_and_specs_exist():
    html = """
    <html>
      <body>
        <h2>Highlights</h2>
        <p>Strong mission alignment and public impact.</p>
        <ul>
          <li>Salary: $120,000</li>
        </ul>
      </body>
    </html>
    """

    result = extract_semantic_detail_data(html)

    assert "features" in result["aggregates"]
    assert "specifications" in result["aggregates"]
    assert "features_specs" not in result["aggregates"]


def test_extract_semantic_detail_data_strips_inline_style_noise_from_sections():
    html = """
    <html>
      <body>
        <section>
          <h2>Overview</h2>
          <style>
            .css-25meqj-description{max-width:75ch;margin:16px 0 0 0;}
          </style>
          <p>Available for you to view and test drive.</p>
        </section>
      </body>
    </html>
    """

    result = extract_semantic_detail_data(html)

    assert result["sections"]["summary"] == "Available for you to view and test drive."


def test_extract_semantic_detail_data_skips_contact_and_share_noise_sections():
    html = """
    <html>
      <body>
        <section>
          <h2>Contact Bolton Citroen</h2>
          <p>Click to reveal phone number</p>
          <p>This listing is powered by our dealer network partner, MOTORS.</p>
        </section>
        <section>
          <h2>Share</h2>
          <p>Share this ad on Facebook</p>
        </section>
        <section>
          <h2>Overview</h2>
          <p>One owner vehicle with full service history.</p>
        </section>
      </body>
    </html>
    """

    result = extract_semantic_detail_data(html)

    assert "contact_bolton_citroen" not in result["sections"]
    assert "share" not in result["sections"]
    assert result["sections"]["summary"] == "One owner vehicle with full service history."


# Property-based tests for Task 5: Enable unconditional tier 2 attribute collection
# Feature: extraction-pipeline-improvements

# Property 8: Semantic Extraction Invocation
@given(
    html=st.text(min_size=100, max_size=5000),
    url=st.just("https://example.com/product/123"),
    surface=st.sampled_from(["product_detail", "job_detail", "detail"]),
)
@settings(max_examples=100, deadline=None)
def test_semantic_extraction_invocation(html: str, url: str, surface: str):
    """Feature: extraction-pipeline-improvements, Property 8: Semantic Extraction Invocation.

    For any detail page (page_type="detail"), the extraction pipeline SHALL invoke
    semantic_detail_extractor exactly once, regardless of whether structured data
    (JSON-LD, __NEXT_DATA__) is present.

    Validates: Requirements 4.1, 4.2
    """
    from app.services.extract.service import extract_candidates

    with patch("app.services.extract.service.extract_semantic_detail_data") as mock_semantic:
        # Mock the semantic extractor to return a valid structure
        mock_semantic.return_value = {
            "sections": {},
            "specifications": {},
            "promoted_fields": {},
            "coverage": {},
            "aggregates": {},
            "table_groups": [],
        }

        # Call extract_candidates for a detail page
        extract_candidates(
            url=url,
            surface=surface,
            html=html,
            xhr_payloads=[],
            additional_fields=[],
            extraction_contract=None,
            resolved_fields=None,
            adapter_records=None,
        )

        # Verify semantic_detail_extractor was called exactly once
        assert mock_semantic.call_count == 1, f"Expected 1 call, got {mock_semantic.call_count}"


# Property 9: Product Attributes Extraction Completeness
@given(
    html_type=st.sampled_from(["dl_dd_dt", "table", "accordion"]),
)
@settings(max_examples=100, deadline=None)
def test_product_attributes_extraction_completeness(html_type: str):
    """Feature: extraction-pipeline-improvements, Property 9: Product Attributes Extraction Completeness.

    For any detail page HTML containing definition lists (dl/dt/dd), spec tables (table elements),
    or accordion content (details/summary), semantic_detail_extractor SHALL extract
    product_attributes as a non-empty flat dict[str, str].

    Validates: Requirements 4.3, 4.4, 4.5, 4.6
    """
    # Generate HTML based on type
    if html_type == "dl_dd_dt":
        html = """
        <html>
          <body>
            <dl>
              <dt>Material</dt>
              <dd>Cotton</dd>
              <dt>Color</dt>
              <dd>Blue</dd>
            </dl>
          </body>
        </html>
        """
    elif html_type == "table":
        html = """
        <html>
          <body>
            <table>
              <tr><td>Brand</td><td>Nike</td></tr>
              <tr><td>Size</td><td>Large</td></tr>
            </table>
          </body>
        </html>
        """
    else:  # accordion
        html = """
        <html>
          <body>
            <details>
              <summary>Specifications</summary>
              <p>Weight: 500g</p>
              <p>Dimensions: 10x20x30cm</p>
            </details>
          </body>
        </html>
        """

    result = extract_semantic_detail_data(html)

    # Verify specifications (product_attributes) is non-empty
    assert "specifications" in result
    assert isinstance(result["specifications"], dict)
    assert len(result["specifications"]) > 0, f"Expected non-empty specifications for {html_type}"


# Property 10: Product Attributes Output Persistence
@given(
    url=st.just("https://example.com/product/123"),
    surface=st.sampled_from(["product_detail", "job_detail", "detail"]),
)
@settings(max_examples=100, deadline=None)
def test_product_attributes_output_persistence(url: str, surface: str):
    """Feature: extraction-pipeline-improvements, Property 10: Product Attributes Output Persistence.

    For any detail page where semantic_detail_extractor returns non-empty product_attributes,
    the final extraction output SHALL contain a "product_attributes" key with those attributes.

    Validates: Requirement 4.7
    """
    from app.services.extract.service import extract_candidates

    # HTML with specifications
    html = """
    <html>
      <body>
        <dl>
          <dt>Material</dt>
          <dd>Cotton</dd>
          <dt>Color</dt>
          <dd>Blue</dd>
        </dl>
      </body>
    </html>
    """

    candidates, source_trace = extract_candidates(
        url=url,
        surface=surface,
        html=html,
        xhr_payloads=[],
        additional_fields=[],
        extraction_contract=None,
        resolved_fields=None,
        adapter_records=None,
    )

    # Verify product_attributes is in the output
    assert "product_attributes" in candidates, "Expected product_attributes in candidates"

    # Verify product_attributes contains the specifications
    product_attrs = candidates["product_attributes"]
    assert isinstance(product_attrs, list)
    assert len(product_attrs) > 0
    assert "value" in product_attrs[0]
    assert isinstance(product_attrs[0]["value"], dict)
    assert len(product_attrs[0]["value"]) > 0, "Expected non-empty product_attributes dict"
