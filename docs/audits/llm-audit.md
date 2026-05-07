llm_types.py (16 lines)
This file has an inverted dependency: it imports LLMErrorCategory from llm_circuit_breaker to use as a field type on LLMTaskResult. That means the shared contract type (LLMTaskResult) depends on an infrastructure concern (llm_circuit_breaker). The fix is simple — move LLMErrorCategory and classify_error into llm_types.py (or a new llm_errors.py), and have llm_circuit_breaker import from there. Currently the import graph is llm_types → llm_circuit_breaker → config/llm_runtime, which means loading the types dataclass transitively pulls in Redis, settings, and Lua scripts.

llm_runtime.py (31 lines — the 838-byte mystery)
Finding: It is a pure re-export shim, not a stub or dead code. It aggregates public symbols from all 5 other modules (llm_tasks, llm_provider_client, llm_config_service, llm_circuit_breaker, llm_types) into a single __all__ list for external callers (likely API route handlers and background workers). This is a valid pattern — but it creates a hidden footgun: because llm_runtime.py is the declared public surface, callers who want to stay "clean" should only import from here. In practice they don't (see Q1 below). The file should be documented explicitly as the public facade and enforced via __all__-only imports in callers.

llm_config_service.py (182 lines)
Clean and well-scoped. Three concerns are present and acceptable at this size:

DB config resolution (resolve_active_config, resolve_run_config, snapshot_active_configs) — queries LLMConfig model

Prompt loading (get_prompt_task, load_prompt_file) — reads from disk + registries

API key resolution (resolve_provider_api_key, provider_env_key) — decrypts or reads env

One smell: provider_env_key uses a bare if/elif chain over provider names. This will go stale as providers are added. The llm_provider_catalog() list at the bottom of the same file already has the canonical provider→env-key mapping but it isn't used by provider_env_key. These two structures should be merged — llm_provider_catalog() should drive key resolution, not a parallel if-chain.

llm_cache.py (156 lines)
Q2 Answer: Content-addressed, correctly implemented. build_llm_cache_key serializes a 9-field payload (task_type, domain, provider, model, response_type, data_key, system_prompt, user_prompt, variables) with deterministic JSON (sort_keys=True, separators=(",",":"), ensure_ascii=True) then SHA-256 hashes it. The _normalize_cache_value function handles sets (sorted), Decimals, and nested dicts/lists recursively, so key stability is solid.

One gap: the domain field is normalized to lowercase but system_prompt and user_prompt are included raw without leading/trailing whitespace normalization. A prompt with a trailing newline and one without will produce different cache keys even if semantically identical. Add .strip() to both prompts before hashing.

The cache stores input_tokens/output_tokens in the serialized result, meaning a cache hit returns the original token counts — callers should be aware these are historical, not live, when rendering cost estimates.

llm_circuit_breaker.py (259 lines)
Q3 Answer: It wraps calls only through call_provider_with_retry in llm_provider_client.py — which means any caller that calls call_provider directly bypasses the circuit breaker entirely.

The architecture has two layers:

call_provider() — raw dispatch, no circuit breaker check

call_provider_with_retry() — calls circuit_is_open() before each attempt and calls record_success/failure after

test_provider_connection() (exported via llm_runtime.py) calls call_provider() directly — this is intentional (you want to test even if the circuit is open) but it is not annotated as a deliberate bypass. Any future caller seeing call_provider as an importable function may call it naively without the breaker.

Recommendation: Rename call_provider to _call_provider_raw (private) and make call_provider_with_retry the only public API. Add a bypass_circuit_breaker=True parameter for diagnostic paths like test_provider_connection.

The dual-layer circuit state (in-process dict[str, _CircuitState] + Redis Lua script) is well-designed for multi-worker deployments. The Redis key crawl:llm:circuit:{provider}:open uses SET NX EX which is race-safe. One issue: _resolved_failure_threshold() is called inside the Lua script from Python via ARGV — if it returns None (threshold disabled), the value passed to Lua is None or 1, meaning threshold is effectively pinned to 1 failure. This silently enables the circuit even when configured to be off.

