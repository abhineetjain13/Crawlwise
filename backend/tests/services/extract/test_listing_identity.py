from __future__ import annotations

from app.services.extract.listing_identity import merge_record_sets_on_identity


def test_merge_uses_strong_identity_key_match() -> None:
    primary = [{"title": "A", "sku": "SKU-1", "url": ""}]
    supplemental = [[{"title": "Other", "sku": "SKU-1", "url": "https://example.com/p/1"}]]

    merged = merge_record_sets_on_identity(primary, supplemental)

    assert merged[0]["url"] == "https://example.com/p/1"


def test_merge_backfills_url_by_unique_title_when_identity_missing() -> None:
    primary = [{"title": "Campera PackLITE para hombre", "sku": "849355_70", "url": ""}]
    supplemental = [
        [{"title": "Campera PackLITE para hombre", "url": "https://example.com/p/849355_70"}]
    ]

    merged = merge_record_sets_on_identity(primary, supplemental)

    assert merged[0]["url"] == "https://example.com/p/849355_70"


def test_merge_does_not_backfill_when_title_is_ambiguous() -> None:
    primary = [
        {"title": "Heart Charm Key Fob", "sku": "A-1", "url": ""},
        {"title": "Heart Charm Key Fob", "sku": "A-2", "url": ""},
    ]
    supplemental = [[{"title": "Heart Charm Key Fob", "url": "https://example.com/p/fob"}]]

    merged = merge_record_sets_on_identity(primary, supplemental)

    assert merged[0]["url"] == ""
    assert merged[1]["url"] == ""


def test_merge_does_not_override_existing_url_on_backfill_path() -> None:
    primary = [{"title": "Existing URL Product", "sku": "SKU-2", "url": "https://example.com/original"}]
    supplemental = [[{"title": "Existing URL Product", "url": "https://example.com/new"}]]

    merged = merge_record_sets_on_identity(primary, supplemental)

    assert merged[0]["url"] == "https://example.com/original"


def test_merge_rejects_noisy_brand_candidates_via_field_decision_engine() -> None:
    primary = [{"title": "A", "sku": "SKU-1", "brand": ""}]
    supplemental = [[{"title": "A", "sku": "SKU-1", "brand": "Home privacy policy sign in"}]]

    merged = merge_record_sets_on_identity(primary, supplemental)

    assert merged[0]["brand"] == ""
