CrawlerAI POC Rebuild Plan, Revised
Summary
Rebuild CrawlerAI from scratch as a scalable POC using FastAPI + Next.js, while preserving docs/, .env, and archive/ as reference. The POC must include the full user-facing workflow described in docs/POC.md, and the architecture must stay aligned with docs/PRD.MD so it can grow into the fuller product later without another rewrite.

Key corrections applied:

No user-facing Overrides feature
Additional fields is the user input mechanism for comma-separated requested fields
Users must see all extracted/discovered data so there is no perceived data loss
UI defaults to normalized output, but raw/discovered/source data remains inspectable
A first-class review workflow is required where users can:
inspect all fields
select which fields matter
rename/map them
save/promote them for reuse on future runs
POC scope includes the workflows in POC.md; the PRD guides architecture and future-proofing
Chosen defaults:

Runtime for this phase: SQLite + local worker execution
No Docker, no Postgres in this phase
No user-facing Overrides table/API/UI
Save/promote persists: approved schema fields, raw-to-canonical mappings, and supporting selectors/recipes
Raw visibility model: dedicated raw-data/source views alongside normalized views
Product and Workflow Model
1. Core user promise
The crawler extracts and preserves all sensible data it can find from a page.
Normalized output is what the user primarily works with.
Raw/discovered/source data is still visible in the UI so users can verify coverage and confirm nothing was dropped silently.
Save/promote is the mechanism for turning one successful run into reusable domain knowledge.
2. User workflows in scope
Auth and user roles
Category/listing crawl
PDP/detail crawl
Batch crawl via pasted URLs and CSV
Run history
Dashboard
Selector testing/suggestion
Active jobs
LLM config
Additional fields entry via comma-separated input
Review/save/promote workflow:
show all discovered fields and candidate values
let user choose fields to keep
let user rename/map those fields
persist the approved schema/mapping/selectors for future runs
Full output inspection:
normalized data
raw/discovered data
source attribution
logs
intelligence/coverage views
3. Explicitly out of scope
User-facing Overrides management
Domain memory as a separate product area
Docker
Postgres
SaaS/multi-workspace auth
Vision extraction
Proxy rotation
Any feature not required by POC.md or necessary for the future-safe architecture
Architecture
1. Backend
Replace Flask with FastAPI under backend/app/.
Use SQLAlchemy 2.0 + Alembic + SQLite in this phase.
Keep clear separation:
api/: route handlers only
services/: orchestration and business logic only
models/: SQLAlchemy only
schemas/: Pydantic only
Keep the structure close to your original target, but adapt infra for this phase:
main.py
core/
models/
schemas/
api/
services/
tasks/
workers.py
Keep the interfaces stable enough that SQLite/local-worker can later be swapped to Postgres/Celery/Redis with minimal API churn.
2. Persistence model
Keep these core tables because they are still needed for the POC and future product direction:
users
crawl_runs
crawl_records
crawl_logs
selectors
llm_configs
llm_cost_log
Remove overrides as a product feature and do not expose it in UI/API.
Add only the minimum persistence needed for the save/promote workflow if it cannot be expressed cleanly through the existing tables and centralized knowledge base.
Persist per-run raw/discovered/normalized data in a way that supports:
normalized display
raw/source inspection
future re-extraction/review
exports
3. Centralized knowledge base
Build a backend-owned centralized knowledge base as the single source of truth for reusable extraction knowledge.
It must hold:
canonical schemas by surface/domain
raw-to-canonical mappings
selector memory
deterministic extraction recipes/defaults
prompt registry metadata
No hardcoded schema lists, selector sets, or mapper dicts inside pipeline code.
Database holds runtime/user-managed data; the knowledge-base layer owns reusable extraction knowledge and promotion outputs.
4. Crawl pipeline
Implement the POC pipeline as stage-owned services:
Acquire
Discover
Extract
Unify
Publish
Acquire:
local acquisition cache
curl-cffi
Playwright fallback for JS-required/thin pages
save artifact HTML to disk
Discover:
enumerate JSON-LD, __NEXT_DATA__, DOM/selector opportunities, table structures, and other usable sources
preserve discovered/raw payloads for later inspection
Extract:
produce candidates from each source without losing source attribution
Unify:
choose best values per canonical field
map raw fields using centralized mappings
keep unmapped data visible, not discarded
Publish:
persist normalized records
persist/disclose raw/discovered data paths or payloads
update summaries, coverage, and logs
5. Background jobs
Use a local worker model for this phase, not Celery/Redis.
Persist run status in crawl_runs.
Support:
enqueue
poll
cooperative cancel
active jobs listing
Keep the internal contract narrow so Celery/Redis can replace the worker implementation later without changing the API shapes.
Data and Review Model
1. Record representation
Each crawl result must preserve three layers of truth:

