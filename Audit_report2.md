The core of your struggle stems from a blurring of boundaries between system provenance (manifests/HTML), canonical data, and unverified attribute data. Currently, your system extracts everything into a massive pool of candidates, tries to deterministically filter them, and then relies on a flat LLM prompt (field_cleanup_review) to figure out what is valuable. This inevitably leads to either aggressive data loss (via deterministic pruning) or massive noise (via LLM hallucination/over-extraction).Here is the actionable audit and architectural blueprint to solve this trade-off.
A. Schema Isolation Audit: The "Dual-Schema" Pattern
Current Flaw:
In models/crawl.py and schemas/crawl.py, you use data, raw_data, discovered_data, and source_trace.
Currently, discovered_data is acting as a dumping ground for both unverified product attributes (e.g., water_resistance: "50m") AND massive structural website payloads (e.g., __NEXT_DATA__, json_ld). Your _clean_for_display method tries to patch this by dropping specific keys (next_data, adapter_data), but it is a leaky abstraction.
The Solution:
Implement a strict Triage Schema using Pydantic. Separate "Manifest/Provenance Data" (useful for debugging/selectors) from "Unverified Domain Data" (useful for the user to review and promote).
code
from pydantic import BaseModel, Field, ConfigDictclass UnverifiedAttribute(BaseModel):
    key: str
    value: Any
    confidence_score: int = Field(ge=1, le=10) # Allows UI to filter noise slider
    source: str

class CanonicalData(BaseModel):
    # Strict schema based on canonical_schemas.json
    model_config = ConfigDict(extra="ignore")
    title: str | None = None
    price: float | None = None
    # ... other strict fields

class RecordStagingSchema(BaseModel):
    """The unified boundary for the extraction pipeline."""
    canonical: CanonicalData
    review_bucket: list[UnverifiedAttribute] = Field(default_factory=list)
    
    # Keep massive JSON-LD/Next.js blobs OUT of the review bucket.
    # Store them here ONLY for debugging/provenance, never for user review.
    manifest_trace: dict[str, Any] = Field(default_factory=dict, exclude=True)
Why this works: The UI now only reads from review_bucket. Because the bucket requires a confidence_score, your frontend can implement a "Noise Slider". If the user wants strict data, they set the slider to 9-10. If they are missing data, they lower the slider to 3-4 to see the noisier extractions without polluting the primary canonical view.
B. Normalization Prompt Review: The LLM as a Router
Current Flaw:
In field_cleanup_review.system.txt, your prompt says:
"preserve as much legible, user-valuable detail as the page clearly supports... Use concise, stable field names in snake_case. Each key must map to an object..."
This prompt asks the LLM to output a flat JSON object where canonical fields (title, price) are mixed at the exact same level as hallucinated or noisy fields (shipping_promo, button_text). The LLM has no concept of "strict vs. unverified".
The Solution:
Rewrite the prompt to enforce the Dual-Schema routing directly at the LLM level. Give the LLM the canonical schema, and explicitly tell it to dump everything else into the review bucket.
New field_cleanup_review.system.txt:
code
Text
You are a strict data extraction router. Your job is to extract data from the provided evidence and route it into two exact buckets: "canonical" and "review_bucket".
You are a strict data extraction router. Your job is to extract data from the provided evidence and route it into two exact buckets: "canonical" and "review_bucket".{
  "canonical": {
    // ONLY use fields from the provided Canonical Schema. 
    // Do not invent keys here. If a value is missing, omit it.
  },
  "review_bucket": [
    // Put ALL OTHER meaningful specifications, features, or attributes here.
    // Ignore site navigation, marketing promos, and UI text.
    {
      "key": "snake_case_name",
      "value": "extracted value",
      "confidence": <1-10 integer based on how likely this is a permanent attribute of the entity>,
      "source": "source label"
    }
  ]
}

