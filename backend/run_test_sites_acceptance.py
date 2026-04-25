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
    DEFAULT_SITE_SET_PATH,
    build_explicit_sites,
    classify_failure_mode,
    evaluate_quality,
    load_site_set,
    parse_test_sites_markdown,
    review_saved_run,
    run_site_harness,
    status_for_result,
    timeout_owner_for_mode,
)

DEFAULT_TEST_SITES_PATH = Path(__file__).resolve().parent.parent / "TEST_SITES.md"
DEFAULT_REPORT_DIR = Path("artifacts/test_sites_acceptance")
_MISSING = object()


async def _run_one(site: dict[str, object], mode: str) -> dict[str, object]:
    started = time.perf_counter()
    result: dict[str, object] = {
        "name": str(site.get("name") or ""),
        "url": str(site.get("url") or ""),
        "surface": str(site.get("surface") or ""),
        "mode": mode,
        "timeout_owner": timeout_owner_for_mode(mode),
        "bucket": site.get("bucket"),
        "gate": site.get("gate"),
        "expected_failure_modes": _object_list(site.get("expected_failure_modes")),
    }
    try:
        artifact_run_id = _safe_int(site.get("artifact_run_id"))
        if bool(site.get("prefer_artifact")) and artifact_run_id:
            result.update(
                await review_saved_run(
                    run_id=artifact_run_id,
                    requested_url=str(site.get("url") or ""),
                )
            )
        else:
            result.update(
                await run_site_harness(
                    url=str(site.get("url") or ""),
                    surface=str(site.get("surface") or ""),
                    mode=mode,
                )
            )
    except Exception as exc:  # pylint: disable=broad-exception-caught
        result["error"] = f"{type(exc).__name__}: {exc}"
    result["elapsed_s"] = round(time.perf_counter() - started, 2)
    result["failure_mode"] = classify_failure_mode(result)
    result.update(evaluate_quality(site, result))
    result["expectation_met"] = _expectation_met(site, result)
    hard_gate = str(site.get("gate") or "").strip().lower() == "hard"
    result["tracked_issue"] = (
        not bool(result["expectation_met"])
        and (
            str(site.get("bucket") or "").strip().lower() not in {"must_pass", "known_blocked"}
            or not hard_gate
        )
    )
    result["ok"] = bool(result["expectation_met"]) or not hard_gate
    return result


