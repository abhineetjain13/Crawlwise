# Product Intelligence: Web Product Matching + Price Comparison

## Summary

Build Product Intelligence as a web-discovery and comparison workflow.

Source is a completed ecommerce crawl, first optimized for Belk but not hardcoded to Belk. User selects source records from completed crawl results. System searches web for exact/near-exact product PDPs on brand sites and other retailers, crawls those candidate URLs through the existing crawler, scores matches, then compares price/availability against the source product.

LLM is allowed when explicit and useful. It must stay gated by run settings/config and used for enrichment or ambiguity resolution, not silent primary extraction.

## Phase 1: Belk Source Crawl To Brand/Retailer Matches

- Add completed-run button beside existing Batch Crawl action:
  - `Product Intelligence Selected (N)` when rows selected
  - `Product Intelligence Results (N)` when no rows selected
- Add sidebar route/page: `/product-intelligence`.
- Prefill Product Intelligence page from selected completed crawl records using the same sessionStorage pattern as Batch Crawl.
- Page controls:
  - source crawl/records preview
  - source domain
  - max source products
  - max candidates per product
  - search provider
  - include/flag/exclude private-label products
  - confidence threshold
  - allowed/excluded domains
  - LLM enrichment toggle
- Backend flow:
  - group source products by normalized brand
  - flag private labels from config
  - build per-product search queries using brand, title, sku/mpn/gtin when present, source-domain exclusion, and brand-domain hints
  - discover candidate URLs from configured provider
  - create normal ecommerce detail crawl jobs for candidate URLs
  - reuse existing acquisition/extraction pipeline
  - compare extracted candidate records to source records
  - store match score, score reasons, source/candidate prices, availability, URL, domain, and crawl IDs
- No fixed test counts. User examples are illustrative only.

## Phase 2: Any Source Catalog To Brand + Aggregator + Retailer Comparison

- Generalize input from Belk-only to any completed ecommerce crawl:
  - retailer listing crawl
  - brand category crawl
  - marketplace crawl
  - aggregator crawl
- Add comparison modes:
  - source vs brand DTC
  - source vs retailers
  - aggregator vs brand
  - aggregator vs aggregator
  - source recrawl vs previous source crawl
- Candidate discovery becomes provider-backed and domain-aware:
  - SerpAPI if configured
  - DuckDuckGo fallback for local/demo
  - no Google Custom Search dependency
- Add user controls for source-type priority, domain allow/deny lists, stale recrawl threshold, and confidence bands.

## Phase 3: Image Matching

Decision open, but document path now.

- pHash option:
  - use Pillow + ImageHash
  - good for same or near-same product images
  - cheap and local
- CLIP/OpenCLIP option:
  - better for alternate angles and lifestyle images
  - heavier dependency and model/runtime cost
  - config-gated only
- Store image signal as one part of score breakdown, not sole match proof.
- Use `pgvector` only if CLIP embeddings become large enough to need vector search.

## Backend Changes

- Add API module: `backend/app/api/product_intelligence.py`.
- Add schemas: `backend/app/schemas/product_intelligence.py`.
- Add models in existing model ownership:
  - `ProductIntelligenceJob`
  - `ProductIntelligenceSourceProduct`
  - `ProductIntelligenceCandidate`
  - `ProductIntelligenceMatch`
- Add Alembic migration.
- Add service owner under `backend/app/services/product_intelligence/`.
- Add config owner: `backend/app/services/config/product_intelligence.py`.
- All weights, thresholds, source-type labels, private labels, brand aliases, search limits, provider names, and timeout tunables live in config.
- Candidate crawl creation must use existing `create_crawl_run` / dispatch path. No second crawler.

## LLM Use

LLM is optional and explicit.

Allowed Phase 1 uses:
- normalize messy product titles into comparable attributes
- infer likely model/style names from title text
- explain low-confidence mismatch reason
- enrich score reasons when deterministic signals conflict

Not allowed:
- replacing deterministic extraction
- silently enabling when `llm_enabled=False`
- overwriting extracted SKU/price/brand without explicit diagnostic trace

LLM output must be stored as diagnostic/enrichment metadata and degrade cleanly.
Product Intelligence enrichment prompt output is a strict object. Missing fields use deterministic defaults, score/confidence stay in the 0-1 range, and invalid payloads fail validation instead of being applied.
Candidate crawl polling must end in an explicit candidate status. If the crawl result is not scoreable before the poll deadline, the candidate is marked `crawl_timeout`.

## Frontend Changes

- Add sidebar item: `Product Intelligence`.
- Add page with:
  - source records panel
  - configuration panel
  - job progress panel
  - match results table
  - price comparison view
  - score breakdown drawer/panel
- Add API client methods and types in existing frontend API layer.
- Keep UI user-controlled and flexible:
  - filters by brand/domain/source type/confidence
  - include low-confidence toggle
  - export CSV/JSON
  - accept/reject match action

## Tests

- Source record prefill from completed crawl works.
- Product Intelligence page consumes prefill and shows source products.
- Search query builder excludes source domain and uses SKU/MPN/GTIN when present.
- Private-label behavior follows user-selected mode.
- Candidate crawl creates normal ecommerce detail crawl jobs.
- Match scorer returns score plus reason breakdown.
- LLM toggle is respected and never runs unless explicitly enabled.
- Price comparison renders source vs candidate prices.
- No config constants added outside `app/services/config/*`.

Verify:
- `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests -q`
- `cd frontend; npm test`

## Assumptions

- Phase 1 starts with Belk as seeded config and demo path, but code remains generic.
- External search APIs discover URLs only. Matching decision is internal and auditable.
- User examples are illustrative, not fixed acceptance numbers.
- Image matching is Phase 3, not Phase 1.
