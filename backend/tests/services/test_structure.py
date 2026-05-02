from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SERVICES_ROOT = ROOT / "app" / "services"
EXTRACTION_MODULES = [
    SERVICES_ROOT / "extraction_runtime.py",
    SERVICES_ROOT / "extraction_context.py",
    SERVICES_ROOT / "crawl_fetch_runtime.py",
    SERVICES_ROOT / "detail_extractor.py",
    SERVICES_ROOT / "listing_extractor.py",
    SERVICES_ROOT / "structured_sources.py",
    SERVICES_ROOT / "field_value_core.py",
    SERVICES_ROOT / "field_value_candidates.py",
    SERVICES_ROOT / "field_value_dom.py",
]
GENERIC_EXTRACTION_MODULES = [
    SERVICES_ROOT / "js_state_mapper.py",
]
FIELD_POLICY_CONSUMERS = [
    SERVICES_ROOT / "crawl_crud.py",
    SERVICES_ROOT / "schema_service.py",
    SERVICES_ROOT / "review" / "__init__.py",
]
ALLOWED_PRIVATE_SERVICE_IMPORTS = {
    "_batch_runtime.py -> app.services.pipeline.core:_mark_run_failed",
    "_batch_runtime.py -> app.services.publish:_aggregate_verdict",
    "acquisition/browser_identity.py -> app.services.network_resolution:_accept_language_for_locale",
    "acquisition/browser_runtime.py -> app.services.acquisition.browser_capture:_MAX_CAPTURED_NETWORK_PAYLOADS",
    "acquisition/browser_runtime.py -> app.services.acquisition.browser_capture:_MAX_CAPTURED_NETWORK_PAYLOAD_BYTES",
    "acquisition/browser_runtime.py -> app.services.acquisition.browser_capture:_NETWORK_CAPTURE_QUEUE_SIZE",
    "acquisition/browser_runtime.py -> app.services.acquisition.browser_capture:_NETWORK_CAPTURE_WORKERS",
    "config/adapter_runtime_settings.py -> app.services.config.runtime_settings:_settings_config",
    "config/llm_runtime.py -> app.services.config.runtime_settings:_settings_config",
    "config/product_intelligence.py -> app.services.config.runtime_settings:_settings_config",
    "crawl_service.py -> app.services.pipeline.core:_mark_run_failed",
    "publish/__init__.py -> app.services.publish.verdict:_aggregate_verdict",
}
CONFIG_CONSTANT_NAME_MARKERS = (
    "SELECTOR",
    "TOKEN",
    "THRESHOLD",
    "TIMEOUT",
    "LIMIT",
    "RETRY",
    "PATH_MARKER",
)
ALLOWED_SERVICE_CONFIG_CONSTANTS = {
    ("acquisition/cookie_store.py", "_CHALLENGE_COOKIE_VALUE_TOKENS"),
    ("acquisition/cookie_store.py", "_CHALLENGE_LOCAL_STORAGE_NAME_TOKENS"),
    ("acquisition/cookie_store.py", "_CHALLENGE_LOCAL_STORAGE_VALUE_TOKENS"),
    ("crawl_fetch_runtime.py", "_RETRY_SENTINEL"),
    ("extract/detail_record_finalizer.py", "_VARIANT_OPTION_VALUE_NOISE_TOKENS"),
    ("extract/shared_variant_logic.py", "_VARIANT_AXIS_LABEL_NOISE_TOKENS"),
    ("extract/shared_variant_logic.py", "_VARIANT_GROUP_ATTR_NOISE_TOKENS"),
    ("extract/shared_variant_logic.py", "_VARIANT_OPTION_VALUE_NOISE_TOKENS"),
    ("field_value_dom.py", "_SECTION_CONTAINER_SELECTORS"),
    ("field_value_dom.py", "_SECTION_LABEL_SELECTOR"),
    ("normalizers/__init__.py", "_AVAILABILITY_TOKENS"),
    ("platform_policy.py", "_GENERIC_COMMERCE_TOKENS"),
    ("platform_policy.py", "_GENERIC_JOB_TOKENS"),
    ("selectors_runtime.py", "_SELECTOR_NOISE_FROZEN"),
}
DEFAULT_LOC_BUDGET = 1000
# Keep explicit budgets for coherent large owners. Budgets are set to roughly the
# current LOC plus 10% so growth requires a conscious update instead of a blanket
# threshold increase.
FILE_LOC_BUDGETS = {
    # Browser identity owns UA/timezone/device/runtime surface shaping.
    Path("app/services/acquisition/browser_identity.py"): 1765,
    # Browser runtime owns pooled browser lifecycle and context management.
    Path("app/services/acquisition/browser_runtime.py"): 2275,
    # Page flow owns navigation, readiness, artifact capture, and final browser shaping.
    Path("app/services/acquisition/browser_page_flow.py"): 1880,
    # Traversal owns readiness-aware pagination and bounded expansion loops.
    Path("app/services/acquisition/traversal.py"): 1965,
    # Fetch runtime remains the request/browser arbitration owner.
    Path("app/services/crawl_fetch_runtime.py"): 1235,
    # Detail extraction owns candidate arbitration and tier orchestration.
    Path("app/services/detail_extractor.py"): 1460,
    # Detail DOM extraction owns DOM fallback fields plus DOM variant recovery.
    Path("app/services/extract/detail_dom_extractor.py"): 1320,
    # Detail finalizer owns public-boundary cleanup and record repair.
    Path("app/services/extract/detail_record_finalizer.py"): 1090,
    # Shared variant logic owns generic axis and row reconciliation.
    Path("app/services/extract/shared_variant_logic.py"): 1020,
    # Listing extraction remains coherent but large enough to warrant an explicit budget.
    Path("app/services/listing_extractor.py"): 1395,
    # Shared DOM field recovery remains centralized here instead of fragmenting selectors.
    Path("app/services/field_value_dom.py"): 1550,
    # Canonical field coercion remains centralized here instead of scattering value policy.
    Path("app/services/field_value_core.py"): 1360,
    # Enrichment owns deterministic product normalization and job application.
    Path("app/services/data_enrichment/service.py"): 1300,
    # JS state mapping stays centralized to avoid adapter-specific drift.
    Path("app/services/js_state_mapper.py"): 1060,
    # LLM task runtime owns prompt validation, provider calls, cost logging, and typed errors.
    Path("app/services/llm_tasks.py"): 1080,
    # Pipeline core still owns the per-URL orchestration boundary.
    Path("app/services/pipeline/core.py"): 1320,
    # Product Intelligence service owns job + discovery orchestration with brand and enrichment LLM helpers.
    Path("app/services/product_intelligence/service.py"): 1160,
}


