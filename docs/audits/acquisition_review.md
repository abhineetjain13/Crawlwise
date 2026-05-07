# Acquisition Memory Migration — Codex Execution Brief

Date: 2026-05-07
Scope: crawl_fetch_runtime.py, domain_run_profile_service.py, host_protection_memory.py,
       pipeline/core.py, crawl_crud.py, metrics.py

---

## Context and goal

The acquisition layer has three memory stores:

- `DomainRunProfile` — scoped to `(domain, surface)`, long-term learned behavior
- `HostProtectionMemory` — scoped to host only, short-TTL block/backoff facts
- `DomainCookieMemory` — scoped to domain + engine, reusable browser session state

The problem: `HostProtectionMemory` has grown beyond its mandate. It currently stores
and exposes `patchright_success` and `real_chrome_success` as policy signals, which
causes `crawl_fetch_runtime.py` to make long-term engine and curl handoff decisions
from host-scoped, TTL'd facts rather than from the domain/surface contract in
`DomainRunProfile`. This results in wrong engine choices, premature curl handoff on
pages that required browser rendering, and different behavior between single-URL and
batch runs on the same domain.

The migration has four slices. Execute them in order. Each slice is independently
deployable and verifiable.

---

## Hard rules for all slices

- Do not add compatibility shims or wrapper functions. Make the clean cut.
- Do not leave dead code paths. Delete the branches you replace.
- Do not add new abstraction layers. Modify the existing functions in place.
- Each slice must pass the existing test suite before the next slice begins.
- Commit message format: `[slice-N] <description>`

---

## Slice 1 — Remove success-path signals from host memory decision logic

**Files to modify:** `crawl_fetch_runtime.py`, `metrics.py`

**Do NOT modify** `host_protection_memory.py` in this slice. The fields
`patchright_success` and `real_chrome_success` still exist on `HostProtectionPolicy`
and are still written — they are still consumed by `_extend_browser_engine_attempts_after_block`
for mid-run post-block engine escalation. That is a valid short-term block-derived use.
Do not remove them from the model yet. That is Slice 5 (future, not in this brief).

### 1a. `_try_browser_http_handoff` — remove host-success guards

Current (lines 668–674):
```python
if not (
    host_policy.prefer_browser
    or host_policy.patchright_success
    or host_policy.real_chrome_success
    or context.prefer_curl_handoff
):
    return None
```

Replace with:
```python
if not (
    host_policy.prefer_browser
    or context.prefer_curl_handoff
):
    return None
```

Reason: `host_policy.patchright_success` and `host_policy.real_chrome_success` are
host-scoped TTL signals. They activate curl handoff based on a recent success on any
URL for the host regardless of surface. Only `context.prefer_curl_handoff` (which
comes from the domain/surface contract in `DomainRunProfile`) and
`host_policy.prefer_browser` (which is block-derived, not success-derived) are
legitimate guards here.

### 1b. `_browser_engine_attempts` — remove hard real_chrome lock from host success

Current (lines 1062–1063):
```python
if host_policy.real_chrome_success:
    return ["real_chrome"]
```

Delete these two lines entirely.

Reason: `host_policy.real_chrome_success` is a host-level TTL signal. Using it to
hard-lock the engine bypasses the domain contract and causes the Urban Outfitters
class of failure — a domain with no `DomainRunProfile` row gets locked to real_chrome
based on a recent success on a different URL on the same host.

The remaining block-derived logic in `_browser_engine_attempts` (lines 1064–1074)
is correct and must be kept:
```python
if host_policy.patchright_blocked and host_policy.prefer_browser:
    # escalate to real_chrome first
if host_policy.request_blocked or host_policy.prefer_browser or host_policy.last_block_vendor:
    # append real_chrome as fallback
```
These are block-derived signals and remain valid.

### 1c. `_handoff_cookie_engines` — remove host-success engine prioritisation

Current (lines 745–748):
```python
if host_policy.real_chrome_success and "real_chrome" not in preferred:
    preferred.append("real_chrome")
if host_policy.patchright_success and "patchright" not in preferred:
    preferred.append("patchright")
```

Delete both blocks.

Reason: After fixing 1a, the handoff guard now only fires when
`context.prefer_curl_handoff` or `host_policy.prefer_browser` is set.
The cookie engine order should come from `context.handoff_cookie_engine`
(resolved from the domain contract), which is already handled by the
`normalized_preferred` block above these lines. Host-success signals
must not influence which engine's cookies are tried.