raw/discovered: all sensible source data/candidates found
normalized: cleaned and mapped values shown by default
published/promoted: the approved schema-facing view the user chooses to save for future reuse
2. UI visibility rules
Normalized data is the default main presentation.
Users can inspect all discovered/raw/source-backed data through dedicated views.
Nothing sensible is silently stripped from the user’s ability to inspect it.
Source attribution stays visible:
source type
field origin
confidence/candidate provenance where relevant
3. Additional fields
Users enter additional fields as comma-separated names in crawl forms.
The pipeline attempts to detect and extract them.
Additional fields remain visible even if not yet promoted into canonical schema.
If users later rename/select/promote them, the mapping and selectors become reusable domain knowledge.
4. Save/promote flow
From a completed run, users can:
inspect all available fields
choose which fields should be part of the approved output
rename raw/discovered fields to canonical names
save/promote that decision
Promotion persists:
approved output schema for the domain/surface
raw-to-canonical mapping
supporting selectors/recipes where available
Future runs for that domain should use the promoted knowledge first, while still exposing newly discovered raw fields.
API and Frontend Contracts
1. Backend API
Implement the route set from your earlier prompt, with one correction:

remove user-facing Overrides endpoints/UI from the plan
keep all other core areas:
auth
users
dashboard
crawls
records
selectors
llm
jobs
Add or retain review/promotion endpoints needed for:
fetching a run’s normalized + raw/discovered field inventory
saving/promoting approved field selection and renames
2. Frontend app
Replace Vite/React Router with Next.js 15 App Router.
Rebuild the UI cleanly.
Use:
Tailwind v4
TanStack Query
TanStack Table
Zustand where client-only state is needed
shadcn/ui
Recharts
Required pages:
/login
/register
/dashboard
/crawl/category
/crawl/pdp
/runs
/runs/[run_id]
/selectors
/admin/users
/admin/llm
/jobs
Remove /admin/overrides from the plan.
Add run detail UX that explicitly supports:
normalized table view
JSON/raw/discovered view
intelligence/coverage view
logs
review/select/rename/promote workflow
3. Typed interfaces
Use backend Pydantic schemas as the source for frontend client shapes.
Create one typed API client layer.
Avoid one giant shared types.ts; split by domain:
auth
dashboard
crawls
records
selectors
llm
jobs
review/promotion
Delivery Phases
Phase 0: Repo cleanup and baseline
Preserve:
docs/
.env
archive/
Remove active legacy runtime and generated/vendor artifacts.
Replace startup/developer flow for FastAPI + local worker + Next.js.
Document the new local dev flow.
Phase 1: Backend foundation
FastAPI app
config/security/dependencies
SQLite DB + Alembic
user/auth system
core tables
local worker skeleton
health/docs/auth verification
Phase 2: Knowledge base and crawl engine
centralized knowledge base
acquire/discover/extract/unify/publish services
artifact persistence
raw/discovered/normalized result model
single-run crawl verification
Phase 3: Review/promote and remaining APIs
run history
dashboard
selectors
records and exports
jobs
llm config/cost log
review/select/rename/promote endpoints and persistence
Phase 4: Frontend rebuild
Next.js app scaffold and design system
auth and guarded navigation
crawl forms
dashboard
runs list
run detail with normalized/raw/intelligence/logs/review
selectors tool
admin users
admin llm
jobs
Phase 5: Hardening
export correctness
cancel behavior
coverage summaries
promotion persistence behavior
selector reuse on future runs
raw-data visibility verification
docs alignment with actual runtime
Test Plan
Backend tests
Auth:
register/login/me/admin access
Schema/migrations:
Alembic upgrade on clean SQLite DB
Knowledge base:
canonical schema lookup
mapping lookup
selector reuse
promotion persistence
Pipeline:
curl-first success
Playwright fallback
JSON-LD extraction
__NEXT_DATA__ extraction
raw candidate preservation
unify picks best candidate but does not hide inspectable raw data
Review/promote:
field inventory includes discovered/raw + normalized data
rename/map persists correctly
future run reuses promoted schema/mapping/selectors
Jobs:
enqueue/poll/cancel/active jobs
LLM:
optional behavior
masked config reads
encrypted key storage
cost logging
Frontend tests
Auth redirects and admin gating
Category and PDP crawl submission flows
Batch URL and CSV submission
Run detail polling and terminal-state transition
Run detail raw/normalized/intelligence/log views
Review/select/rename/promote flow
Selector suggest/test/save flow
LLM config page
Jobs page polling and cancel action
End-to-end scenarios
Register → login → run PDP crawl → inspect normalized + raw data → promote fields → rerun same domain and confirm reuse
Run category crawl → inspect discovered fields → submit detail/batch follow-up
Submit additional fields via comma-separated input → verify extracted fields are visible even before promotion
Export CSV/JSON after review and confirm normalized output is stable while raw inspection remains available in UI/artifacts
Assumptions and Defaults
docs/POC.md defines what the POC must do.
docs/PRD.MD is the architectural guide for making this POC scale into the full product.
Your latest corrections override my earlier mistaken assumptions.
There is no user-facing Overrides feature in this build.
“Save/promote” is a core persisted workflow, not a temporary per-run convenience.
The app must preserve user trust by making all sensible discovered data inspectable, even when normalized views are the primary UI.
SQLite/local-worker is a temporary infrastructure choice only; public contracts should not depend on that choice.