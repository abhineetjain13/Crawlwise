"""
End-to-end extraction coverage test harness.

Runs acquire → discover → extract for a set of URLs and reports
field coverage, data sources hit, and extraction quality.

Usage:
    cd backend
    set PYTHONPATH=.
    python run_coverage_test.py
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings
from app.services.acquisition.acquirer import acquire
from app.services.acquisition.blocked_detector import detect_blocked_page
from app.services.adapters.registry import run_adapter
from app.services.discover.service import DiscoveryManifest, discover_sources
from app.services.extract.listing_extractor import extract_listing_records
from app.services.extract.service import extract_candidates
from app.services.extract.json_extractor import extract_json_listing, extract_json_detail


# ── Test URLs ──
TEST_URLS: list[tuple[str, str, str]] = [
    # (label, url, surface)
    # Sandboxes
    ("S01 web-scraping.dev listing", "https://web-scraping.dev/products", "ecommerce_listing"),
    ("S05 books.toscrape listing", "https://books.toscrape.com/catalogue/page-1.html", "ecommerce_listing"),
    ("S07 quotes.toscrape listing", "https://quotes.toscrape.com/", "ecommerce_listing"),
    ("S11 webscraper.io laptops", "https://webscraper.io/test-sites/e-commerce/allinone/computers/laptops", "ecommerce_listing"),
    ("S18 oxylabs sandbox listing", "https://sandbox.oxylabs.io/products", "ecommerce_listing"),
    ("S15 scrapethissite simple", "https://www.scrapethissite.com/pages/simple/", "ecommerce_listing"),
    # Real commerce listings
    ("LC13 ifixit parts", "https://www.ifixit.com/Parts", "ecommerce_listing"),
    ("LC15 thriftbooks browse", "https://www.thriftbooks.com/browse/?b.search=science", "ecommerce_listing"),
    # Under Armour
    ("UA mens listing", "https://www.underarmour.com/en-us/c/mens/", "ecommerce_listing"),
    # JSON APIs (RD section)
    ("RD12 restcountries", "https://restcountries.com/v3.1/name/germany", "ecommerce_listing"),
    ("RD20 cocktaildb", "https://www.thecocktaildb.com/api/json/v1/1/search.php?s=margarita", "ecommerce_listing"),
    # Detail pages
    ("S02 web-scraping.dev detail", "https://web-scraping.dev/product/1", "ecommerce_detail"),
    ("S06 books.toscrape detail", "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html", "ecommerce_detail"),
]

CORE_LISTING_FIELDS = {"title", "price", "url", "image_primary", "brand", "rating"}
CORE_DETAIL_FIELDS = {"title", "price", "description", "image_primary", "brand", "rating", "availability", "sku"}


@dataclass
class CoverageReport:
    label: str
    url: str
    surface: str
    engine: str = ""
    http_status: str = ""
    blocked: bool = False
    blocked_reason: str = ""
    record_count: int = 0
    fields_extracted: list[str] = field(default_factory=list)
    fields_missing: list[str] = field(default_factory=list)
    sources_hit: list[str] = field(default_factory=list)
    sources_missed: list[str] = field(default_factory=list)
    coverage_score: int = 0
    issues: list[str] = field(default_factory=list)
    manifest_summary: dict = field(default_factory=dict)
    sample_record: dict = field(default_factory=dict)
    elapsed_s: float = 0.0


ALL_DATA_SOURCES = [
    "DOM", "JSON-LD", "Inline JSON / Hydrated State", "Open Graph",
    "Data Attributes", "Network Payloads", "Hidden DOM", "Tables", "Microdata",
]


def _manifest_sources(manifest: DiscoveryManifest) -> list[str]:
    """Which data source types were found (non-empty) in the manifest."""
    hit = []
    if manifest.json_ld:
        hit.append("JSON-LD")
    if manifest.next_data:
        hit.append("Inline JSON / Hydrated State")
    if manifest._hydrated_states:
        hit.append("Inline JSON / Hydrated State")
    if manifest.embedded_json:
        hit.append("Inline JSON / Hydrated State")
    if manifest.open_graph:
        hit.append("Open Graph")
    if manifest.network_payloads:
        hit.append("Network Payloads")
    if manifest.hidden_dom:
        hit.append("Hidden DOM")
    if manifest.tables:
        hit.append("Tables")
    if manifest.microdata:
        hit.append("Microdata")
    if manifest.adapter_data:
        hit.append("Adapter")
    return list(set(hit))  # dedupe


def _compute_score(report: CoverageReport) -> int:
    """Score 0-10 based on record count, field coverage, and source diversity."""
    score = 0
    if report.blocked:
        return 0
    if report.record_count == 0:
        return 1
    # records: up to 3 points
    if report.record_count >= 10:
        score += 3
    elif report.record_count >= 3:
        score += 2
    else:
        score += 1
    # fields: up to 4 points
    core = CORE_LISTING_FIELDS if "listing" in report.surface else CORE_DETAIL_FIELDS
    present = set(report.fields_extracted) & core
    score += min(4, len(present))
    # sources: up to 3 points
    score += min(3, len(report.sources_hit))
    return min(10, score)


async def _test_url(label: str, url: str, surface: str, run_id: int) -> CoverageReport:
    report = CoverageReport(label=label, url=url, surface=surface)
    t0 = time.perf_counter()
    is_listing = surface in ("ecommerce_listing", "job_listing")

    try:
        acq = await asyncio.wait_for(acquire(run_id, url), timeout=45)
    except Exception as e:
        report.issues.append(f"Acquisition failed: {e}")
        report.elapsed_s = time.perf_counter() - t0
        return report

    report.engine = acq.method or "unknown"

    # Blocked detection
    if acq.content_type != "json":
        blocked = detect_blocked_page(acq.html or "")
        if blocked.is_blocked:
            report.blocked = True
            report.blocked_reason = blocked.reason or ""
            report.issues.append(f"BLOCKED: {blocked.reason}")
            report.elapsed_s = time.perf_counter() - t0
            return report

    # JSON-first path
    if acq.content_type == "json" and acq.json_data is not None:
        report.sources_hit.append("JSON API")
        if is_listing:
            records = extract_json_listing(acq.json_data, url, max_records=50)
        else:
            records = extract_json_detail(acq.json_data, url)
        report.record_count = len(records)
        if records:
            all_fields = set()
            for r in records:
                all_fields.update(k for k, v in r.items() if v and not k.startswith("_"))
            report.fields_extracted = sorted(all_fields)
            report.sample_record = {k: v for k, v in records[0].items() if not k.startswith("_")}
        report.sources_missed = [s for s in ALL_DATA_SOURCES if s not in report.sources_hit]
        report.coverage_score = _compute_score(report)
        report.elapsed_s = time.perf_counter() - t0
        return report

    html = acq.html or ""
    if not html:
        report.issues.append("Empty HTML after acquisition")
        report.elapsed_s = time.perf_counter() - t0
        return report

    # Discover
    adapter_result = await run_adapter(url, html, surface)
    adapter_records = adapter_result.records if adapter_result else []
    manifest = discover_sources(html, acq.network_payloads, adapter_records)

    report.sources_hit = _manifest_sources(manifest)
    if not report.sources_hit:
        report.sources_hit.append("DOM")  # we always parse DOM
    else:
        report.sources_hit.append("DOM")
    report.sources_hit = sorted(set(report.sources_hit))
    report.sources_missed = sorted(set(ALL_DATA_SOURCES) - set(report.sources_hit))

    report.manifest_summary = {
        "json_ld_count": len(manifest.json_ld),
        "hydrated_states": len(manifest._hydrated_states),
        "embedded_json": len(manifest.embedded_json),
        "open_graph_keys": list(manifest.open_graph.keys()) if manifest.open_graph else [],
        "network_payloads": len(manifest.network_payloads),
        "hidden_dom": len(manifest.hidden_dom),
        "tables": len(manifest.tables),
        "microdata": len(manifest.microdata),
        "adapter_data": len(manifest.adapter_data),
    }

    # Extract
    if is_listing:
        target_fields = {"title", "price", "url", "image_primary", "brand", "rating",
                         "availability", "description", "sku", "category"}
        records = extract_listing_records(
            html=html, surface=surface, target_fields=target_fields,
            page_url=url, max_records=50, manifest=manifest,
        )
        report.record_count = len(records)
        if records:
            all_fields = set()
            for r in records:
                all_fields.update(k for k, v in r.items() if v and not k.startswith("_"))
            report.fields_extracted = sorted(all_fields)
            report.sample_record = {k: v for k, v in records[0].items() if not k.startswith("_")}
            core = CORE_LISTING_FIELDS
            report.fields_missing = sorted(core - set(report.fields_extracted))
        else:
            report.fields_missing = sorted(CORE_LISTING_FIELDS)
            report.issues.append("0 records extracted from listing page")
    else:
        additional_fields = list(CORE_DETAIL_FIELDS | {"currency", "category", "url"})
        candidates, _trace = extract_candidates(
            url=url, surface=surface, html=html,
            manifest=manifest,
            additional_fields=additional_fields,
        )
        record = {}
        for fname, rows in candidates.items():
            if rows:
                best = rows[0]
                val = best.get("value", "")
                if val:
                    record[fname] = val
        report.record_count = 1 if record else 0
        all_fields = set(record.keys())
        report.fields_extracted = sorted(all_fields)
        report.fields_missing = sorted(CORE_DETAIL_FIELDS - all_fields)
        report.sample_record = record

    if report.record_count == 0:
        report.issues.append("Zero records extracted")
    elif report.record_count < 3 and is_listing:
        report.issues.append(f"Only {report.record_count} records — possible pagination/load-more failure")

    report.coverage_score = _compute_score(report)
    report.elapsed_s = time.perf_counter() - t0
    return report


async def main():
    reports: list[CoverageReport] = []
    for i, (label, url, surface) in enumerate(TEST_URLS):
        print(f"\n{'='*70}")
        print(f"[{i+1}/{len(TEST_URLS)}] {label}")
        print(f"  URL: {url}")
        print(f"  Surface: {surface}")
        report = await _test_url(label, url, surface, run_id=9000 + i)
        reports.append(report)
        status = "BLOCKED" if report.blocked else f"{report.record_count} records, score={report.coverage_score}/10"
        print(f"  Engine: {report.engine}")
        print(f"  Result: {status}")
        print(f"  Fields: {report.fields_extracted}")
        print(f"  Missing: {report.fields_missing}")
        print(f"  Sources hit: {report.sources_hit}")
        print(f"  Sources missed: {report.sources_missed}")
        if report.issues:
            print(f"  Issues: {report.issues}")
        print(f"  Time: {report.elapsed_s:.1f}s")
        if report.sample_record:
            sample = {k: (str(v)[:80] if isinstance(v, str) and len(str(v)) > 80 else v)
                      for k, v in list(report.sample_record.items())[:8]}
            print(f"  Sample: {json.dumps(sample, indent=2, default=str)}")

    # Summary
    print(f"\n{'='*70}")
    print("COVERAGE SUMMARY")
    print(f"{'='*70}")
    print(f"{'Label':<35} {'Score':>5} {'Recs':>5} {'Fields':>6} {'Engine':<10} {'Issues'}")
    print("-" * 100)
    for r in reports:
        issues_str = "; ".join(r.issues[:2]) if r.issues else "OK"
        print(f"{r.label:<35} {r.coverage_score:>5}/10 {r.record_count:>5} {len(r.fields_extracted):>6} {r.engine:<10} {issues_str}")

    avg_score = sum(r.coverage_score for r in reports) / len(reports) if reports else 0
    print(f"\nAverage coverage score: {avg_score:.1f}/10")

    # Save report
    out_dir = Path(settings.artifacts_dir) / "coverage_reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"coverage_{ts}.json"
    serializable = []
    for r in reports:
        serializable.append({
            "label": r.label, "url": r.url, "surface": r.surface,
            "engine": r.engine, "blocked": r.blocked, "blocked_reason": r.blocked_reason,
            "record_count": r.record_count,
            "fields_extracted": r.fields_extracted, "fields_missing": r.fields_missing,
            "sources_hit": r.sources_hit, "sources_missed": r.sources_missed,
            "coverage_score": r.coverage_score, "issues": r.issues,
            "manifest_summary": r.manifest_summary,
            "sample_record": {k: str(v)[:200] for k, v in r.sample_record.items()},
            "elapsed_s": round(r.elapsed_s, 2),
        })
    out_path.write_text(json.dumps(serializable, indent=2, default=str))
    print(f"\nReport saved to: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
