r"""
Run the `TEST_SITES.md` tail through the current architecture and classify failures.

Usage:
    cd backend
    set PYTHONPATH=.
    .venv\Scripts\python.exe run_test_sites_acceptance.py
    .venv\Scripts\python.exe run_test_sites_acceptance.py --start-line 198 --limit 5
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from app.services.acquisition import (
    AcquisitionRequest,
    acquire,
)
from app.services.acquisition.runtime import is_blocked_html
from app.services.acquisition_plan import AcquisitionPlan
from app.services.adapters.registry import run_adapter
from app.services.extraction_runtime import extract_records
from app.services.platform_policy import detect_platform_family

from harness_support import classify_failure_mode, infer_surface, parse_test_sites_markdown

DEFAULT_TEST_SITES_PATH = Path(__file__).resolve().parent.parent / "TEST_SITES.md"
DEFAULT_REPORT_DIR = Path("artifacts/test_sites_acceptance")


async def _run_one(site: dict[str, str], run_id: int, timeout_seconds: int) -> dict[str, object]:
    url = site["url"]
    surface = site["surface"]
    started = time.perf_counter()
    result: dict[str, object] = {
        "name": site["name"],
        "url": url,
        "surface": surface,
    }
    try:
        acquisition = await asyncio.wait_for(
            acquire(
                AcquisitionRequest(
                    run_id=run_id,
                    url=url,
                    plan=AcquisitionPlan(
                        surface=surface,
                        max_pages=5,
                        max_scrolls=5,
                    ),
                )
            ),
            timeout=timeout_seconds,
        )
        blocked = (
            is_blocked_html(acquisition.html or "", acquisition.status_code)
            if acquisition.content_type.startswith("text/html")
            else False
        )
        adapter_result = None
        if acquisition.content_type.startswith("text/html"):
            adapter_result = await run_adapter(url, acquisition.html or "", surface)
        records = extract_records(
            acquisition.html or "",
            url,
            surface,
            max_records=50,
            adapter_records=list(adapter_result.records or []) if adapter_result else None,
            network_payloads=acquisition.network_payloads or [],
        )
        result.update(
            {
                "ok": bool(records),
                "platform_family": detect_platform_family(url, acquisition.html or ""),
                "method": acquisition.method,
                "status_code": acquisition.status_code,
                "content_type": acquisition.content_type,
                "blocked": blocked,
                "html_len": len(acquisition.html or ""),
                "network_payloads": len(acquisition.network_payloads or []),
                "browser_diagnostics": dict(acquisition.browser_diagnostics or {}),
                "adapter_name": adapter_result.adapter_name if adapter_result else None,
                "adapter_records": (
                    len(adapter_result.records or []) if adapter_result else 0
                ),
                "records": len(records),
                "sample_title": str(records[0].get("title") or "")[:120] if records else "",
            }
        )
    except Exception as exc:
        result["ok"] = False
        result["platform_family"] = detect_platform_family(url)
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        result["elapsed_s"] = round(time.perf_counter() - started, 2)
    result["failure_mode"] = classify_failure_mode(result)
    return result


def _build_summary(results: list[dict[str, object]]) -> dict[str, object]:
    failure_counts = Counter(str(row.get("failure_mode") or "unknown") for row in results)
    return {
        "ok": sum(1 for row in results if row.get("ok")),
        "failed": sum(1 for row in results if not row.get("ok")),
        "total": len(results),
        "failure_modes": dict(sorted(failure_counts.items())),
    }


def _write_report(results: list[dict[str, object]], *, start_line: int, source_path: Path) -> Path:
    DEFAULT_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = DEFAULT_REPORT_DIR / f"{stamp}__test_sites_tail.json"
    payload = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "source_path": str(source_path),
        "start_line": start_line,
        "summary": _build_summary(results),
        "results": results,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Run TEST_SITES.md tail against the current acquisition/extraction stack."
    )
    parser.add_argument("--path", default=str(DEFAULT_TEST_SITES_PATH), help="Path to TEST_SITES.md")
    parser.add_argument("--start-line", type=int, default=198, help="1-based start line")
    parser.add_argument("--limit", type=int, default=None, help="Optional site limit")
    parser.add_argument("--timeout", type=int, default=90, help="Per-site timeout in seconds")
    parser.add_argument(
        "--url",
        action="append",
        default=[],
        help="Explicit URL to smoke-test. Repeat to bypass TEST_SITES.md selection.",
    )
    args = parser.parse_args(argv)

    source_path = Path(args.path)
    explicit_urls = [str(value or "").strip() for value in args.url if str(value or "").strip()]
    if explicit_urls:
        sites = [
            {"name": url, "url": url, "surface": infer_surface(url)}
            for url in explicit_urls
        ]
    else:
        sites = parse_test_sites_markdown(source_path, start_line=args.start_line)
    if args.limit is not None:
        sites = sites[: args.limit]

    if explicit_urls:
        print(f"Running {len(sites)} explicit TEST_SITES URLs...")
    else:
        print(f"Running {len(sites)} TEST_SITES entries from line {args.start_line}...")
    print("=" * 70)

    results: list[dict[str, object]] = []
    for offset, site in enumerate(sites, start=1):
        print(f"\n[{offset}/{len(sites)}] {site['url']}")
        row = await _run_one(site, 70000 + offset - 1, args.timeout)
        results.append(row)
        status = "PASS" if row.get("ok") else "FAIL"
        print(f"  Status: {status}")
        print(f"  Surface: {row.get('surface')}  Platform: {row.get('platform_family')}")
        print(f"  Failure mode: {row.get('failure_mode')}")
        if row.get("adapter_name"):
            print(f"  Adapter: {row['adapter_name']} ({row.get('adapter_records', 0)} records)")
        if row.get("records") is not None:
            print(f"  Records: {row.get('records')}")
        if row.get("sample_title"):
            print(f"  Sample: {row['sample_title']}")
        if row.get("error"):
            print(f"  Error: {row['error']}")
        print(f"  Elapsed: {row.get('elapsed_s')}s")

    summary = _build_summary(results)
    print("\n" + "=" * 70)
    print(json.dumps(summary, indent=2))
    report_path = _write_report(results, start_line=args.start_line, source_path=source_path)
    print(f"Report: {report_path}")
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
