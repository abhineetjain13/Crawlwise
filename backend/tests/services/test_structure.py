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
