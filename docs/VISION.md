# CrawlerAI — Agentic Vision

> **Status:** DRAFT
> **Created:** 2026-04-21
> **Purpose:** Define what CrawlerAI is, where it is going, and what architectural
> boundaries must be preserved as it gets there. This document informs every agent
> and engineer touching the codebase. It is not an implementation plan.

---

## 1. What CrawlerAI Is

CrawlerAI is an **agentic web intelligence platform**. Specialized agents collaborate to
acquire, extract, normalize, enrich, and act on web data. The core pipeline runs
deterministically and always. Optional agents extend it — enriching output and taking
supervised real-world actions — without affecting the core.

**The core pipeline is non-negotiable and always active:**

```
ACQUIRE → EXTRACT → NORMALIZE → PERSIST
```

**Optional agents extend the pipeline post-normalization:**

```
ACQUIRE → EXTRACT → NORMALIZE → PERSIST → [Commerce Agent] → [Job Apply Agent]
```

Users toggle optional agents on or off per run. The core never toggles.

---

## 2. System Architecture

```
┌──────────────────────────────────────────────────────────┐
│                      USER INTERFACE                        │
│         Goal · Agent toggles · Presets · Approval         │
└───────────────────────────┬──────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────┐
│                     ORCHESTRATOR                           │
│  Goal → execution plan · Agent selection · DAG runner     │
│  Runtime adaptation · Error recovery · Approval gating    │
└──────┬──────────────┬──────────────┬─────────────────────┘
       │              │              │
       ▼              ▼              ▼
┌────────────┐ ┌────────────┐ ┌────────────────────────────┐
│   CORE PIPELINE (always active)   │  OPTIONAL AGENTS       │
│ Acquisition│ │ Extraction │ │ Commerce Agent             │
│ Normalization · Persistence       │ Job Apply Agent        │
└────────────┘ └────────────┘ └────────────────────────────┘
                      │
                      ▼
┌──────────────────────────────────────────────────────────┐
│                  SHARED SERVICES                           │
│  Browser Runtime · LLM Runtime · Domain Memory · Config   │
│  Persistence · Artifact Store · Selector Service          │
└──────────────────────────────────────────────────────────┘
```

---

## 3. Core Pipeline

The core pipeline handles all crawl surfaces: `ecommerce_listing`, `ecommerce_detail`,
`job_listing`, `job_detail`, `automobile_listing`, `automobile_detail`, `tabular`.

### Extraction Source Hierarchy (deterministic, first-match-wins)

```
adapter → XHR/JSON network payload → JSON-LD / microdata / Open Graph
→ hydrated state (__NEXT_DATA__, __NUXT_DATA__) → DOM selectors → LLM fallback
```

### Ownership Buckets

| # | Bucket | Primary Files |
|---|--------|---------------|
| 1 | API + Bootstrap | `app/main.py`, `app/api/*`, `app/core/*` |
| 2 | Crawl Ingestion + Orchestration | `crawl_ingestion_service.py`, `crawl_service.py`, `_batch_runtime.py`, `pipeline/*` |
| 3 | Acquisition + Browser Runtime | `acquisition/*`, `crawl_fetch_runtime.py`, `robots_policy.py` |
| 4 | Extraction | `crawl_engine.py`, `detail_extractor.py`, `listing_extractor.py`, `structured_sources.py`, `js_state_mapper.py`, `network_payload_mapper.py`, `adapters/*` |
| 5 | Publish + Persistence | `publish/*`, `artifact_store.py`, `pipeline/persistence.py` |
| 6 | Review + Selectors + Domain Memory | `review/__init__.py`, `selectors_runtime.py`, `selector_self_heal.py`, `domain_memory_service.py` |
| 7 | LLM Admin + Runtime | `llm_runtime.py`, `llm_provider_client.py`, `llm_config_service.py`, `llm_cache.py`, `llm_circuit_breaker.py`, `llm_tasks.py` |

Config tunables for all buckets: `app/services/config/*`

### Registered API Surface

| Route group | Purpose |
|-------------|---------|
| `POST /api/crawls` | Create and dispatch crawl runs |
| `GET /api/crawls/{id}/records` | List extracted records |
| `GET /api/records/{id}/provenance` | Full extraction provenance |
| `GET /api/crawls/{id}/export/*` | JSON / CSV / markdown / discoverist export |
| `WS /api/crawls/{id}/logs/ws` | Real-time log streaming |
| `GET/POST /api/review/{id}` | Review payload and save approved mapping |
| `GET/POST/PUT/DELETE /api/selectors` | Selector CRUD, suggest, test, preview |
| `GET/POST/PUT/DELETE /api/llm` | LLM provider config, connection test, cost log |
| `GET /api/dashboard` | Run stats and metrics |
| `GET /api/health` | DB, Redis, browser pool status |

