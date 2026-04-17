"""
Ad-hoc extraction smoke for plan audit URLs.

Usage:
    cd backend
    set PYTHONPATH=.
    .venv\Scripts\python.exe run_audit_smoke.py
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from app.services.acquisition.acquirer import AcquisitionRequest, acquire
from app.services.acquisition.blocked_detector import detect_blocked_page
from app.services.extract.listing_extractor import extract_listing_records
from app.services.discover import parse_page_sources

TEST_SITES: list[dict] = [
    {
        "name": "Clark Associates careers (iCIMS embed)",
        "url": "https://careers.clarkassociatesinc.biz/",
        "surface": "ecommerce_listing",
        "page_type": "category",
        "expect_min_records": 2,
    },
    {
        "name": "Klingspor jobs",
        "url": "https://www.klingspor.com/jobs",
        "surface": "ecommerce_listing",
        "page_type": "category",
        "expect_min_records": 1,
    },
    {
        "name": "LCBHS careers",
        "url": "https://lcbhs.net/careers/",
        "surface": "ecommerce_listing",
        "page_type": "category",
        "expect_min_records": 1,
    },
    {
        "name": "UltiPro/UKG job board",
        "url": "https://recruiting.ultipro.com/KAP1002KAPC/JobBoard/1e739e24-c237-44f3-9f7a-310b0cec4162/?q=&o=postedDateDesc",
        "surface": "ecommerce_listing",
        "page_type": "category",
        "expect_min_records": 2,
    },
    {
        "name": "Ganni dresses listing",
        "url": "https://www.ganni.com/en-gb/dresses/",
        "surface": "ecommerce_listing",
        "page_type": "category",
        "expect_min_records": 2,
    },
    {
        "name": "Phase Eight dresses listing",
        "url": "https://www.phase-eight.com/clothing/dresses/",
        "surface": "ecommerce_listing",
        "page_type": "category",
        "expect_min_records": 2,
    },
]


def _resolve_effective_surface(surface: str, diagnostics: dict) -> str:
    """Mirror the pipeline's surface resolution from acquisition diagnostics."""
    effective = str(diagnostics.get("surface_effective") or "").strip().lower()
    if effective in {"job_listing", "job_detail", "ecommerce_listing", "ecommerce_detail"}:
        return effective
    return surface


async def _run_one(site: dict, run_id: int) -> dict:
    name = site["name"]
    url = site["url"]
    surface = site["surface"]
    started = time.perf_counter()
    result_entry: dict = {"name": name, "url": url, "surface": surface}

    try:
        acq = await asyncio.wait_for(
            acquire(
                AcquisitionRequest(
                    run_id=run_id,
                    url=url,
                    surface=surface,
                    traversal_mode=None,
                    max_pages=5,
                    max_scrolls=5,
                    sleep_ms=0,
                    requested_fields=[],
                )
            ),
            timeout=90,
        )
        diag = acq.diagnostics or {}
        result_entry["method"] = acq.method
        result_entry["outcome"] = acq.outcome
        result_entry["html_len"] = len(acq.html or "")
        result_entry["content_type"] = acq.content_type
        result_entry["network_payloads"] = len(acq.network_payloads or [])
        result_entry["js_shell_detected"] = diag.get("curl_needs_browser", False)
        result_entry["browser_used"] = diag.get("browser_used", False)
        result_entry["browser_attempt"] = diag.get("browser_attempt", False)
        result_entry["promoted_browser_used"] = diag.get("promoted_browser_used", False)
        result_entry["promoted_source_used"] = diag.get("promoted_source_used")

        # Blocked check
        if acq.content_type == "html" and acq.html:
            blocked = detect_blocked_page(acq.html)
            result_entry["blocked"] = blocked.as_dict()
        else:
            result_entry["blocked"] = None

        if acq.content_type == "json":
            result_entry["elapsed_s"] = round(time.perf_counter() - started, 2)
            result_entry["ok"] = True
            result_entry["records"] = 0
            result_entry["note"] = "JSON API response"
            return result_entry

        html = acq.html or ""

        # Resolve effective surface the same way the pipeline does
        effective_surface = _resolve_effective_surface(surface, diag)
        result_entry["effective_surface"] = effective_surface

        # Source parsing
        parsed_sources = parse_page_sources(html)
        result_entry["json_ld_count"] = len(parsed_sources.get("json_ld") or [])
        result_entry["has_next_data"] = bool(parsed_sources.get("next_data"))
        result_entry["hydrated_states"] = len(parsed_sources.get("hydrated_states") or [])

        # Extract using effective surface
        records = extract_listing_records(
            html, effective_surface, set(), page_url=url, max_records=50,
            xhr_payloads=acq.network_payloads or [],
        )
        result_entry["records"] = len(records)
        result_entry["record_sources"] = list({r.get("_source", "?") for r in records})
        if records:
            sample = records[0]
            result_entry["sample_fields"] = [k for k in sample.keys() if not k.startswith("_")]
            result_entry["sample_title"] = str(sample.get("title", ""))[:120]
            result_entry["sample_url"] = str(sample.get("url", ""))[:200]

        expect_min = site.get("expect_min_records", 0)
        result_entry["ok"] = len(records) >= expect_min
        if not result_entry["ok"]:
            result_entry["issue"] = f"Expected >= {expect_min} records, got {len(records)}"

        if not result_entry["ok"]:
            result_entry["html_head"] = html[:500]

    except Exception as exc:
        result_entry["ok"] = False
        result_entry["error"] = f"{type(exc).__name__}: {exc}"

    result_entry["elapsed_s"] = round(time.perf_counter() - started, 2)
    return result_entry


async def main():
    print(f"Running audit smoke tests for {len(TEST_SITES)} sites...")
    print("=" * 70)
    results = []
    for i, site in enumerate(TEST_SITES):
        run_id = 8000 + i
        print(f"\n[{i+1}/{len(TEST_SITES)}] {site['name']}")
        print(f"  URL: {site['url']}")
        result = await _run_one(site, run_id)
        results.append(result)

        status = "PASS" if result.get("ok") else "FAIL"
        print(f"  Status: {status}")
        print(f"  Outcome: {result.get('outcome', '?')}")
        print(f"  Method: {result.get('method', '?')}, HTML: {result.get('html_len', 0):,}")
        print(f"  Effective surface: {result.get('effective_surface', '?')}")
        if result.get("promoted_source_used"):
            print(f"  Promoted: {result['promoted_source_used'].get('url', '')[:80]}")
            print(f"  Promoted browser: {result.get('promoted_browser_used')}")
        print(f"  Records: {result.get('records', '?')}, Sources: {result.get('record_sources', [])}")
        if result.get("sample_title"):
            print(f"  Sample: {result['sample_title']}")
        if result.get("issue"):
            print(f"  Issue: {result['issue']}")
        if result.get("error"):
            print(f"  Error: {result['error']}")
        print(f"  Elapsed: {result.get('elapsed_s', 0)}s")

    # Summary
    print("\n" + "=" * 70)
    passed = sum(1 for r in results if r.get("ok"))
    total = len(results)
    print(f"Results: {passed}/{total} passed")
    for r in results:
        status = "PASS" if r.get("ok") else "FAIL"
        extra = f" [{r.get('outcome','')}]" if r.get("outcome") else ""
        print(f"  [{status}] {r['name']}{extra}")

    # Write report
    report_dir = Path("artifacts/audit_smoke")
    report_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report_path = report_dir / f"audit_smoke_{ts}.json"
    report_path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"\nReport: {report_path}")

    if passed < total:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
