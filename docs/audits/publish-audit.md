I now have the full picture of all layers. Here is the complete audit.

Full Data Flow Diagram
text
[CrawlRun.settings / CSV input]
         │
         ▼
crawl_ingestion_service.py
  build_csv_crawl_payload() / prepare_crawl_create_payload()
  → create_crawl_run()  →  dispatch_run()
         │
         ▼
pipeline/core.py  (49KB god-file)
  process_url(url, config: URLProcessingConfig)
    ├─ crawl_fetch_runtime.py  → AcquisitionResult (html, dom, network_payloads)
    ├─ detail_extractor.py     → list[dict]  (raw extraction output, _-prefixed keys)
    ├─ publish/verdict.py      → VERDICT_*  string
    └─ publish/metrics.py      → url_metrics dict
         │
         ▼
pipeline/persistence.py
  persist_acquisition_artifacts()   → artifact_store.py  → local FS (runs/{id}/pages/{url_hash}.*)
  persist_extracted_records()
    ├─ _record_identity_key(source_url)  → sha256[:16] dedup check
    ├─ SELECT existing url_identity_key  → skip duplicates within run
    ├─ _build_source_trace()             → full provenance dict
    └─ INSERT CrawlRecord (ORM)          → Postgres
         │
         ▼
record_export_service.py
  export_records_for_run() / export_records_as_csv() / build_webhook_payload()
    ├─ CSV (StreamingResponse with csv.writer)
    ├─ JSON (list[dict] response)
    └─ Webhook (HTTP POST via httpx)
         │
         ▼
artifact_store.py (HTML/JSON/PNG)
  Path(settings.artifacts_dir)/runs/{run_id}/pages/{url_hash}.html
  Path(settings.artifacts_dir)/runs/{run_id}/pages/{url_hash}.browser.json
  Path(settings.artifacts_dir)/runs/{run_id}/pages/{url_hash}.browser.png
Q1 — What Formats Does record_export_service.py Support?
Three export formats: CSV streaming, JSON list, and outbound webhook (HTTP POST). There is no direct DB write in the export service — writes happen upstream in pipeline/persistence.py. The formats are:

Format	Function	Mechanism
CSV	export_records_as_csv / stream_records_as_csv	csv.DictWriter → StreamingResponse (async generator), field order driven by canonical_requested_fields
JSON	export_records_for_run / build_export_payload	Plain list[dict] response; public fields filtered via public_record_data_for_surface
Webhook	dispatch_webhook_delivery / build_webhook_payload	httpx.AsyncClient.post() with HMAC-SHA256 signature header (X-Crawlwise-Signature); retry logic with exponential backoff
There is no S3 push, no Parquet/Arrow output, and no streaming DB write in the export layer. The webhook is the only outbound delivery path.

Notable gap: CSV streaming writes are not chunked by page — the entire CrawlRecord table for a run is loaded into memory via session.scalars(select(CrawlRecord).where(run_id=...)) before the async generator yields rows. For large runs this is a memory risk.

Q2 — Does artifact_store.py Abstract a Storage Backend?
No — it is hardcoded to the local filesystem. Every function calls Path(settings.artifacts_dir) directly and uses Path.write_text, Path.write_bytes, shutil.copyfile. There is no abstraction interface, no StorageBackend protocol, and no conditional S3/GCS path.

The path scheme is deterministic: {artifacts_dir}/runs/{run_id}/pages/{sha256(url)[:16]}.{suffix}. This means:

No remote storage — artifacts_dir must be on a volume mounted to every worker process

No content-addressable dedup — a re-run of the same URL writes a new file at the same path, silently overwriting the previous one

No presigned URL generation — artifact paths returned to callers are absolute local paths (e.g. /data/artifacts/runs/42/pages/a3f9c12d.html), not accessible to API consumers directly

Q3 — What Is pipeline/ Responsible For?
pipeline/ is the per-URL crawl-and-extract execution layer, not a scheduler or ETL pipeline in the traditional sense. It is the core processing loop that turns a URL + URLProcessingConfig into persisted CrawlRecord rows.