### 1d. `metrics.py` — expand `memory_browser_first` to include contract-driven reason

Current:
```python
memory_browser_first = str(browser_diagnostics.get("browser_reason") or "").strip().lower() == "host-preference"
```

Replace with:
```python
memory_browser_first = str(browser_diagnostics.get("browser_reason") or "").strip().lower() in {
    "host-preference",
    "acquisition-contract",
}
```

Reason: After Slice 1, more runs will reach browser via `"acquisition-contract"` reason
(set in `apply_acquisition_contract_to_profile` when `prefer_browser=True` in the
saved contract). Without this fix, `memory_browser_first` will undercount during
and after the transition.

### Slice 1 verification

- Run the full test suite. All existing tests must pass.
- Manually verify: a domain with a saved `DomainRunProfile` row that has
  `preferred_browser_engine=real_chrome` still gets real_chrome, because
  `context.forced_browser_engine` is set from the contract.
- Manually verify: a domain with no `DomainRunProfile` row and no host block
  does not attempt curl handoff.

---

## Slice 2 — Expand `acquisition_contract` schema with rendering/traversal semantics

**Files to modify:** `domain_run_profile_service.py`, `crawl_fetch_runtime.py`,
`pipeline/core.py`

### 2a. `domain_run_profile_service.py` — add fields to `_empty_acquisition_contract`

Current:
```python
def _empty_acquisition_contract() -> dict[str, object]:
    return {
        "preferred_browser_engine": "auto",
        "prefer_browser": False,
        "prefer_curl_handoff": False,
        "handoff_cookie_engine": "auto",
        "last_quality_success": None,
        "stale_after_failures": {
            "failure_count": 0,
            "stale": False,
        },
    }
```

Replace with:
```python
def _empty_acquisition_contract() -> dict[str, object]:
    return {
        "preferred_browser_engine": "auto",
        "prefer_browser": False,
        "handoff_eligible": False,
        "handoff_cookie_engine": "auto",
        "required_rendering": False,
        "required_traversal": False,
        "required_network_payloads": False,
        "last_quality_success": None,
        "stale_after_failures": {
            "failure_count": 0,
            "stale": False,
        },
    }
```

Note: `prefer_curl_handoff` is replaced by `handoff_eligible`. `prefer_curl_handoff`
is removed from the schema. Existing DB rows that have `prefer_curl_handoff` will be
read by `normalize_acquisition_contract` and ignored (the field will not be
present in the normalised output). That is the intended behaviour — existing rows
will default `handoff_eligible=False` until the domain gets a new successful run
that writes the expanded contract.

### 2b. `domain_run_profile_service.py` — update `normalize_acquisition_contract`

Add the new fields to the return dict. Remove `prefer_curl_handoff`:

```python
def normalize_acquisition_contract(value: object) -> dict[str, object]:
    payload = dict(value or {}) if isinstance(value, Mapping) else {}
    # ... existing last_quality_success and stale_payload logic unchanged ...
    return {
        "preferred_browser_engine": _coerce_choice(
            payload.get("preferred_browser_engine"),
            _BROWSER_ENGINE_VALUES,
            default="auto",
        ),
        "prefer_browser": bool(payload.get("prefer_browser", False)),
        "handoff_eligible": bool(payload.get("handoff_eligible", False)),
        "handoff_cookie_engine": _coerce_choice(
            payload.get("handoff_cookie_engine"),
            _BROWSER_ENGINE_VALUES,
            default="auto",
        ),
        "required_rendering": bool(payload.get("required_rendering", False)),
        "required_traversal": bool(payload.get("required_traversal", False)),
        "required_network_payloads": bool(payload.get("required_network_payloads", False)),
        "last_quality_success": normalized_success,
        "stale_after_failures": {
            "failure_count": _coerce_int_clamped(
                stale_payload.get("failure_count"), default=0, minimum=0,
            ),
            "stale": bool(stale_payload.get("stale", False)),
        },
    }
```

### 2c. `domain_run_profile_service.py` — update `build_success_acquisition_contract`

Add `browser_diagnostics: dict[str, object]` parameter. Populate the new fields:

```python
def build_success_acquisition_contract(
    *,
    method: object,
    browser_engine: object,
    record_count: int,
    requested_fields: list[str],
    found_fields: list[str],
    source_run_id: int,
    browser_diagnostics: dict[str, object] | None = None,
    timestamp: str | None = None,
) -> dict[str, object]:
    diag = dict(browser_diagnostics or {})
    normalized_method = str(method or "").strip().lower()
    normalized_engine = _coerce_optional_choice(browser_engine, _BROWSER_ENGINE_VALUES)
    preferred_engine = normalized_engine if normalized_engine in {"patchright", "real_chrome"} else "auto"

    extraction_source = str(diag.get("extraction_source") or "").strip().lower()
    required_rendering = extraction_source in {"rendered_dom", "rendered_dom_visual"}
    required_traversal = bool(diag.get("traversal_activated"))
    required_network_payloads = int(diag.get("network_payload_count") or 0) > 0

    handoff_eligible = (
        normalized_method == "browser"
        and preferred_engine != "auto"
        and not required_rendering
        and not required_traversal
        and not required_network_payloads
    )
    handoff_engine = preferred_engine if handoff_eligible else "auto"

    requested_set = set(requested_fields or [])
    covered_fields = [f for f in list(found_fields or []) if f in requested_set]

    return normalize_acquisition_contract({
        "preferred_browser_engine": preferred_engine,
        "prefer_browser": normalized_method == "browser",
        "handoff_eligible": handoff_eligible,
        "handoff_cookie_engine": handoff_engine,
        "required_rendering": required_rendering,
        "required_traversal": required_traversal,
        "required_network_payloads": required_network_payloads,
        "last_quality_success": {
            "method": normalized_method or None,
            "browser_engine": normalized_engine,
            "record_count": int(record_count or 0),
            "field_coverage": {
                "requested": list(requested_fields or []),
                "found": covered_fields,
                "missing": [f for f in list(requested_fields or []) if f not in set(covered_fields)],
            },
            "source_run_id": int(source_run_id or 0),
            "timestamp": timestamp or datetime.now(UTC).isoformat(),
        },
        "stale_after_failures": {"failure_count": 0, "stale": False},
    })
```

### 2d. `domain_run_profile_service.py` — update `apply_acquisition_contract_to_profile`

Replace the `prefer_curl_handoff` application with `handoff_eligible`:

```python
def apply_acquisition_contract_to_profile(
    acquisition_profile: object,
    contract: object,
) -> dict[str, object]:
    profile = dict(acquisition_profile or {}) if isinstance(acquisition_profile, Mapping) else {}
    normalized = normalize_acquisition_contract(contract)
    stale_value = normalized.get("stale_after_failures")
    stale = dict(stale_value) if isinstance(stale_value, Mapping) else {}
    if bool(stale.get("stale")):
        profile["acquisition_contract_stale"] = True
        return profile
    engine = str(normalized.get("preferred_browser_engine") or "auto").strip().lower()
    cookie_engine = str(normalized.get("handoff_cookie_engine") or "auto").strip().lower()
    if bool(normalized.get("prefer_browser")):
        profile["prefer_browser"] = True
        profile.setdefault("browser_reason", "acquisition-contract")
    if engine in {"patchright", "real_chrome"} and not profile.get("forced_browser_engine"):
        profile["forced_browser_engine"] = engine
    if bool(normalized.get("handoff_eligible")):
        profile["prefer_curl_handoff"] = True          # keep legacy key for _FetchRuntimeContext
        profile["handoff_eligible"] = True
    if cookie_engine in {"patchright", "real_chrome"}:
        profile["handoff_cookie_engine"] = cookie_engine
    elif engine in {"patchright", "real_chrome"}:
        profile["handoff_cookie_engine"] = engine
    return profile
```

### 2e. `pipeline/core.py` — pass `browser_diagnostics` into `record_acquisition_contract_outcome`

In `_update_acquisition_contract_memory`, extract and pass diagnostics:

```python
async def _update_acquisition_contract_memory(
    context: _URLProcessingContext,
    *,
    acquisition_result,
    records: list[dict[str, object]],
    persisted_count: int,
    verdict: str,
) -> None:
    domain = normalize_domain(
        getattr(acquisition_result, "final_url", "") or context.url
    )
    if not domain:
        return
    diagnostics = mapping_or_empty(
        getattr(acquisition_result, "browser_diagnostics", {})
    )
    await record_acquisition_contract_outcome(
        context.session,
        domain=domain,
        surface=context.surface,
        source_run_id=int(context.run.id),
        method=getattr(acquisition_result, "method", None),
        browser_engine=str(diagnostics.get("browser_engine") or "").strip().lower(),
        browser_diagnostics=dict(diagnostics),          # NEW — pass full diagnostics
        requested_fields=repair_target_fields_for_surface(
            context.surface,
            list(context.requested_fields),
        ),
        records=records,
        persisted_count=persisted_count,
        quality_success=(
            persisted_count > 0
            and not _effective_blocked(acquisition_result)
            and verdict not in {VERDICT_BLOCKED, VERDICT_EMPTY}
        ),
        count_failure=verdict == VERDICT_LISTING_FAILED,   # Slice 4 will fix this
        stale_threshold=int(
            crawler_runtime_settings.acquisition_contract_stale_failure_threshold
        ),
    )
```