def _build_summary(results: list[dict[str, object]]) -> dict[str, object]:
    failure_counts = Counter(str(row.get("failure_mode") or "unknown") for row in results)
    bucket_counts = Counter(str(row.get("bucket") or "unbucketed") for row in results)
    quality_verdict_counts = Counter(str(row.get("quality_verdict") or "unknown") for row in results)
    observed_failure_counts = Counter(str(row.get("observed_failure_mode") or "unknown") for row in results)
    return {
        "ok": sum(1 for row in results if row.get("ok")),
        "failed": sum(1 for row in results if not row.get("ok")),
        "tracked_issues": sum(1 for row in results if row.get("tracked_issue")),
        "total": len(results),
        "mode": str(results[0].get("mode") or "") if results else "",
        "timeout_owner": str(results[0].get("timeout_owner") or "") if results else "",
        "failure_modes": dict(sorted(failure_counts.items())),
        "quality_verdicts": dict(sorted(quality_verdict_counts.items())),
        "observed_failure_modes": dict(sorted(observed_failure_counts.items())),
        "buckets": dict(sorted(bucket_counts.items())),
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


def _expectation_met(site: dict[str, object], result: dict[str, object]) -> bool:
    expected = _object_dict(site.get("expected"))
    if expected:
        return _expected_contract_met(site, result, expected=expected)
    if site.get("quality_expectations"):
        bucket = str(site.get("bucket") or "").strip().lower()
        if bucket == "known_blocked":
            return str(result.get("quality_verdict") or "").strip().lower() == "blocked"
        return str(result.get("quality_verdict") or "").strip().lower() == "good"
    failure_mode = str(result.get("failure_mode") or "").strip().lower()
    bucket = str(site.get("bucket") or "").strip().lower()
    expected_failure_modes = {
        str(value or "").strip().lower()
        for value in _object_list(site.get("expected_failure_modes"))
        if str(value or "").strip()
    }
    if expected_failure_modes:
        return failure_mode in expected_failure_modes
    if bucket == "must_pass":
        return failure_mode == "success"
    if bucket == "known_blocked":
        return failure_mode == "blocked"
    return failure_mode == "success"


def _expected_contract_met(
    site: dict[str, object],
    result: dict[str, object],
    *,
    expected: dict[str, object],
) -> bool:
    record_count = _safe_int(result.get("records"))
    if record_count < _safe_int(expected.get("min_record_count")):
        return False
    sample_record = _object_dict(result.get("sample_record_data"))
    for field_name in _object_list(expected.get("fields_must_be_present")):
        if _nested_value(sample_record, str(field_name)) is _MISSING:
            return False
    for field_name in _object_list(expected.get("fields_must_not_be_null")):
        if _nested_value(sample_record, str(field_name)) in (None, "", [], {}):
            return False
    min_variant_count = _safe_int(expected.get("min_variant_count"))
    if min_variant_count > 0:
        variant_count = _safe_int(_object_dict(result.get("sample_semantics")).get("variant_count"))
        if variant_count < min_variant_count:
            return False
    if bool(expected.get("price_must_be_numeric")):
        listing_contract = _object_dict(result.get("listing_contract"))
        surface = str((site.get("surface") or result.get("surface") or "")).strip().lower()
        if surface.endswith("_listing"):
            if _safe_int(listing_contract.get("price_numeric_count")) <= 0:
                return False
        else:
            price_value = _nested_value(sample_record, "price")
            if price_value in (None, "", [], {}):
                price_value = _nested_value(sample_record, "selected_variant.price")
            if not _looks_numeric_price(price_value):
                return False
    if bool(expected.get("detail_urls_must_be_present")):
        if not bool(_object_dict(result.get("listing_contract")).get("detail_urls_present")):
            return False
    return True


def _nested_value(payload: dict[str, object], dotted_key: str) -> object:
    current: object = payload
    for segment in [part for part in str(dotted_key or "").split(".") if part]:
        if not isinstance(current, dict):
            return _MISSING
        if segment not in current:
            return _MISSING
        current = current.get(segment)
    return current


def _looks_numeric_price(value: object) -> bool:
    text = str(value or "").strip().replace(",", "")
    if not text:
        return False
    try:
        float(text)
    except ValueError:
        return False
    return True


def _console_safe(value: object) -> str:
    text = str(value or "")
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    return text.encode(encoding, errors="replace").decode(encoding, errors="replace")


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run TEST_SITES.md tail against production harness owners.")
    parser.add_argument("--path", default=str(DEFAULT_TEST_SITES_PATH), help="Path to TEST_SITES.md")
    parser.add_argument("--start-line", type=int, default=198, help="1-based start line")
    parser.add_argument("--limit", type=int, default=None, help="Optional site limit")
    parser.add_argument("--mode", choices=[HARNESS_MODE_FULL_PIPELINE, HARNESS_MODE_ACQUISITION_ONLY], default=HARNESS_MODE_FULL_PIPELINE, help="Run the full persisted pipeline or acquisition-only prefetch path.")
    parser.add_argument("--url", action="append", default=[], help="Explicit URL to smoke-test. Repeat to bypass TEST_SITES.md selection.")
    parser.add_argument("--surface", action="append", default=[], help="Explicit surface paired by position with each --url.")
    parser.add_argument("--site-set", default="", help="Curated site set name to load from the site-set manifest.")
    parser.add_argument("--site-set-path", default=str(DEFAULT_SITE_SET_PATH), help="Path to curated site-set manifest JSON.")
    parser.add_argument("--prefer-artifacts", action="store_true", help="Reuse artifact-backed run_ids from the curated site-set when present.")
    args = parser.parse_args(argv)

    source_path = Path(args.path)
    explicit_urls = [str(value or "").strip() for value in args.url if str(value or "").strip()]
    explicit_surfaces = [str(value or "").strip() for value in args.surface if str(value or "").strip()]
    if explicit_urls:
        sites: list[dict[str, object]] = [
            _as_object_row(site)
            for site in build_explicit_sites(explicit_urls, explicit_surfaces=explicit_surfaces)
        ]
    elif str(args.site_set or "").strip():
        sites = load_site_set(Path(args.site_set_path), site_set_name=str(args.site_set).strip())
    else:
        sites = [
            _as_object_row(site)
            for site in parse_test_sites_markdown(source_path, start_line=args.start_line)
        ]
    if args.prefer_artifacts:
        sites = [{**site, "prefer_artifact": True} for site in sites]
    if args.limit is not None:
        sites = sites[: args.limit]

    if explicit_urls:
        lead = f"Running {len(sites)} explicit TEST_SITES URLs"
    elif str(args.site_set or "").strip():
        lead = f"Running {len(sites)} curated site-set entries from {args.site_set}"
    else:
        lead = f"Running {len(sites)} TEST_SITES entries from line {args.start_line}"
    print(f"{lead} in mode={args.mode} (timeout_owner={timeout_owner_for_mode(args.mode)})...")
    print("=" * 70)

    results: list[dict[str, object]] = []
    for offset, site in enumerate(sites, start=1):
        print(f"\n[{offset}/{len(sites)}] {site['url']}")
        row = await _run_one(site, args.mode)
        results.append(row)
        print(f"  Status: {status_for_result(row)}")
        print(f"  Mode: {row.get('mode')}  Surface: {row.get('surface')}  Platform: {row.get('platform_family')}  Bucket: {row.get('bucket')}")
        print(f"  Verdict: {row.get('verdict')}  Failure mode: {row.get('failure_mode')}")
        print(f"  Quality: {row.get('quality_verdict')}  Observed: {row.get('observed_failure_mode')}  Source: {row.get('run_source')}")
        if row.get("records") is not None:
            print(f"  Records: {row.get('records')}")
        if row.get("sample_title"):
            print(f"  Sample: {_console_safe(row['sample_title'])}")
        if row.get("sample_url"):
            print(f"  Sample URL: {_console_safe(row['sample_url'])}")
        if row.get("sample_utility_noise_hits"):
            print(f"  Audit utility hits: {row['sample_utility_noise_hits']}")
        if isinstance(row.get("challenge_summary"), dict):
            challenge_summary = _object_dict(row.get("challenge_summary"))
            provider = str(challenge_summary.get("provider") or "").strip()
            evidence = _object_list(challenge_summary.get("evidence"))
            provider_text = provider or "unknown"
            print(f"  Challenge: provider={provider_text}")
            if evidence:
                print(f"  Challenge evidence: {', '.join(str(item) for item in evidence[:3])}")
        failed_quality_checks = [
            name
            for name, value in _object_dict(row.get("quality_checks")).items()
            if not bool(value)
        ]
        if failed_quality_checks:
            print(f"  Failed quality checks: {', '.join(failed_quality_checks)}")
        if row.get("error"):
            print(f"  Error: {row['error']}")
        print(f"  Elapsed: {row.get('elapsed_s')}s")

    summary = _build_summary(results)
    print("\n" + "=" * 70)
    print(json.dumps(summary, indent=2))
    report_path = _write_report(results, start_line=args.start_line, source_path=source_path, mode=args.mode)
    print(f"Report: {report_path}")
    return 0 if summary["failed"] == 0 else 1


def _safe_int(value: object) -> int:
    try:
        return 0 if value in (None, "") else int(str(value))
    except (TypeError, ValueError):
        return 0


def _object_dict(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def _object_list(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


def _as_object_row(row: dict[str, str]) -> dict[str, object]:
    return {key: value for key, value in row.items()}


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
