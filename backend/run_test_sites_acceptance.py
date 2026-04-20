r"""Run the `TEST_SITES.md` tail through the current production owners."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from harness_support import (
    HARNESS_MODE_ACQUISITION_ONLY,
    HARNESS_MODE_FULL_PIPELINE,
    classify_failure_mode,
    infer_surface,
    parse_test_sites_markdown,
    run_site_harness,
    status_for_result,
    timeout_owner_for_mode,
)

DEFAULT_TEST_SITES_PATH = Path(__file__).resolve().parent.parent / "TEST_SITES.md"
DEFAULT_REPORT_DIR = Path("artifacts/test_sites_acceptance")


async def _run_one(site: dict[str, str], mode: str) -> dict[str, object]:
    started = time.perf_counter()
    result = {
        "name": site["name"],
        "url": site["url"],
        "surface": site["surface"],
        "mode": mode,
        "timeout_owner": timeout_owner_for_mode(mode),
    }
    try:
        result.update(await run_site_harness(url=site["url"], surface=site["surface"], mode=mode))
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    result["elapsed_s"] = round(time.perf_counter() - started, 2)
    result["failure_mode"] = classify_failure_mode(result)
    result["ok"] = result["failure_mode"] == "success"
    return result


def _build_summary(results: list[dict[str, object]]) -> dict[str, object]:
    failure_counts = Counter(str(row.get("failure_mode") or "unknown") for row in results)
    return {
        "ok": sum(1 for row in results if row.get("ok")),
        "failed": sum(1 for row in results if not row.get("ok")),
        "total": len(results),
        "mode": str(results[0].get("mode") or "") if results else "",
        "timeout_owner": str(results[0].get("timeout_owner") or "") if results else "",
        "failure_modes": dict(sorted(failure_counts.items())),
    }


def _write_report(results: list[dict[str, object]], *, start_line: int, source_path: Path, mode: str) -> Path:
    DEFAULT_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = DEFAULT_REPORT_DIR / f"{stamp}__{mode}__test_sites_tail.json"
    path.write_text(
        json.dumps(
            {
                "timestamp_utc": datetime.now(UTC).isoformat(),
                "source_path": str(source_path),
                "start_line": start_line,
                "mode": mode,
                "timeout_owner": timeout_owner_for_mode(mode),
                "summary": _build_summary(results),
                "results": results,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run TEST_SITES.md tail against production harness owners.")
    parser.add_argument("--path", default=str(DEFAULT_TEST_SITES_PATH), help="Path to TEST_SITES.md")
    parser.add_argument("--start-line", type=int, default=198, help="1-based start line")
    parser.add_argument("--limit", type=int, default=None, help="Optional site limit")
    parser.add_argument("--mode", choices=[HARNESS_MODE_FULL_PIPELINE, HARNESS_MODE_ACQUISITION_ONLY], default=HARNESS_MODE_FULL_PIPELINE, help="Run the full persisted pipeline or acquisition-only prefetch path.")
    parser.add_argument("--url", action="append", default=[], help="Explicit URL to smoke-test. Repeat to bypass TEST_SITES.md selection.")
    args = parser.parse_args(argv)

    source_path = Path(args.path)
    explicit_urls = [str(value or "").strip() for value in args.url if str(value or "").strip()]
    sites = ([{"name": url, "url": url, "surface": infer_surface(url)} for url in explicit_urls] if explicit_urls else parse_test_sites_markdown(source_path, start_line=args.start_line))
    if args.limit is not None:
        sites = sites[: args.limit]

    lead = f"Running {len(sites)} explicit TEST_SITES URLs" if explicit_urls else f"Running {len(sites)} TEST_SITES entries from line {args.start_line}"
    print(f"{lead} in mode={args.mode} (timeout_owner={timeout_owner_for_mode(args.mode)})...")
    print("=" * 70)

    results: list[dict[str, object]] = []
    for offset, site in enumerate(sites, start=1):
        print(f"\n[{offset}/{len(sites)}] {site['url']}")
        row = await _run_one(site, args.mode)
        results.append(row)
        print(f"  Status: {status_for_result(row)}")
        print(f"  Mode: {row.get('mode')}  Surface: {row.get('surface')}  Platform: {row.get('platform_family')}")
        print(f"  Verdict: {row.get('verdict')}  Failure mode: {row.get('failure_mode')}")
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
    report_path = _write_report(results, start_line=args.start_line, source_path=source_path, mode=args.mode)
    print(f"Report: {report_path}")
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