### 2f. `domain_run_profile_service.py` — update `record_acquisition_contract_outcome` signature

Add `browser_diagnostics: dict[str, object] | None = None` parameter and pass it
to `build_success_acquisition_contract`:

```python
async def record_acquisition_contract_outcome(
    session: AsyncSession,
    *,
    domain: str,
    surface: str,
    source_run_id: int,
    method: object,
    browser_engine: object,
    browser_diagnostics: dict[str, object] | None = None,
    requested_fields: list[str],
    records: list[dict[str, object]],
    persisted_count: int,
    quality_success: bool,
    count_failure: bool = True,
    stale_threshold: int,
) -> None:
    if quality_success:
        found_fields = sorted({
            str(field_name)
            for record in records
            if isinstance(record, dict)
            for field_name, value in record.items()
            if not str(field_name).startswith("_") and value not in (None, "", [], {})
        })
        await save_learned_acquisition_contract(
            session,
            domain=domain,
            surface=surface,
            source_run_id=source_run_id,
            contract=build_success_acquisition_contract(
                method=method,
                browser_engine=browser_engine,
                browser_diagnostics=browser_diagnostics,   # NEW
                record_count=persisted_count,
                requested_fields=requested_fields,
                found_fields=found_fields,
                source_run_id=source_run_id,
            ),
        )
        return
    if not count_failure:
        return
    await note_acquisition_contract_failure(
        session,
        domain=domain,
        surface=surface,
        threshold=stale_threshold,
    )
```

### Slice 2 verification

- A domain that succeeds via browser with `traversal_activated=True` must write
  `handoff_eligible=False` and `required_traversal=True` to its `DomainRunProfile`.
- A domain that succeeds via browser for cookie bootstrap only
  (`traversal_activated=False`, `network_payload_count=0`, `extraction_source=raw_html`)
  must write `handoff_eligible=True`.
- A domain that succeeds via HTTP must write `handoff_eligible=False` and
  `prefer_browser=False`.
- Confirm that existing DB rows with `prefer_curl_handoff=True` load without error
  (they will default `handoff_eligible=False` which is safe — curl handoff is
  disabled for them until the domain gets a new successful run).

---

## Slice 3 — Unified per-URL profile resolver for all run types

**Files to modify:** `domain_run_profile_service.py`, `pipeline/core.py`, `crawl_crud.py`

### 3a. Critical pre-condition — fix the early-return no-op in `apply_saved_acquisition_contract_for_url`

This is the most important fix in Slice 3. The current early-return in
`apply_saved_acquisition_contract_for_url` (domain_run_profile_service.py:385–395)
bypasses the saved domain contract whenever explicit settings already carry
`prefer_browser`, `forced_browser_engine`, or `prefer_curl_handoff`:

```python
explicit_contract = settings_view.acquisition_contract()
if (
    explicit_contract.get("last_quality_success")
    or explicit_contract.get("prefer_browser")
    or explicit_contract.get("prefer_curl_handoff")
    or str(explicit_contract.get("preferred_browser_engine") or "auto") != "auto"
):
    return apply_acquisition_contract_to_profile(acquisition_profile, explicit_contract)
```

For single-URL runs, these fields are already populated from the create-time merge in
`crawl_crud.py`, so this early-return fires every time and the per-URL reload is a
complete no-op that wastes a DB hit. For a stale contract that has `prefer_curl_handoff=True`
in the saved profile but should now be `handoff_eligible=False`, this means the bad
value is never corrected at runtime.

Replace with a merged approach — always load the saved contract, let explicit settings
win per-key but do not skip the saved contract entirely:

