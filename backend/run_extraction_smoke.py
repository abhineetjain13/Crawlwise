"""
Extraction pipeline smoke runner for complex TEST_SITES validation.

Tests the full acquisition -> discovery -> extraction path without a database.

Usage:
    cd backend
    set PYTHONPATH=.
    python run_extraction_smoke.py
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from app.services.acquisition.acquirer import acquire
from app.services.extract.listing_extractor import extract_listing_records
from app.services.extract.service import extract_candidates
from app.services.discover import parse_page_sources
from app.services.semantic_detail_extractor import extract_semantic_detail_data

TEST_SITES: list[dict] = [
    # --- Client demo URLs ---
    {
        "name": "Adorama Tamron lens PDP",
        "url": "https://www.adorama.com/tamron-35-100mm-f2-8-di-iii-vxd-lens-sony-e-mount/p/tm35100e",
        "surface": "ecommerce_detail",
        "page_type": "pdp",
        "expect_fields": ["title"],
    },
    {
        "name": "Dice.com jobs listing",
        "url": "https://www.dice.com/jobs",
        "surface": "ecommerce_listing",
        "page_type": "category",
        "expect_min_records": 2,
    },
    {
        "name": "Dice.com job detail",
        # Dice job-detail URLs are volatile and may need to be refreshed when listings expire.
        "url": "https://www.dice.com/job-detail/b3a0711d-49e9-4bcf-bab5-92dddfa53533",
        "surface": "ecommerce_detail",
        "page_type": "pdp",
        "expect_fields": ["title"],
        "skip_on_404": True,
    },
    {
        "name": "SSENSE jacket PDP",
        "url": "https://www.ssense.com/en-us/women/product/simone-rocha/black-sailor-collar-workwear-bow-denim-jacket/19231481",
        "surface": "ecommerce_detail",
        "page_type": "pdp",
        "expect_fields": ["title"],
    },
    {
        "name": "Arc'teryx shoe PDP",
        "url": "https://arcteryx.com/us/en/shop/mens/sylan-2-shoe-0155",
        "surface": "ecommerce_detail",
        "page_type": "pdp",
        "expect_fields": ["title"],
    },
    # --- Batch 2: diverse sites ---
    {
        "name": "Adafruit electronics PDP",
        "url": "https://www.adafruit.com/product/5700",
        "surface": "ecommerce_detail",
        "page_type": "pdp",
        "expect_fields": ["title", "price"],
    },
    {
        "name": "SparkFun electronics PDP",
        "url": "https://www.sparkfun.com/products/19030",
        "surface": "ecommerce_detail",
        "page_type": "pdp",
        "expect_fields": ["title", "price"],
    },
    {
        "name": "Open Food Facts Coca Cola data PDP",
        "url": "https://world.openfoodfacts.org/product/5449000000996/coca-cola-original-taste",
        "surface": "ecommerce_detail",
        "page_type": "pdp",
        "expect_fields": ["title"],
    },
    {
        "name": "AutoZone oil filters listing",
        "url": "https://www.autozone.com/filters-and-pcv/oil-filter",
        "surface": "ecommerce_listing",
        "page_type": "category",
        "expect_min_records": 2,
    },
    {
        "name": "Puma womens tops listing",
        "url": "https://in.puma.com/in/en/womens/womens-clothing/womens-clothing-t-shirts-and-tops",
        "surface": "ecommerce_listing",
        "page_type": "category",
        "expect_min_records": 2,
    },
]


async def _run_one(site: dict, run_id: int) -> dict:
    name = site["name"]
    url = site["url"]
    surface = site["surface"]
    page_type = site["page_type"]
    started = time.perf_counter()
    result_entry: dict = {"name": name, "url": url, "surface": surface}

    try:
        # Phase 1: Acquire
        acquire_kwargs: dict[str, object] = {
            "surface": surface,
            "traversal_mode": None,
            "max_pages": 5,
            "max_scrolls": 5,
            "sleep_ms": 0,
            "requested_fields": [],
        }
        if page_type == "category":
            # Category runs exercise explicit traversal mode wiring in acquisition.
            acquire_kwargs["traversal_mode"] = "scroll"
        acq = await asyncio.wait_for(acquire(run_id=run_id, url=url, **acquire_kwargs), timeout=45)
        result_entry["method"] = acq.method
        result_entry["html_len"] = len(acq.html or "")
        result_entry["content_type"] = acq.content_type
        result_entry["network_payloads"] = len(acq.network_payloads or [])
        js_shell = (acq.diagnostics or {}).get("curl_needs_browser", False)
        result_entry["js_shell_detected"] = js_shell

        if acq.content_type == "json":
            result_entry["elapsed_s"] = time.perf_counter() - started
            result_entry["ok"] = True
            result_entry["records"] = 0
            result_entry["note"] = "JSON API response, skipping DOM extraction"
            return result_entry

        html = acq.html or ""
        curl_status_code = int((acq.diagnostics or {}).get("curl_status_code") or 0)
        if site.get("skip_on_404") and curl_status_code == 404:
            result_entry["ok"] = True
            result_entry["skipped"] = True
            result_entry["records"] = 0
            result_entry["note"] = "Skipped because the target URL returned HTTP 404 and the listing is volatile"
            result_entry["elapsed_s"] = round(time.perf_counter() - started, 2)
            return result_entry

        # Phase 2: Discover
        parsed_sources = parse_page_sources(html)
        manifest = SimpleNamespace(
            json_ld=parsed_sources.get("json_ld") or [],
            next_data=parsed_sources.get("next_data"),
            _hydrated_states=parsed_sources.get("hydrated_states") or [],
        )
        result_entry["json_ld_count"] = len(manifest.json_ld)
        result_entry["has_next_data"] = bool(manifest.next_data)
        result_entry["hydrated_states"] = len(manifest._hydrated_states)

        # Phase 3: Extract
        if page_type == "category":
            records = extract_listing_records(
                html, surface, set(), page_url=url, max_records=50, xhr_payloads=acq.network_payloads or [],
            )
            result_entry["records"] = len(records)
            result_entry["record_sources"] = list({r.get("_source", "?") for r in records})
            if records:
                sample = records[0]
                result_entry["sample_fields"] = [
                    k for k in sample.keys() if not k.startswith("_")
                ]
                result_entry["sample_title"] = str(sample.get("title", ""))[:80]
                result_entry["sample_url"] = str(sample.get("url", ""))[:120]

            expect_min = site.get("expect_min_records", 0)
            result_entry["ok"] = len(records) >= expect_min
            if not result_entry["ok"]:
                result_entry["issue"] = f"Expected >= {expect_min} records, got {len(records)}"
        else:
            # Detail page
            semantic = extract_semantic_detail_data(html, requested_fields=[])
            candidates, _ = extract_candidates(
                url, surface, html, acq.network_payloads or [], additional_fields=[],
            )
            result_entry["candidate_fields"] = sorted(candidates.keys())
            result_entry["spec_count"] = len(semantic.get("specifications", {}))
            result_entry["section_count"] = len(semantic.get("sections", {}))
            result_entry["has_phantom_specs"] = (
                "specifications" in candidates
                and result_entry["spec_count"] < 2
            )

            expect_fields = site.get("expect_fields", [])
            found = [f for f in expect_fields if f in candidates]
            missing = [f for f in expect_fields if f not in candidates]
            result_entry["found_fields"] = found
            result_entry["missing_fields"] = missing
            result_entry["ok"] = len(missing) == 0
            if missing:
                result_entry["issue"] = f"Missing expected fields: {missing}"

    except Exception as exc:
        result_entry["ok"] = False
        result_entry["error"] = f"{type(exc).__name__}: {exc}"

    result_entry["elapsed_s"] = round(time.perf_counter() - started, 2)
    return result_entry


async def main():
    print(f"Running extraction smoke tests for {len(TEST_SITES)} sites...")
    print("=" * 70)
    results = []
    for i, site in enumerate(TEST_SITES):
        run_id = 9000 + i
        print(f"\n[{i+1}/{len(TEST_SITES)}] {site['name']} ({site['surface']})")
        print(f"  URL: {site['url']}")
        result = await _run_one(site, run_id)
        results.append(result)

        status = "SKIP" if result.get("skipped") else "PASS" if result.get("ok") else "FAIL"
        print(f"  Status: {status}")
        print(f"  Method: {result.get('method', '?')}, HTML: {result.get('html_len', 0):,}")
        if result.get("records") is not None:
            print(f"  Records: {result['records']}, Sources: {result.get('record_sources', [])}")
        if result.get("candidate_fields"):
            print(f"  Fields: {result['candidate_fields'][:15]}")
        if result.get("has_phantom_specs"):
            print(f"  WARNING: Phantom specifications detected (spec_count={result['spec_count']})")
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
        status = "SKIP" if r.get("skipped") else "PASS" if r.get("ok") else "FAIL"
        print(f"  [{status}] {r['name']}")

    # Write report
    report_dir = Path("artifacts/extraction_smoke")
    report_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report_path = report_dir / f"smoke_{ts}.json"
    report_path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"\nReport: {report_path}")

    # Exit with non-zero code if any tests failed
    if passed < total:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