---

## 4. Agent Interface Contract

Every agent — core or optional — implements this interface. The orchestrator invokes
all agents generically through it.

```python
class AgentCapability(Enum):
    ACQUIRE    = "acquire"
    EXTRACT    = "extract"
    NORMALIZE  = "normalize"
    COMMERCE   = "commerce"
    JOB_APPLY  = "job_apply"

@dataclass
class AgentRequest:
    goal:             str                  # What this agent must achieve
    input_artifacts:  dict[str, Any]       # Typed data from upstream agents
    config:           AgentConfig          # LLM settings, limits, mode
    context:          RunContext           # run_id, surface, user preferences

@dataclass
class AgentResult:
    status:           AgentStatus          # SUCCESS | PARTIAL | FAILED | NEEDS_APPROVAL
    output_artifacts: dict[str, Any]       # Typed data produced
    diagnostics:      dict[str, Any]       # Timing, cost, decisions
    approval_request: ApprovalRequest | None   # Optional agents only
    sub_tasks:        list[SubTaskReport]

class Agent(Protocol):
    capability: AgentCapability
    def can_handle(self, request: AgentRequest) -> float: ...  # Confidence 0.0–1.0
    async def execute(self, request: AgentRequest) -> AgentResult: ...
    def describe(self) -> AgentDescriptor: ...
```

**Inter-agent data flows through typed artifacts:**

```python
@dataclass
class Artifact:
    type:           str    # "html" | "records" | "normalized_records" | "commerce_enriched"
    data:           Any
    metadata:       dict   # provenance, timestamps, source agent
    schema_version: int
```

Agents never call each other directly. The orchestrator routes artifacts between them.

---

## 5. Toggle System

Core pipeline agents (Acquisition, Extraction, Normalization) are always active.
Optional agents are toggled per run via `CrawlRun.settings` JSONB:

```python
{
  "agents": {
    "commerce": {
      "enabled": false,
      "config": {
        "mode": "enrichment",          # "enrichment" | "checkout"
        "enrichment_subagents": [],    # which enrichers to activate
        "brand_voice": null
      }
    },
    "job_apply": {
      "enabled": false,
      "config": {}
    }
  }
}
```

**Orchestrator override rule:** The orchestrator may activate an optional agent when a
goal requires it, but only if the agent is not explicitly disabled and the user has
granted prior consent for action agents.

### Presets

```python
class AgentPreset(Base):
    id:           int
    user_id:      int
    name:         str
    description:  str
    agent_config: dict   # Same shape as per-run agent config
    is_default:   bool
```

| Preset | Commerce | Job Apply |
|--------|:--------:|:---------:|
| Quick Scrape | ❌ | ❌ |
| Deep Extract | ❌ | ❌ |
| Catalog Enrich | ✅ enrichment | ❌ |
| Shop & Buy | ✅ checkout | ❌ |
| Job Hunter | ❌ | ✅ supervised |
| Full Auto | ✅ both | ✅ supervised |

---

## 6. Orchestrator

The orchestrator replaces the hardcoded linear pipeline call in `_batch_runtime.process_run()`
with a DAG-driven execution engine. It is responsible for:

1. **Goal interpretation** — parse user goal into a structured execution plan
2. **Agent selection** — decide which agents participate based on goal and toggles
3. **DAG execution** — agents run in parallel where artifact dependencies allow
4. **Runtime adaptation** — if acquisition is blocked, select a different strategy;
   if extraction yields thin results, invoke schema inferencer; degrade gracefully on budget exhaustion
5. **Error recovery** — agent failures do not crash the pipeline; orchestrator decides retry, skip, or fail
6. **Approval gating** — for supervised agents, pause and present state for user decision

**Intelligence model:** LLM-powered planner for goal interpretation + deterministic executor
for DAG traversal. The deterministic executor runs regardless of LLM availability.

**Backward compatibility:** Runs without a goal use the orchestrator to generate a linear
plan identical to the current pipeline. Existing API contracts are preserved.

---

## 7. Commerce Agent

> The primary new capability. Transforms raw crawled product records into AI-ready
> catalog intelligence — enriched for the era of agentic commerce where AI assistants
> shop on behalf of humans.