```python
async def apply_saved_acquisition_contract_for_url(
    session: AsyncSession,
    *,
    url: str,
    surface: str,
    settings_view,
    acquisition_profile: dict[str, object],
) -> dict[str, object]:
    saved_profile = await load_domain_run_profile(
        session,
        domain=normalize_domain(url),
        surface=surface,
    )
    if saved_profile is None:
        explicit_contract = settings_view.acquisition_contract()
        return apply_acquisition_contract_to_profile(acquisition_profile, explicit_contract)

    saved_contract = dict(saved_profile.profile or {}).get("acquisition_contract")
    if not isinstance(saved_contract, dict):
        explicit_contract = settings_view.acquisition_contract()
        return apply_acquisition_contract_to_profile(acquisition_profile, explicit_contract)

    # Explicit settings win per-key; saved contract fills the rest.
    # Stale saved contracts are respected — apply_acquisition_contract_to_profile
    # short-circuits and returns acquisition_contract_stale=True if stale.
    explicit_contract = settings_view.acquisition_contract()
    merged_contract = {**saved_contract, **{k: v for k, v in explicit_contract.items() if v}}
    return apply_acquisition_contract_to_profile(acquisition_profile, merged_contract)
```

### 3b. `domain_run_profile_service.py` — create `resolve_url_acquisition_recipe`

New function that returns fully merged settings for one URL, safe to call for both
single and batch runs:

```python
async def resolve_url_acquisition_recipe(
    session: AsyncSession,
    *,
    url: str,
    surface: str,
    explicit_settings: dict[str, object],
) -> dict[str, object]:
    """
    Returns merged acquisition settings for a single URL.
    Priority: explicit_settings > saved DomainRunProfile(domain, surface) > defaults.
    Safe to call per-URL for both single and batch runs.
    """
    normalized_domain = normalize_domain(url)
    saved = await load_domain_run_profile(session, domain=normalized_domain, surface=surface)
    if saved is None:
        return dict(explicit_settings)
    saved_profile = dict(saved.profile or {})
    merged = _merge_saved_run_profile(dict(explicit_settings), saved_profile)
    return merged
```

`_merge_saved_run_profile` is the existing function in `crawl_crud.py`. Move it to
`domain_run_profile_service.py` so it can be called from the pipeline without importing
`crawl_crud`. Update the import in `crawl_crud.py` to reference the new location.

### 3c. `pipeline/core.py` — call resolver per URL in the acquire stage

In `process_single_url` (or wherever `URLProcessingConfig` is built), before building
the `AcquisitionRequest`, call `resolve_url_acquisition_recipe` and apply the result:

```python
resolved_recipe = await resolve_url_acquisition_recipe(
    context.session,
    url=context.url,
    surface=context.surface,
    explicit_settings=context.run.settings_view.as_dict(),
)
# Use resolved_recipe to build AcquisitionRequest instead of raw run settings
```

This ensures batch runs get the same domain profile application as single-URL runs.

### 3d. `crawl_crud.py` — narrow the create-time merge

**Do NOT remove `_merge_saved_run_profile` from `create_crawl_run` for fetch_profile,
locality_profile, and diagnostics_profile.** Those sections are needed at create time
to configure run-level display, bounding, and storage settings.

Only stop merging `acquisition_contract` at create time, because the per-URL resolver
(3b) now owns it:

```python
# In _merge_saved_run_profile, remove the acquisition_contract merge block:
# DELETE these lines:
saved_contract = dict(saved.get("acquisition_contract") or {})
explicit_contract = dict(merged.get("acquisition_contract") or {})
if saved_contract or explicit_contract:
    merged["acquisition_contract"] = {**saved_contract, **explicit_contract}
```

### Slice 3 verification

- Run a batch job with URLs from a domain that has a saved `DomainRunProfile`.
  Confirm each URL in the batch uses the domain's `fetch_mode`, `geo_country`,
  and `acquisition_contract` settings.
- Run a single-URL job for the same domain. Behavior must be identical.
- Confirm that `apply_saved_acquisition_contract_for_url` no longer returns early
  for single-URL runs where the profile was merged at create time.

---

## Slice 4 — Centralise stale/failure policy in `domain_run_profile_service.py`

**Files to modify:** `pipeline/core.py`, `domain_run_profile_service.py`

### 4a. `pipeline/core.py` — pass raw outcome facts, remove local count_failure logic

Replace the current `count_failure=verdict == VERDICT_LISTING_FAILED` call-site logic.
Pass raw facts and let the service decide:

```python
await record_acquisition_contract_outcome(
    context.session,
    domain=domain,
    surface=context.surface,
    source_run_id=int(context.run.id),
    method=getattr(acquisition_result, "method", None),
    browser_engine=str(diagnostics.get("browser_engine") or "").strip().lower(),
    browser_diagnostics=dict(diagnostics),
    requested_fields=repair_target_fields_for_surface(
        context.surface,
        list(context.requested_fields),
    ),
    records=records,
    persisted_count=persisted_count,
    verdict=verdict,                                        # NEW — raw verdict
    blocked=_effective_blocked(acquisition_result),        # NEW — raw block fact
    # REMOVE: quality_success, count_failure, stale_threshold from call site
)
```

### 4b. `domain_run_profile_service.py` — move all failure policy into `record_acquisition_contract_outcome`

Replace the current signature and internals:

```python
async def record_acquisition_contract_outcome(
    session: AsyncSession,
    *,
    domain: str,
    surface: str,
    source_run_id: int,
    method: object,
    browser_engine: object,
    browser_diagnostics: dict[str, object] | None = None,
    requested_fields: list[str],
    records: list[dict[str, object]],
    persisted_count: int,
    verdict: str,
    blocked: bool,
) -> None:
    stale_threshold = int(
        crawler_runtime_settings.acquisition_contract_stale_failure_threshold
    )

    quality_success = (
        persisted_count > 0
        and not blocked
        and verdict not in {VERDICT_BLOCKED, VERDICT_EMPTY, VERDICT_LISTING_FAILED}
    )

    # Count a failure when the learned path produced no data on a surface
    # that was expected to succeed. Do NOT count failures caused by host blocking —
    # that is a host-level event, not a contract failure.
    count_failure = (
        not blocked
        and (
            verdict == VERDICT_LISTING_FAILED
            or (
                verdict in {VERDICT_EMPTY}
                and "detail" in str(surface or "")
                and persisted_count == 0
            )
        )
    )

    if quality_success:
        found_fields = sorted({
            str(field_name)
            for record in records
            if isinstance(record, dict)
            for field_name, value in record.items()
            if not str(field_name).startswith("_") and value not in (None, "", [], {})
        })
        await save_learned_acquisition_contract(
            session,
            domain=domain,
            surface=surface,
            source_run_id=source_run_id,
            contract=build_success_acquisition_contract(
                method=method,
                browser_engine=browser_engine,
                browser_diagnostics=browser_diagnostics,
                record_count=persisted_count,
                requested_fields=requested_fields,
                found_fields=found_fields,
                source_run_id=source_run_id,
            ),
        )
        return

    if count_failure:
        await note_acquisition_contract_failure(
            session,
            domain=domain,
            surface=surface,
            threshold=stale_threshold,
        )
```

Note on the blocked condition: `blocked=True` must not increment the failure counter.
A host block tells you nothing about whether the learned acquisition path (engine choice,
curl handoff eligibility) was wrong. Incrementing on blocks would age out valid
contracts purely because a site had a bad day or blocked a specific IP. Only count
failures where the path ran to completion and produced zero data.

### 4c. Remove `VERDICT_*` imports that are no longer needed at the call site in `core.py`

After this change, `core.py` passes `verdict` and `blocked` as raw strings/bools and
does not evaluate them locally. Remove any now-unused `VERDICT_*` imports if applicable.

### Slice 4 verification

- A blocked listing run must NOT increment the failure counter.
- A zero-record detail run (not blocked) must increment the failure counter.
- A zero-record listing run must increment and eventually mark contract stale.
- A successful listing run must reset the failure counter via `build_success_acquisition_contract`.

---

## Summary — files touched per slice

| Slice | Files modified |
|-------|----------------|
| 1 | crawl_fetch_runtime.py, metrics.py |
| 2 | domain_run_profile_service.py, crawl_fetch_runtime.py (context field), pipeline/core.py |
| 3 | domain_run_profile_service.py, pipeline/core.py, crawl_crud.py |
| 4 | domain_run_profile_service.py, pipeline/core.py |

## Slice 5 (future — not in this brief)

After all four slices are stable in production, `patchright_success` and
`real_chrome_success` can be removed from `HostProtectionPolicy`, `load_host_protection_policy`,
and `_host_policy_snapshot`. `last_success_method` can be demoted to observability-only
(kept in the row but not returned as a policy field). This is the final cleanup.
Do not attempt it until Slices 1–4 have been verified.