llm_provider_client.py (432 lines)
Q1 Answer: The interface contract is partially clean, but callers do reach past it.

The public surface is:

call_provider_with_retry(...) → tuple[str, int, int]

estimate_cost_usd(...) → Decimal

test_provider_connection(...) → bool

close_llm_provider_clients() → lifecycle

Problems:

The return type tuple[str, int, int] is a raw tuple (raw_text, input_tokens, output_tokens). Callers in llm_tasks.py destructure it as raw, input_tokens, output_tokens = await call_provider_with_retry(...). If a 4th field were added (e.g. latency_ms), all 8+ call sites break. This should be a dataclass or NamedTuple: ProviderCallResult(text, input_tokens, output_tokens).

ERROR_PREFIX leaks through the boundary. llm_tasks.py imports ERROR_PREFIX from llm_circuit_breaker (not from the client) and checks if result.startswith(ERROR_PREFIX) — but the string sentinel pattern itself is the implementation detail. The ProviderCallResult dataclass should carry is_error: bool and error_category: LLMErrorCategory so callers never inspect raw text for error signals.

Per-provider httpx client management (4 sets of globals + locks + _refresh_shared_client) is correct but verbose. The four _shared_*_client() functions are identical except for the global they touch — a _ProviderClientPool dataclass with (client, timeout, lock) fields would collapse this to one generic function.

estimate_cost_usd lives here but is called from llm_tasks.py alongside token logging — it's a pricing concern, not a client transport concern. Better home: llm_cost.py (see Q5 below).

llm_tasks.py (1080 lines)
Q6 Answer: No retry duplication — llm_tasks.py delegates all retry logic to call_provider_with_retry. There is no manual retry loop in llm_tasks.py. The concern is different: llm_tasks.py owns the task-level orchestration (cache check → provider call → parse → validate → persist cost log) via run_prompt_task, and each named task (discover_xpath_candidates, extract_records_directly, extract_missing_fields, review_field_candidates) is a thin wrapper that builds prompts and calls run_prompt_task. This is clean.

The real problem here is size and mixed concerns in run_prompt_task:

Lines 200–420: cache lookup, provider call, parse, validate, Pydantic model dispatch, cost logging, metric recording — all in one function body

The cost logging (lines 230–270) writes LLMCostLog rows to the DB inside the same function that does the LLM call — meaning a DB write failure can mask or retry the LLM call outcome incorrectly

Q5 Answer — Token/Cost Tracking: llm_tasks.py is where costs are tracked. Specifically:

LLMCostLog (SQLAlchemy model) is written in the _persist_cost_log inner function at L230–270 inside run_prompt_task

LLMCostLogOutcome enum tracks success, parse_failure, validation_failure, circuit_open, missing_config

estimate_cost_usd() from llm_provider_client computes the USD value from llm_runtime_settings.get_token_pricing()

record_llm_task_outcome() and observe_llm_task_duration() from app.core.metrics emit Prometheus metrics

This is the right place for cost tracking. However it's buried inside run_prompt_task. The gaps are:

No aggregated per-run token budget enforcement (you can see costs after the fact but not gate on them pre-call)

Cache hits return historical token counts but those are not logged to LLMCostLog — only live calls are logged, so the cost model undercounts when cache hit rate is high

estimate_cost_usd is in llm_provider_client.py but conceptually belongs in a dedicated cost module

