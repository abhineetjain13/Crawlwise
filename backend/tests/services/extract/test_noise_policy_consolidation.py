from __future__ import annotations

from bs4 import BeautifulSoup

from app.services.extract.noise_policy import (
    contains_low_quality_merge_token,
    field_value_contains_noise,
    is_noise_container,
    is_noisy_product_attribute_entry,
    is_social_url,
    sanitize_detail_field_value,
)


def test_contains_low_quality_merge_token_preserves_existing_noise_classification() -> None:
    assert contains_low_quality_merge_token("Review our privacy policy before checkout")
    assert not contains_low_quality_merge_token("Merino wool upper with cushioned sole")


def test_field_value_contains_noise_uses_consolidated_title_and_brand_rules() -> None:
    assert field_value_contains_noise("title", "Search Results")
    assert field_value_contains_noise("brand", "Cookie settings")
    assert not field_value_contains_noise("brand", "Allbirds")


def test_sanitize_detail_field_value_uses_common_and_field_specific_pollution_rules() -> None:
    assert sanitize_detail_field_value("title", "Add to cart")[0] is None
    assert sanitize_detail_field_value("brand", "Home > Designer")[1] == "detail_field_noise"
    assert sanitize_detail_field_value("availability", "In stock") == ("In stock", None)


def test_is_noisy_product_attribute_entry_uses_consolidated_product_attribute_rules() -> None:
    assert is_noisy_product_attribute_entry(
        "shipping_policy",
        "Download our app and review our shipping policy.",
    )
    assert is_noisy_product_attribute_entry(
        "material",
        "padding: 8px; margin: 0; display: block;",
    )
    assert not is_noisy_product_attribute_entry("material", "100% cotton")


def test_noise_container_and_social_rules_use_config_backed_data() -> None:
    soup = BeautifulSoup(
        "<footer><section><h2>Contact</h2><p>Footer copy</p></section></footer>",
        "html.parser",
    )
    heading = soup.find("h2")

    assert is_noise_container(heading)
    assert is_social_url("https://www.instagram.com/example/")
    assert not is_social_url("https://example.com/products/widget")