Rules for the Review Bucket:
- A confidence of 9-10 means this is a definitive product specification (e.g., dimensions, materials, ISBN).
- A confidence of 1-4 means this is contextual or potentially noisy (e.g., "bestseller_rank", "shipping_note").
- Drop values with 0 confidence.
C. Workflow Efficiency: Managing Dual-State Data
Current Flaw:
In crawl_service.py (_extract_detail), you merge candidates, run deterministic filters, then optionally call the LLM, and finally stuff everything into db_record.discovered_data. The state blob is gigantic, slowing down API responses and bloating SQLite/Postgres.
The Solution:
Prune Before Extracting: You have a great start with spa_pruner.py. Expand this. Before sending manifest.next_data or candidate_evidence to the LLM, aggressively drop known noise keys (theme, tracking, analytics) natively in Python.
Asynchronous Promotion: When a user promotes a field via /api/review/{run_id}/save, do not just update the field_mapping. Fire a background task that iterates over the review_bucket of all records in that run_id, extracts the matching key, moves it to the canonical JSONB column, and deletes it from the review_bucket.
Lazy-Load Manifests: Stop returning source_trace and discovered_data (the raw Next.js/HTML blobs) in the standard /api/crawls/{run_id}/records endpoint. These payloads can be megabytes in size. Create a specific endpoint (/api/records/{id}/provenance) that fetches this heavy data only when a developer clicks "View Source Trace" in the UI.
D. Automated Evaluation: Testing Architecture
To safely iterate on the LLM prompt and Python pruning scripts without regressing, you need a programmatic test harness.
Create a tests/evaluations/ directory using your existing Pytest setup.
1. The Golden Dataset:
Create tests/evaluations/golden_data.json. Hand-curate 20 difficult URLs (e.g., heavily Javascript-rendered e-commerce pages, messy job boards).
code
JSON
[
  {
    "url": "https://example.com/messy-product",
    "expected_canonical": {"title": "Widget X", "price": 49.99},
    "expected_review_keys": ["water_resistance", "battery_life"],
    "must_not_contain_keys": ["add_to_cart", "related_products"]
  }
]
2. The Pytest Architecture:
Write a parameterized Pytest fixture that runs the pipeline on offline-cached HTML (to save time/money).
code
Python
import pytest
from app.services.extract.service import extract_candidates

@pytest.mark.parametrize("item", load_golden_data())
async def test_extraction_balance(item):
    # 1. Run Pipeline (using offline cached HTML)
    html = load_cached_html(item["url"])
    result = await run_test_pipeline(html) # Mocks LLM call
    
    canonical = result["canonical"]
    review_bucket = result["review_bucket"]
    review_keys = [r["key"] for r in review_bucket]
    
    # 2. Measure Canonical Recall (Data Loss Metric)
    for key, expected_val in item["expected_canonical"].items():
        assert canonical.get(key) == expected_val, f"Data Loss: Missing canonical {key}"
        
    # 3. Measure Review Bucket Recall (Valuable Extra Data)
    for expected_key in item["expected_review_keys"]:
        assert expected_key in review_keys, f"Data Loss: Over-pruned {expected_key}"
        
    # 4. Measure Noise (Precision Metric)
    for bad_key in item["must_not_contain_keys"]:
        assert bad_key not in review_keys, f"Noise Retention: Leaked {bad_key}"
        
    # 5. Measure Overall Noise Ratio
    # If the LLM generates 50 extra keys but we only expected 5, our prompt is too loose.
    noise_ratio = len(review_keys) / len(item["expected_review_keys"])
    assert noise_ratio < 3.0, f"Too much noise! Ratio: {noise_ratio}"
3. LLM-as-a-Judge (Optional but highly recommended):
For deeper testing, write a script that sends the outputted review_bucket back to a cheaper LLM (e.g., Llama 3 8B via Groq) with the prompt: "Score this JSON from 0.0 to 1.0 based on how much UI/navigation noise is present." Assert in Pytest that noise_score < 0.2. This allows agents to autonomously tweak the extraction prompts and immediately see if they triggered a collapse in data quality.