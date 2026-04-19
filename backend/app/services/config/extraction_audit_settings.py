from __future__ import annotations

from types import MappingProxyType

from pydantic import Field
from pydantic_settings import BaseSettings

from app.services.config.runtime_settings import _settings_config


class ExtractionAuditSettings(BaseSettings):
    model_config = _settings_config(env_prefix="CRAWLER_EXTRACTION_")

    listing_card_group_min_size: int = 2
    listing_card_group_min_signal_ratio: float = 0.45
    listing_card_group_sample_size: int = 30
    listing_card_substantial_text_min_chars: int = 40
    listing_card_multi_element_min_children: int = 2
    listing_card_max_regex_input_chars: int = 500
    listing_card_repeated_link_root_max_depth: int = 4
    listing_card_min_path_segments: int = 2
    listing_card_job_title_min_chars: int = 4
    listing_card_listing_title_min_chars: int = 3
    listing_card_job_metadata_text_max_chars: int = 120
    listing_card_job_metadata_salary_max_chars: int = 40
    listing_card_job_company_line_max_chars: int = 60
    listing_card_job_company_suffix_max_chars: int = 40
    listing_card_job_location_line_max_chars: int = 80
    listing_card_color_label_max_chars: int = 40
    listing_card_product_url_scan_max_depth: int = 6
    listing_card_product_url_scan_max_list_items: int = 40
    listing_card_commerce_strong_signal_score: float = 1.0
    listing_card_commerce_partial_signal_score: float = 0.5
    listing_card_job_strong_signal_score: float = 1.0
    listing_card_job_partial_signal_score: float = 0.6
    listing_card_generic_media_signal_score: float = 1.0
    listing_card_generic_heading_signal_score: float = 0.5
    listing_card_generic_text_signal_score: float = 0.4
    json_listing_search_max_depth: int = 5
    json_listing_alias_max_depth: int = 4
    json_listing_default_max_records: int = 100
    json_candidate_array_sample_size: int = 5
    json_candidate_title_score: int = 3
    json_candidate_url_score: int = 3
    json_candidate_job_score: int = 4
    json_candidate_commerce_score: int = 2
    json_alias_visit_list_limit: int = 40
    json_image_list_limit: int = 20
    source_parser_datalayer_field_weights: dict[str, int] = Field(
        default_factory=lambda: {
            "price": 3,
            "sale_price": 2,
            "discount_amount": 1,
            "discount_percentage": 1,
            "price_currency": 2,
            "availability": 2,
            "category": 1,
            "google_product_category": 1,
        }
    )
    source_parser_embedded_blob_max_depth: int = 5
    source_parser_embedded_blob_list_sample_size: int = 5
    source_parser_embedded_blob_strong_signal_threshold: int = 2
    source_parser_embedded_blob_supporting_signal_threshold: int = 1
    source_parser_embedded_blob_strong_only_threshold: int = 3
    source_parser_embedded_blob_weak_signal_threshold: int = 1
    source_parser_previous_heading_limit: int = 6


extraction_audit_settings = ExtractionAuditSettings()
SOURCE_PARSER_DATALAYER_FIELD_WEIGHTS = MappingProxyType(
    extraction_audit_settings.source_parser_datalayer_field_weights
)

__all__ = [
    "ExtractionAuditSettings",
    "SOURCE_PARSER_DATALAYER_FIELD_WEIGHTS",
    "extraction_audit_settings",
]