**Two modes:**

### Enrichment Mode (default)

Enriched fields are stored in `enriched_data JSONB` on `CrawlRecord`, separate from
`record.data`. The original extraction output is never modified.

| Sub-agent | Purpose | Intelligence |
|-----------|---------|-------------|
| **Intent Attribute Generator** | Intent-driven attributes (style, occasion, audience, use-case) matching how shoppers think and search | LLM — brand-voice-aware |
| **Metadata Generator** | SEO titles, descriptions, keywords, alt-text — optimized for traditional search and AI discovery | LLM — SEO + AI-aware |
| **Vision Tagger** | Color, pattern, style, material, fit extracted from product images | CV model + LLM refinement |
| **Category Harmonizer** | Normalize taxonomy across source schemas into a unified hierarchy | LLM — category semantics |
| **Review Summarizer** | On-brand summaries from product reviews; enables shoppers to ask questions about fit and quality | LLM — sentiment + brand-voice |
| **Suggestion Engine** | Intent-driven product recommendations and complete-the-look bundles | LLM + co-occurrence rules |
| **Cross-Source Merger** | Merge listing + detail + reviews into one complete enriched record | Rule-based entity matching + LLM conflict resolution |
| **Pricing & Promotion Engine** | Price normalization, range detection, promotion strategy generation | Rule-based + LLM |

**Enrichment output shape:**

```json
{
  "original": { "title": "Blue Dress", "price": "$49.99" },
  "enriched": {
    "intent_attributes": ["evening wear", "cocktail", "A-line", "midi", "formal occasion"],
    "audience": ["women 25-40", "professional", "event-goer"],
    "style_tags": ["elegant", "classic", "minimalist"],
    "color_family": "navy blue",
    "seo_keywords": ["navy blue cocktail dress", "midi formal dress"],
    "ai_discovery_tags": ["formal-dress", "evening-wear", "midi-length"],
    "image_tags": ["navy", "a-line cut", "knee-length", "solid color"],
    "review_summary": "Runs slightly small — size up. Great for weddings and cocktail events.",
    "suggested_bundles": ["matching clutch", "statement earrings", "nude heels"],
    "category_path": "Women > Dresses > Formal > Midi"
  }
}
```

Every enriched field carries provenance: source sub-agent, model used, confidence score.

### Checkout Mode (supervised)

| Sub-agent | Purpose | Intelligence |
|-----------|---------|-------------|
| **Cart Navigator** | Find and add items to cart, navigate checkout flow | LLM — understands page layout |
| **Form Filler** | Fill shipping, billing, payment from user-provided data | Rule-based + LLM |
| **Approval Gate** | Pause before any irreversible action; present to user; wait for decision | Deterministic — always triggers |
| **Session Manager** | Authenticated sessions, cookie persistence, login flows | Rule-based |

**Non-negotiable constraints:**
- The Approval Gate always triggers before payment or order submission. No exceptions.
- User credentials are stored encrypted, never logged, never persisted in records.
- Sessions are isolated per user. No cross-user session leakage.
- Every action is logged with screenshot evidence.
- The user can abort at any point. The agent abandons the cart and closes the session cleanly.

---

## 8. Job Application Agent

> Supervised. Applies for jobs on behalf of the user — navigates application flows,
> fills forms with user profile data, and always pauses for approval before submission.

| Sub-agent | Purpose | Intelligence |
|-----------|---------|-------------|
| **Application Navigator** | Navigate multi-step application flows across Workday, Greenhouse, Lever, and others | LLM — every site is different |
| **Profile Filler** | Fill personal info, work history, education from structured user profile | Rule-based field mapping |
| **Question Responder** | Answer custom application questions derived from user profile and job description | LLM — profile-grounded only |
| **Document Attacher** | Attach resume, cover letter, portfolio files | Rule-based file upload |
| **Approval Gate** | Pause before final submission; present completed application for review | Deterministic — always triggers |

**Non-negotiable constraints — identical to Commerce checkout:**
- Never auto-submit an application.
- LLM answers are derived only from user-provided profile data. No fabrication.
- Credential vault, session isolation, audit trail, abort-at-any-point — same model as Commerce.

---

## 9. Multi-Model LLM Strategy

Different tasks require different models. The existing `llm_config_service` per-run pattern
extends to per-agent model preferences declared in `AgentConfig`.