def _module_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        if isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def _loc_budget_for(path: Path) -> int:
    return FILE_LOC_BUDGETS.get(path, DEFAULT_LOC_BUDGET)


def _service_rel(path: Path) -> str:
    return path.relative_to(SERVICES_ROOT).as_posix()


def _module_level_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in tree.body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                names.add(target.id)
    return names


def _private_service_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    rel = _service_rel(path)
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        if not node.module.startswith("app.services."):
            continue
        for alias in node.names:
            if alias.name.startswith("_"):
                imports.add(f"{rel} -> {node.module}:{alias.name}")
    return imports


def test_service_files_stay_under_loc_budget() -> None:
    oversized: list[str] = []
    for path in SERVICES_ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT)
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        budget = _loc_budget_for(rel)
        if line_count > budget:
            oversized.append(f"{rel} has {line_count} LOC (budget {budget})")
    assert oversized == []


def test_extraction_modules_do_not_import_llm_runtime_layers() -> None:
    offenders: list[str] = []
    for path in EXTRACTION_MODULES:
        imports = _module_imports(path)
        if any(module.startswith("app.services.llm") for module in imports):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_generic_extraction_modules_do_not_import_site_adapters() -> None:
    offenders: list[str] = []
    for path in GENERIC_EXTRACTION_MODULES:
        imports = _module_imports(path)
        if any(module.startswith("app.services.adapters.") for module in imports):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_field_policy_is_the_only_field_rule_entrypoint() -> None:
    assert not (SERVICES_ROOT / "field_alias_policy.py").exists()
    assert not (SERVICES_ROOT / "requested_field_policy.py").exists()
    assert not (SERVICES_ROOT / "simple_crawler.py").exists()

    missing_imports: list[str] = []
    for path in FIELD_POLICY_CONSUMERS:
        imports = _module_imports(path)
        if "app.services.field_policy" not in imports:
            missing_imports.append(str(path.relative_to(ROOT)))
    assert missing_imports == []


def test_new_config_like_modules_stay_under_services_config() -> None:
    offenders = [
        _service_rel(path)
        for path in SERVICES_ROOT.rglob("*.py")
        if "config" not in path.relative_to(SERVICES_ROOT).parts
        if path.name in {"config.py", "settings.py", "constants.py"}
        or path.name.endswith("_constants.py")
    ]
    assert offenders == []


def test_new_service_level_config_constants_are_not_added_outside_config() -> None:
    offenders: list[str] = []
    for path in SERVICES_ROOT.rglob("*.py"):
        rel_parts = path.relative_to(SERVICES_ROOT).parts
        if "config" in rel_parts:
            continue
        rel = _service_rel(path)
        for name in _module_level_names(path):
            if not name.isupper():
                continue
            if not any(marker in name for marker in CONFIG_CONSTANT_NAME_MARKERS):
                continue
            if (rel, name) not in ALLOWED_SERVICE_CONFIG_CONSTANTS:
                offenders.append(f"{rel}:{name}")
    assert sorted(offenders) == []


def test_data_enrichment_taxonomy_matching_does_not_use_manual_category_alias_maps() -> (
    None
):
    config_text = (SERVICES_ROOT / "config" / "data_enrichment.py").read_text(
        encoding="utf-8"
    )
    forbidden = (
        "DATA_ENRICHMENT_TAXONOMY_TOKEN_ALIASES",
        "DATA_ENRICHMENT_TAXONOMY_CONTEXTUAL_TOKEN_ALIASES",
    )
    assert [name for name in forbidden if name in config_text] == []


def test_private_service_imports_do_not_drift() -> None:
    offenders: set[str] = set()
    for path in SERVICES_ROOT.rglob("*.py"):
        offenders.update(_private_service_imports(path))
    assert offenders == ALLOWED_PRIVATE_SERVICE_IMPORTS