File	Role
core.py (49KB)	God-file: orchestrates fetch → extract → verdict → persist for one URL; contains process_url, _process_url_with_acquisition, _run_extraction_attempt, _finalize_url_result
persistence.py	DB + artifact write logic; persist_extracted_records, persist_acquisition_artifacts
types.py	URLProcessingConfig, URLProcessingResult, RecordWriter Protocol
extraction_retry_decision.py	Decides whether to re-attempt extraction with a different engine (browser vs HTTP); should_retry_with_browser, extraction_warrants_dom_retry
direct_record_fallback.py	Fallback path when extraction yields zero records — tries a simpler direct selector-only pass
runtime_helpers.py	Small utilities: timing, run-state mutation, logging helpers
pipeline/core.py at 49KB is the next god-file that needs decomposition — it handles URL normalization, acquisition orchestration, extraction loop, retry decision, fallback triggering, verdict computation, and persistence coordination all in one file.

Q4 — Is There Deduplication Logic Before Records Are Written?
Yes, but only within a single run, and only on source_url identity. The dedup in pipeline/persistence.py:

python
def _record_identity_key(source_url: str) -> str | None:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
    # full SHA256, not truncated — different from artifact_store which uses [:16]
Before inserting, persist_extracted_records queries:

sql
SELECT url_identity_key FROM crawl_records
WHERE run_id = :run_id AND url_identity_key IN (:candidate_keys)
If a matching key exists in the same run, the record is skipped. Cross-run dedup does not exist — re-running the same URL set in a new CrawlRun will produce duplicate CrawlRecord rows for the same product URLs. The identity key is sha256(source_url), so product identity is URL-based, not content-based (no title+price+SKU fingerprint).

Additionally, publish/metadata.py contains refresh_record_commit_metadata which overwrites field values on existing records when a user commits a correction — this is a separate, non-deduplicated update path that bypasses the identity key check.

Q5 — Are Writes Idempotent?
Within a run: yes (URL-identity dedup). Across runs: no. The specific risks:

A re-run with a new CrawlRun.id inserts new CrawlRecord rows for the same product URLs with no cross-run check

artifact_store.py overwrites local files silently (same path = same content replaced)

Webhook delivery has exponential backoff retry but no delivered-once guarantee — a timeout on the receiver side after the POST body is received will cause a re-delivery

save_domain_memory in domain_memory_service.py is upsert-based (find existing → update), so selector memory writes are idempotent

Q6 — What Is the Data Contract Between Extraction Output and Export Input? Is It Typed?
The contract is an untyped dict[str, object] throughout. Extraction output (detail_extractor → pipeline/core.py) is a list[dict] where keys are field names plus _-prefixed internal keys (_source, _confidence, _field_sources, _selector_traces, _self_heal, _field_repair, _manifest_trace, _review_bucket, _semantic, _rejected_public_fields).

This dict is:

Passed to _build_source_trace() — consumes _-prefixed keys to build provenance

Filtered by public_record_data_for_surface() — strips _-prefixed keys, applies surface field allowlist

Written to CrawlRecord.data (JSONB column) — no schema enforcement at write time

Read back in record_export_service.py as dict(record.data or {}) — no schema enforcement at read time

Written to CSV/JSON/webhook — field order is canonical_requested_fields(surface) but missing fields silently produce empty CSV columns

pipeline/types.py defines URLProcessingResult.records: list[dict] — the only typed boundary is the wrapper dataclass, not the record dict contents. RecordWriter is a structural Protocol with write_record(record: dict[str, Any]) → Any — it accepts anything.

Q7 — Proposed Typed Schema, Idempotency Key Strategy, and Storage Abstraction
Typed ExportRecord Schema
python
# services/export/schema.py

from pydantic import BaseModel, Field, model_validator
from typing import Any

class FieldProvenance(BaseModel):
    status: str  # "found" | "missing" | "fallback"
    value: str
    sources: list[str]
    selector_trace: dict[str, Any] | None = None

class ExtractionTrace(BaseModel):
    source: str
    confidence: dict[str, float] = {}
    self_heal: dict[str, Any] = {}
    field_repair: dict[str, Any] = {}
    rejected_public_fields: dict[str, Any] = {}

class AcquisitionTrace(BaseModel):
    method: str
    status_code: int | None
    final_url: str
    blocked: bool
    adapter_name: str | None

class ExportRecord(BaseModel):
    # Identity
    run_id: int
    url_identity_key: str                  # sha256(canonical_url)
    content_fingerprint: str | None = None # sha256(title+price+sku) — NEW, enables cross-run dedup

    # Surface fields (open-ended, surface-specific)
    data: dict[str, Any] = Field(default_factory=dict)

    # Provenance (currently stored flat in CrawlRecord.source_trace)
    acquisition: AcquisitionTrace
    extraction: ExtractionTrace
    field_discovery: dict[str, FieldProvenance] = {}

    # Verdict
    verdict: str

    @model_validator(mode="after")
    def require_url_identity(self) -> "ExportRecord":
        if not self.url_identity_key:
            raise ValueError("url_identity_key is required")
        return self
