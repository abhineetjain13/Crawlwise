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
    ("acquisition/browser_identity.py", "_HOST_OS_UA_TOKENS"),
    ("acquisition/browser_page_flow.py", "_ACCESSIBILITY_SNAPSHOT_TIMEOUT_SECONDS"),
    ("acquisition/cookie_store.py", "_CHALLENGE_COOKIE_VALUE_TOKENS"),
    ("acquisition/cookie_store.py", "_CHALLENGE_LOCAL_STORAGE_NAME_TOKENS"),
    ("acquisition/cookie_store.py", "_CHALLENGE_LOCAL_STORAGE_VALUE_TOKENS"),
    ("crawl_fetch_runtime.py", "_RETRY_SENTINEL"),
    ("detail_extractor.py", "_VARIANT_OPTION_VALUE_NOISE_TOKENS"),
    ("extract/listing_candidate_ranking.py", "_EDITORIAL_URL_TOKENS"),
    ("extract/shared_variant_logic.py", "_VARIANT_AXIS_ALLOWED_SINGLE_TOKENS"),
    ("extract/shared_variant_logic.py", "_VARIANT_AXIS_GENERIC_TOKENS"),
    ("extract/shared_variant_logic.py", "_VARIANT_AXIS_LABEL_NOISE_TOKENS"),
    ("extract/shared_variant_logic.py", "_VARIANT_GROUP_ATTR_NOISE_TOKENS"),
    ("extract/shared_variant_logic.py", "_VARIANT_OPTION_VALUE_NOISE_TOKENS"),
    ("field_value_dom.py", "_SECTION_CONTAINER_SELECTORS"),
    ("field_value_dom.py", "_SECTION_LABEL_SELECTOR"),
    ("field_value_dom.py", "_SECTION_LABEL_SKIP_TOKENS"),
    ("listing_extractor.py", "_PRICE_NODE_SELECTORS"),
    ("normalizers/__init__.py", "_AVAILABILITY_TOKENS"),
    ("platform_policy.py", "_GENERIC_COMMERCE_TOKENS"),
    ("platform_policy.py", "_GENERIC_JOB_TOKENS"),
    ("selector_self_heal.py", "_SELECTOR_SYNTHESIS_ALLOWED_ATTRS"),
    ("selector_self_heal.py", "_SELECTOR_SYNTHESIS_DROP_TAGS"),
    ("selector_self_heal.py", "_SELECTOR_SYNTHESIS_LOW_VALUE_TAGS"),
    ("selectors_runtime.py", "_LISTING_FIELD_SELECTORS"),
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
    Path("app/services/acquisition/browser_page_flow.py"): 1645,
    # Traversal owns readiness-aware pagination and bounded expansion loops.
    Path("app/services/acquisition/traversal.py"): 1965,
    # Fetch runtime remains the request/browser arbitration owner.
    Path("app/services/crawl_fetch_runtime.py"): 1165,
    # Detail extraction remains the single owner for structured, DOM, and variant recovery.
    Path("app/services/detail_extractor.py"): 3205,
    # Listing extraction remains coherent but large enough to warrant an explicit budget.
    Path("app/services/listing_extractor.py"): 1655,
    # Shared DOM field recovery remains centralized here instead of fragmenting selectors.
    Path("app/services/field_value_dom.py"): 1265,
    # JS state mapping stays centralized to avoid adapter-specific drift.
    Path("app/services/js_state_mapper.py"): 1150,
    # Pipeline core still owns the per-URL orchestration boundary.
    Path("app/services/pipeline/core.py"): 1180,
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