| Task class | Model class | Examples |
|------------|-------------|---------|
| High-volume mechanical (attribute generation, categorization) | Fast / cheap | Groq, Haiku |
| Complex inference (schema inference, block analysis, strategy) | Powerful | Claude Opus, GPT-4 |
| Vision tasks (image tagging) | Vision-capable | GPT-4o, Claude vision |

Each agent has its own LLM budget (token cap, cost cap per run). The orchestrator tracks
cumulative spend across all agents and can downgrade model selection or disable LLM-powered
sub-agents when budget is exhausted. Rule-based sub-agents always run regardless of budget.

---

## 10. Planned API Surface Additions

| Route | Method | Agent | Purpose |
|-------|--------|-------|---------|
| `/api/crawls/{id}/enrich` | POST | Commerce | Trigger enrichment on completed run |
| `/api/crawls/{id}/enrich` | GET | Commerce | Get enrichment status and results |
| `/api/crawls/{id}/checkout` | POST | Commerce | Initiate supervised checkout |
| `/api/crawls/{id}/approve` | POST | Commerce / Job Apply | Submit approval gate decision |
| `/api/crawls/{id}/apply` | POST | Job Apply | Initiate supervised job application |
| `/api/presets` | GET / POST / PUT / DELETE | All | User preset management |
| `/api/agents` | GET | All | List registered agents and capabilities |

---

## 11. Future Capabilities

### Multi-Tenant Cloud Deployment

All shared state — browser sessions, LLM budgets, credentials — must be scoped by
`user_id` per run. No global singletons that assume one active user. The current
database query pattern (all queries filter by `user_id`) must be maintained in all
new models and agents.

### Agent State Resume

Agent execution state must be serializable so runs can be resumed after interruption.
`AgentResult.output_artifacts` must be JSON-serializable. Each agent's `execute()` must
be idempotent relative to its input artifacts.

### Computer Vision — Self-Hosted

Vision Tagger runs a self-hosted open model (CLIP, BLIP, or equivalent) rather than
cloud vision APIs. This avoids per-image costs and external dependencies. The agent
interface must support non-LLM model backends as a distinct inference path.

---

## 12. Architectural Boundaries

These boundaries must be respected by every change, regardless of phase.

**Record contract:**
- `record.data` contains only populated canonical fields for the crawl surface. Always.
- Enriched fields live in `enriched_data JSONB`. They never appear in `record.data`.
- `source_trace` and `discovered_data` carry provenance without leaking raw manifest noise.

**Agent isolation:**
- Agents never call each other directly. Data flows through the orchestrator via artifacts.
- Disabling any optional agent must never break core pipeline agents or other optional agents.
- Action agents (Commerce checkout, Job Apply) require explicit user consent. The orchestrator
  cannot activate them from goal inference alone.

**LLM boundaries:**
- LLM use is opt-in per run. It cannot activate silently.
- Run snapshots (`llm_config_snapshot`, `extraction_runtime_snapshot`) are stable within a run.
- LLM failures degrade gracefully into diagnostics. They never corrupt `record.data`.

**Generic paths stay generic:**
- Platform-specific behavior belongs in `adapters/` or `config/platforms.json`.
- No platform names as conditional branches in `acquisition/*`, `crawl_engine.py`, or any shared path.
- Config tunables belong in `app/services/config/*`, not inline in service code.

**File structure:**
- The 7 core ownership buckets do not change.
- New agents are added as new top-level directories under `services/` (`commerce_agent/`, `job_apply_agent/`).
- Shared agent infrastructure lives in `services/agents/` (`types.py`, `registry.py`, `approval_gate.py`).
- Core bucket files are not renamed to match agent sub-agent naming conventions.

---

## 13. Canonical Docs

| Doc | Purpose |
|-----|---------|
| `AGENTS.md` | Session bootstrap — read first every session |
| `docs/CODEBASE_MAP.md` | File-to-bucket map for every file in the repo |
| `docs/ENGINEERING_STRATEGY.md` | Engineering principles and named anti-patterns |
| `docs/INVARIANTS.md` | Runtime contracts that no refactor may break |
| `docs/backend-architecture.md` | Detailed backend subsystem reference |
| `docs/frontend-architecture.md` | Frontend structure and API contract notes |
| `docs/agent/PLAN_PROTOCOL.md` | How plans are created, executed, and closed |
| `docs/agent/SKILLS.md` | Step-by-step recipes for common implementation tasks |
| `docs/plans/ACTIVE.md` | Current active plan pointer |