Idempotency Key Strategy
The current sha256(source_url) identity key conflates URL identity with record identity. A product that moves to a new URL (canonical redirect) will be treated as a new record. Proposed two-level strategy:

text
Level 1 — URL identity (existing):
  url_identity_key = sha256(canonical_url)
  Scope: within run (current behavior) + cross-run with index

Level 2 — Content fingerprint (new):
  content_fingerprint = sha256(
      f"{title.lower().strip()}|{price_text}|{sku or ''}"
  )
  Scope: cross-run dedup for same product at different URL

Idempotency enforcement:
  Before INSERT CrawlRecord:
    1. Check url_identity_key in (run_id, url_identity_key) index   ← blocks same-URL dup in re-run
    2. Check content_fingerprint in (run_id, content_fingerprint) index  ← blocks same-product dup
  On conflict: UPDATE updated_at, data WHERE content changed, skip WHERE identical
Database index additions:

sql
CREATE UNIQUE INDEX IF NOT EXISTS crawl_records_run_url_key
    ON crawl_records (run_id, url_identity_key);

CREATE INDEX IF NOT EXISTS crawl_records_content_fp
    ON crawl_records (run_id, content_fingerprint)
    WHERE content_fingerprint IS NOT NULL;
Storage Abstraction Interface
python
# services/storage/base.py

from typing import Protocol, runtime_checkable

@runtime_checkable
class ArtifactStorage(Protocol):
    async def write_text(self, *, key: str, content: str, encoding: str = "utf-8") -> str: ...
    async def write_bytes(self, *, key: str, content: bytes) -> str: ...
    async def read_text(self, *, key: str) -> str | None: ...
    async def exists(self, *, key: str) -> bool: ...
    async def public_url(self, *, key: str, ttl_seconds: int = 3600) -> str | None: ...
    # Returns storage-backend URI (local path, s3://..., gs://...)

# services/storage/local.py   — current behavior, extracted
class LocalArtifactStorage:
    def __init__(self, base_dir: str): ...
    async def write_text(self, *, key, content, encoding="utf-8") -> str:
        path = Path(self.base_dir) / key
        path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_text, content, encoding=encoding)
        return str(path)
    async def public_url(self, *, key, ttl_seconds=3600) -> str | None:
        return None  # local paths have no public URL

# services/storage/s3.py      — future
class S3ArtifactStorage:
    def __init__(self, bucket: str, prefix: str, client: aioboto3.Session): ...
    async def write_text(self, *, key, content, encoding="utf-8") -> str:
        body = content.encode(encoding)
        await self._client.put_object(Bucket=self.bucket, Key=f"{self.prefix}/{key}", Body=body)
        return f"s3://{self.bucket}/{self.prefix}/{key}"
    async def public_url(self, *, key, ttl_seconds=3600) -> str | None:
        return await self._client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": f"{self.prefix}/{key}"},
            ExpiresIn=ttl_seconds
        )

# services/storage/factory.py — driven by config
def get_artifact_storage() -> ArtifactStorage:
    if settings.storage_backend == "s3":
        return S3ArtifactStorage(bucket=settings.s3_bucket, ...)
    if settings.storage_backend == "gcs":
        return GCSArtifactStorage(...)
    return LocalArtifactStorage(base_dir=settings.artifacts_dir)
artifact_store.py becomes a thin facade over get_artifact_storage(), preserving all existing call sites. persist_html_artifact(run_id, source_url, html) becomes:

python
async def persist_html_artifact(*, run_id, source_url, html) -> str:
    storage = get_artifact_storage()
    key = f"runs/{run_id}/pages/{_url_hash(source_url)}.html"
    return await storage.write_text(key=key, content=html)
pipeline/core.py Decomposition (Bonus Flag)
At 49KB, pipeline/core.py is the next decomposition target. Its responsibilities map cleanly onto the modules already split off from it:

text
pipeline/
├── core.py              → thin orchestrator only: process_url() calls the below
├── url_normalizer.py    → URL canonicalization, robots pre-check
├── acquisition_loop.py  → fetch attempts, engine escalation, retry gate
├── extraction_loop.py   → extraction attempts, direct_record_fallback integration
├── verdict_builder.py   → compute_verdict, aggregate across records
└── persistence.py       → already separated ✓