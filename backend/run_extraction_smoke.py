r"""
Acceptance corpus runner for acquisition + extraction verification.

Usage:
    cd backend
    set PYTHONPATH=.
    .venv\Scripts\python.exe run_extraction_smoke.py
    .venv\Scripts\python.exe run_extraction_smoke.py --groups controls --limit 2
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from app.services.acquisition import (
    AcquisitionRequest,
    acquire,
    detect_blocked_page,
)
from app.services.adapters.registry import run_adapter
from app.services.crawl_engine import extract_records
from app.services.platform_policy import detect_platform_family

from harness_support import infer_surface

DEFAULT_CORPUS_PATH = (
    Path(__file__).resolve().parent / "corpora" / "acceptance_corpus.json"
)
DEFAULT_REPORT_DIR = Path("artifacts/extraction_smoke")


def _value_present(value: object) -> bool:
    return value not in (None, "", [], {})


def _listing_field_coverage(
    records: list[dict],
    required_fields: list[str],
    *,
    sample_limit: int,
) -> dict[str, float]:
    if not required_fields:
        return {}
    sample = records[:sample_limit]
    if not sample:
        return {field: 0.0 for field in required_fields}
    return {
        field: round(
            sum(1 for record in sample if _value_present(record.get(field))) / len(sample),
            3,
        )
        for field in required_fields
    }


def _load_corpus(path: Path) -> dict[str, list[dict]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    groups = payload.get("groups")
    if isinstance(groups, dict):
        return {
            str(group_name): [dict(site) for site in sites if isinstance(site, dict)]
            for group_name, sites in groups.items()
            if isinstance(sites, list)
        }
    return {
        str(group_name): [dict(site) for site in sites if isinstance(site, dict)]
        for group_name, sites in payload.items()
        if isinstance(sites, list)
    }


def _select_sites(
    corpus: dict[str, list[dict]],
    selected_groups: list[str],
    limit: int | None,
) -> list[dict]:
    selected: list[dict] = []
    for group_name in selected_groups:
        for site in corpus.get(group_name, []):
            selected.append({**site, "_group": group_name})
    return selected[:limit] if limit is not None else selected


def _report_dir() -> Path:
    return DEFAULT_REPORT_DIR


def _coerce_max_elapsed_s(site: dict) -> float | None:
    raw_value = site.get("max_elapsed_s")
    if raw_value in (None, ""):
        return None
    try:
        value = float(str(raw_value))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _apply_elapsed_assertion(result: dict[str, object], site: dict) -> None:
    max_elapsed_s = _coerce_max_elapsed_s(site)
    if max_elapsed_s is None:
        return
    result["max_elapsed_s"] = max_elapsed_s
    elapsed_s = float(str(result.get("elapsed_s") or 0.0))
    if elapsed_s <= max_elapsed_s:
        return
    result["ok"] = False
    runtime_issue = (
        f"Elapsed {elapsed_s:.2f}s exceeded max_elapsed_s={max_elapsed_s:.2f}s"
    )
    if result.get("issue"):
        result["issue"] = f"{result['issue']}; {runtime_issue}"
    elif not result.get("error"):
        result["issue"] = runtime_issue


def _build_summary(results: list[dict]) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = {}
    for row in results:
        group_name = str(row.get("group") or "default")
        bucket = summary.setdefault(group_name, {"ok": 0, "failed": 0, "total": 0})
        bucket["total"] += 1
        if row.get("ok"):
            bucket["ok"] += 1
        else:
            bucket["failed"] += 1
    return summary


def _write_report(
    results: list[dict],
    *,
    corpus_path: Path,
    selected_groups: list[str],
    timeout_seconds: int,
) -> Path:
    report_dir = _report_dir()
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = report_dir / f"{stamp}__{'-'.join(selected_groups)}.json"
    payload = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "corpus_path": str(corpus_path),
        "groups": selected_groups,
        "timeout_seconds": timeout_seconds,
        "summary": _build_summary(results),
        "results": results,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


async def _run_one(site: dict, run_id: int, timeout_seconds: int) -> dict:
    name = str(site.get("name") or "").strip()
    url = str(site.get("url") or "").strip()
    surface = infer_surface(url, explicit_surface=site.get("surface"))
    page_type = str(site.get("page_type") or "").strip().lower()
    started = time.perf_counter()
    result: dict[str, object] = {
        "group": site.get("_group"),
        "name": name,
        "url": url,
        "surface": surface,
        "page_type": page_type,
        "baseline_reason": site.get("baseline_reason"),
        "baseline_artifact": site.get("baseline_artifact"),
    }

    try:
        acquisition = await asyncio.wait_for(
            acquire(
                AcquisitionRequest(
                    run_id=run_id,
                    url=url,
                    surface=surface,
                    traversal_mode=str(site.get("traversal_mode") or "").strip() or None,
                    max_pages=5,
                    max_scrolls=5,
                    sleep_ms=0,
                    requested_fields=list(site.get("expect_fields") or []),
                )
            ),
            timeout=timeout_seconds,
        )
        blocked = (
            detect_blocked_page(acquisition.html or "", acquisition.status_code)
            if acquisition.content_type.startswith("text/html")
            else False
        )
        adapter_result = None
        if acquisition.content_type.startswith("text/html"):
            adapter_result = await run_adapter(url, acquisition.html or "", surface)

        result.update(
            {
                "method": acquisition.method,
                "status_code": acquisition.status_code,
                "content_type": acquisition.content_type,
                "platform_family": detect_platform_family(url, acquisition.html or ""),
                "html_len": len(acquisition.html or ""),
                "network_payloads": len(acquisition.network_payloads or []),
                "blocked": blocked,
                "adapter_name": adapter_result.adapter_name if adapter_result else None,
                "adapter_records": len(adapter_result.records) if adapter_result else 0,
                "browser_diagnostics": dict(acquisition.browser_diagnostics or {}),
            }
        )

        if acquisition.content_type.startswith("application/json"):
            result["ok"] = True
            result["note"] = "JSON response; extraction corpus checks skipped"
            return result

        records = extract_records(
            acquisition.html or "",
            url,
            surface,
            max_records=int(site.get("max_records") or 50),
            requested_fields=[str(field) for field in site.get("expect_fields") or []] or None,
            adapter_records=list(adapter_result.records or []) if adapter_result else None,
            network_payloads=acquisition.network_payloads or [],
            selector_rules=None,
        )

        if "listing" in surface:
            required_fields = [str(field) for field in site.get("required_record_fields") or []]
            coverage = _listing_field_coverage(
                records,
                required_fields,
                sample_limit=int(site.get("sample_limit") or 10),
            )
            thresholds = {
                str(field): float(threshold)
                for field, threshold in (site.get("required_record_field_coverage") or {}).items()
            }
            failing_fields = [
                field
                for field, threshold in thresholds.items()
                if coverage.get(field, 0.0) < threshold
            ]
            result.update(
                {
                    "records": len(records),
                    "required_record_fields": required_fields,
                    "required_record_field_coverage": coverage,
                    "sample_fields": (
                        [key for key in records[0] if not str(key).startswith("_")]
                        if records
                        else []
                    ),
                    "sample_title": (
                        str(records[0].get("title") or "")[:120] if records else ""
                    ),
                }
            )
            min_records = int(site.get("expect_min_records") or 0)
            result["ok"] = len(records) >= min_records and not failing_fields
            if len(records) < min_records:
                result["issue"] = f"Expected >= {min_records} records, got {len(records)}"
            elif failing_fields:
                result["issue"] = f"Coverage below threshold for: {sorted(failing_fields)}"
        else:
            expected_fields = [str(field) for field in site.get("expect_fields") or []]
            found_fields = [
                field
                for field in expected_fields
                if records and field in records[0] and _value_present(records[0].get(field))
            ]
            missing_fields = [field for field in expected_fields if field not in found_fields]
            result.update(
                {
                    "candidate_fields": sorted(records[0].keys()) if records else [],
                    "found_fields": found_fields,
                    "missing_fields": missing_fields,
                }
            )
            result["ok"] = not missing_fields
            if missing_fields:
                result["issue"] = f"Missing expected fields: {missing_fields}"
    except Exception as exc:
        result["ok"] = False
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        result["elapsed_s"] = round(time.perf_counter() - started, 2)
        _apply_elapsed_assertion(result, site)

    return result


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Run the acceptance corpus against the current acquisition/extraction facades."
    )
    parser.add_argument(
        "--corpus",
        default=str(DEFAULT_CORPUS_PATH),
        help="Path to the acceptance corpus JSON manifest.",
    )
    parser.add_argument(
        "--groups",
        nargs="*",
        help="Corpus groups to run. Defaults to all groups in manifest order.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional global limit after group selection.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=90,
        help="Per-site timeout in seconds.",
    )
    args = parser.parse_args(argv)

    corpus_path = Path(args.corpus)
    corpus = _load_corpus(corpus_path)
    selected_groups = args.groups or list(corpus)
    sites = _select_sites(corpus, selected_groups, args.limit)
    print(f"Running acceptance corpus for {len(sites)} sites...")
    print("=" * 70)

    results: list[dict] = []
    for offset, site in enumerate(sites, start=1):
        run_id = 50000 + offset - 1
        print(
            f"\n[{offset}/{len(sites)}] {site.get('name')} "
            f"[{site.get('_group')}]"
        )
        print(f"  URL: {site.get('url')}")
        result = await _run_one(site, run_id, args.timeout)
        results.append(result)

        status = "PASS" if result.get("ok") else "FAIL"
        print(f"  Status: {status}")
        print(
            f"  Method: {result.get('method', '?')}, "
            f"Platform: {result.get('platform_family', '?')}"
        )
        if result.get("records") is not None:
            print(f"  Records: {result.get('records')}")
        if result.get("found_fields") is not None:
            print(f"  Found: {result.get('found_fields', [])}")
        if result.get("required_record_field_coverage"):
            print(f"  Coverage: {result['required_record_field_coverage']}")
        if result.get("issue"):
            print(f"  Issue: {result['issue']}")
        if result.get("error"):
            print(f"  Error: {result['error']}")
        print(f"  Elapsed: {result.get('elapsed_s', 0)}s")

    summary = _build_summary(results)
    print("\n" + "=" * 70)
    print(json.dumps({"summary": summary}, indent=2))
    report_path = _write_report(
        results,
        corpus_path=corpus_path,
        selected_groups=selected_groups,
        timeout_seconds=args.timeout,
    )
    print(f"Report: {report_path}")
    return 0 if all(row.get("ok") for row in results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
