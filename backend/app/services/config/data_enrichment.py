from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


DATA_ENRICHMENT_STATUS_UNENRICHED = "unenriched"
DATA_ENRICHMENT_STATUS_PENDING = "pending"
DATA_ENRICHMENT_STATUS_RUNNING = "running"
DATA_ENRICHMENT_STATUS_ENRICHED = "enriched"
DATA_ENRICHMENT_STATUS_DEGRADED = "degraded"
DATA_ENRICHMENT_STATUS_FAILED = "failed"
DATA_ENRICHMENT_LLM_TASK = "data_enrichment_semantic"

DATA_ENRICHMENT_SKIP_RECORD_STATUSES = (
    DATA_ENRICHMENT_STATUS_ENRICHED,
    DATA_ENRICHMENT_STATUS_DEGRADED,
)
DATA_ENRICHMENT_JOB_TERMINAL_STATUSES = (
    DATA_ENRICHMENT_STATUS_ENRICHED,
    DATA_ENRICHMENT_STATUS_DEGRADED,
    DATA_ENRICHMENT_STATUS_FAILED,
)

ECOMMERCE_DETAIL_SURFACE = "ecommerce_detail"
DATA_ENRICHMENT_TAXONOMY_FILENAME = "google_product_category.txt"
DATA_ENRICHMENT_ATTRIBUTES_FILENAME = "google_product_data_attributes.json"
DATA_ENRICHMENT_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "enrichment"
DATA_ENRICHMENT_TAXONOMY_PATH = DATA_ENRICHMENT_DATA_DIR / DATA_ENRICHMENT_TAXONOMY_FILENAME
DATA_ENRICHMENT_ATTRIBUTES_PATH = DATA_ENRICHMENT_DATA_DIR / DATA_ENRICHMENT_ATTRIBUTES_FILENAME

DATA_ENRICHMENT_PROMPT_REGISTRY = {
    DATA_ENRICHMENT_LLM_TASK: {
        "response_type": "object",
        "system_file": "data_enrichment_semantic.system.txt",
        "user_file": "data_enrichment_semantic.user.txt",
    },
}


@dataclass(frozen=True, slots=True)
class DataEnrichmentSettings:
    max_source_records: int = 500
    max_concurrency: int = 3
    taxonomy_path: Path = DATA_ENRICHMENT_TAXONOMY_PATH
    attributes_path: Path = DATA_ENRICHMENT_ATTRIBUTES_PATH
    category_match_threshold: float = 0.42
    max_seo_keywords: int = 20
    llm_description_excerpt_chars: int = 300


data_enrichment_settings = DataEnrichmentSettings()
