from __future__ import annotations

from app.services.semantic_detail_extractor import extract_semantic_detail_data


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
