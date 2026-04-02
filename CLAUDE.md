# CLAUDE.md

## Project

CrawlerAI is a POC crawler stack with:

- `backend/`: FastAPI + SQLAlchemy async backend, crawl worker loop, adapters, deterministic extraction pipeline, review/promotion flow.
- `frontend/`: Next.js app for crawl submission, run inspection, review, selectors, admin views.
- `docs/`: product notes and implementation planning docs.

## Current Crawl Contract

### Submission modes

- `run_type="crawl"`: single URL crawl submitted from the unified Crawl Studio.
- `run_type="batch"`: multi-URL loop submitted from pasted URLs.
- `run_type="csv"`: CSV upload, first column parsed as URL, header ignored when present.

### Page type

Page type is no longer split into separate frontend pages. The unified crawl UI uses:

- `settings.page_type="category"` with `surface="ecommerce_listing"`
- `settings.page_type="pdp"` with `surface="ecommerce_detail"`

Category is the default page type in the UI.

### Crawl settings currently wired

- `settings.advanced_mode`: `null | "auto" | "paginate" | "scroll" | "load_more"`
- `settings.max_pages`
- `settings.max_records`
- `settings.sleep_ms`
- `settings.proxy_list`
- `settings.llm_enabled`
- `settings.extraction_contract`: row-wise `field_name`, `xpath`, `regex`

Advanced crawl is a single toggle-backed mode. There is no separate Spacraler implementation.

## Frontend State

### Implemented

- Unified crawl studio at `/crawl`
- Tabs for `Crawl`, `Batch`, and `CSV`
- Compact right-side crawl settings rail
- Category/PDP toggle, defaulting to Category
- Advanced crawl toggle + mode dropdown
- Proxy rotation toggle + list input
- LLM toggle kept separate and off by default
- Extraction contract editor with row-wise add/delete
- Legacy `/crawl/category` and `/crawl/pdp` routes now redirect to `/crawl`
- Root route now redirects to `/login`
- Protected app routes are gated by a frontend `me()` check before child pages mount

### Notes

- CSV submission uses multipart `POST /api/crawls/csv`
- Batch submission uses JSON `POST /api/crawls` with `run_type="batch"`

## Backend State

### Implemented pipeline areas

- HTML acquisition waterfall with deterministic HTTP + Playwright fallback
- XHR/fetch interception in Playwright browser client
- Listing/category extraction via repeating card detection
- Platform adapter interface and registry
- Adapters present for:
  - Shopify
  - Amazon
  - Walmart
  - eBay
  - Indeed
  - LinkedIn Jobs
- Microdata / RDFa discovery
- Batch multi-URL processing
- CSV ingestion from uploaded files
- Optional proxy rotation support
- Review/promotion endpoints

### Recent fixes

- Single-page frontend contract now uses `run_type="crawl"`
- Listing extractor now resolves relative URLs against the page URL
- Review payload now exposes extracted fields instead of manifest container keys
- Password hashing now uses `pbkdf2_sha256` instead of the broken bcrypt runtime path
- Shopify PDP adapter now scopes detail acquisition to `/products/<handle>.js`
- Extraction contract rows now feed XPath and regex candidate extraction

## Tests

Backend tests currently pass with:

```powershell
$env:PYTHONPATH='.'
pytest tests -q
```

## Known Gaps / Risks

- LLM integration is configuration-only today. The pipeline still behaves deterministically.
- XPath and regex rules are currently first-pass extraction helpers; there is no full selector authoring validation UI yet.
- `CLAUDE.md` should be updated again after real-site extraction tuning.

## Preferred Next Steps

1. Smoke test one Shopify category page and one PDP through the new Crawl Studio.
2. Tighten adapter behavior using artifacts from the first real site.
3. Expand extraction-contract validation and preview once first-site behavior is stable.