Target Architecture
text
backend/app/services/
│
│  ┌─────────────────────────────────────────────────────────┐
│  │  llm_runtime.py  (PUBLIC FACADE — only import from here)│
│  │  __all__: run_prompt_task, discover_xpath_candidates,   │
│  │           extract_records_directly, extract_missing_     │
│  │           fields, review_field_candidates,              │
│  │           llm_provider_catalog, circuit_breaker_snapshot│
│  └────────────────────┬────────────────────────────────────┘
│                       │ (re-exports only, zero logic)
│  ┌────────────────────▼────────────────────────────────────┐
│  │  llm_tasks.py  (TASK ORCHESTRATION)                     │
│  │  run_prompt_task: cache → call → parse → validate →     │
│  │  log cost                                               │
│  │  Calls: llm_cache, llm_provider_client, llm_cost,       │
│  │         llm_config_service                              │
│  └──────┬────────────────────────────────────────────┬─────┘
│         │                                            │
│  ┌──────▼───────────┐              ┌─────────────────▼─────┐
│  │  llm_cache.py    │              │  llm_cost.py  (NEW)    │
│  │  Content-addressed              │  estimate_cost_usd     │
│  │  SHA-256 keys    │              │  _persist_cost_log     │
│  │  Redis fail-open │              │  (moved from tasks +   │
│  └──────────────────┘              │   provider_client)     │
│                                    └───────────────────────┘
│  ┌─────────────────────────────────────────────────────────┐
│  │  llm_provider_client.py  (TRANSPORT)                    │
│  │  Public: call_provider_with_retry → ProviderCallResult  │
│  │          test_provider_connection (bypass_circuit=True) │
│  │          close_llm_provider_clients                     │
│  │  Private: _call_provider_raw, _shared_*_client()        │
│  │  Calls: llm_circuit_breaker (open check + record)       │
│  └──────────────────────────┬──────────────────────────────┘
│                             │
│  ┌──────────────────────────▼──────────────────────────────┐
│  │  llm_circuit_breaker.py  (RESILIENCE)                   │
│  │  circuit_is_open, record_success, record_failure        │
│  │  Dual-layer: in-process dict + Redis Lua NX EX          │
│  │  Calls: config/llm_runtime for thresholds only          │
│  └──────────────────────────────────────────────────────────┘
│
│  ┌──────────────────────────────────────────────────────────┐
│  │  llm_config_service.py  (CONFIGURATION)                 │
│  │  resolve_run_config, resolve_active_config              │
│  │  get_prompt_task, load_prompt_file                      │
│  │  resolve_provider_api_key                               │
│  │  llm_provider_catalog (drives provider_env_key,         │
│  │  replaces parallel if-chain)                            │
│  └──────────────────────────────────────────────────────────┘
│
│  ┌──────────────────────────────────────────────────────────┐
│  │  llm_types.py  (CONTRACTS)                              │
│  │  LLMTaskResult, LLMErrorCategory, ProviderCallResult    │
│  │  (NamedTuple — move here from tuple return)             │
│  │  classify_error (move here from llm_circuit_breaker)    │
│  │  NO downstream imports — pure dataclasses + enums only  │
│  └──────────────────────────────────────────────────────────┘
│
│  config/
│  └── llm_runtime.py  (SETTINGS — already separate, keep)
│      SUPPORTED_LLM_PROVIDERS, llm_runtime_settings,
│      token pricing table, thresholds
Priority Action Items (ranked)
Make call_provider private (_call_provider_raw) — closes the circuit breaker bypass gap immediately

Move LLMErrorCategory + classify_error into llm_types.py — fixes the inverted dependency that forces a full infrastructure import just to load the result dataclass

Replace tuple[str, int, int] return with ProviderCallResult NamedTuple — eliminates all positional destructuring at call sites

Create llm_cost.py extracting estimate_cost_usd (from llm_provider_client) and _persist_cost_log (from llm_tasks) — then log cache hits in llm_cost.py as zero-cost outcomes to fix the undercounting gap

Merge provider_env_key if-chain into llm_provider_catalog() — single source of truth for provider metadata in llm_config_service

Strip prompts before hashing in build_llm_cache_key — adds .strip() to system_prompt and user_prompt before the SHA-256 digest