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
