from app.services.record_export_service import _record_to_markdown
from app.models.crawl import CrawlRecord


def test_record_to_markdown_does_not_repeat_scalar_field_as_semantic_section() -> None:
    row = CrawlRecord(
        id=1,
        source_url="https://example.com/item",
        data={"title": "Example", "brand": "Acme"},
        source_trace={"semantic": {"sections": {"brand": "Semantic brand section"}}},
    )

    markdown = _record_to_markdown(row)

    assert "- **Brand:** Acme" in markdown
    assert "## Brand" not in markdown


def test_record_to_markdown_renders_listing_fallback_page_markdown_without_internal_field_labels() -> None:
    row = CrawlRecord(
        id=1,
        source_url="https://example.com/jobs",
        data={
            "title": "Jobs - Example",
            "page_markdown": "# Jobs - Example\n\n## [Executive Assistant](https://example.com/jobs/executive-assistant)",
            "record_type": "page_fallback",
        },
        source_trace={"type": "listing_fallback"},
    )

    markdown = _record_to_markdown(row)

    assert "## [Executive Assistant](https://example.com/jobs/executive-assistant)" in markdown
    assert "Record type" not in markdown
    assert "Page markdown" not in markdown


def test_record_to_markdown_does_not_repeat_source_url_in_fields() -> None:
    row = CrawlRecord(
        id=1,
        source_url="https://example.com/jobs",
        data={
            "title": "Medical Assistant",
            "source_url": "https://example.com/jobs",
            "url": "https://example.com/jobs#9202644178148_1",
            "job_id": "9202644178148_1",
        },
        source_trace={},
    )

    markdown = _record_to_markdown(row)

    assert "Source: <https://example.com/jobs>" in markdown
    assert "Record URL: <https://example.com/jobs#9202644178148_1>" in markdown
    assert "- **Source url:**" not in markdown
