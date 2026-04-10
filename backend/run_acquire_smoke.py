"""
Small acquire-only smoke runner for representative TEST_SITES batches.

Usage:
    cd backend
    set PYTHONPATH=.
    python run_acquire_smoke.py
    python run_acquire_smoke.py api commerce jobs
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import settings
from app.services.acquisition.acquirer import acquire
from app.services.acquisition.blocked_detector import detect_blocked_page

BATCHES: dict[str, list[tuple[str, str]]] = {
    "api": [
        ("Allbirds products.json", "https://www.allbirds.com/products.json"),
        ("OpenFoodFacts sodas.json", "https://world.openfoodfacts.org/category/sodas.json"),
        ("Remotive API", "https://remotive.com/api/remote-jobs"),
        ("RemoteOK API", "https://remoteok.com/api"),
    ],
    "commerce": [
        ("Allbirds PDP", "https://www.allbirds.com/products/mens-wool-runners"),
        ("Allbirds listing", "https://www.allbirds.com/collections/mens"),
        ("Gymshark listing", "https://www.gymshark.com/collections/all-products"),
        ("Puma mens listing", "https://us.puma.com/us/en/men/shop-all-mens"),
        ("Converse mens listing", "https://www.converse.com/shop/mens-shoes"),
        ("UnderArmour mens listing", "https://www.underarmour.com/en-us/c/mens/"),
    ],
    "jobs": [
        ("Greenhouse board", "https://boards.greenhouse.io/embed/job_board?for=stripe"),
        ("Lever board", "https://jobs.lever.co/reddit"),
        ("Remotive jobs page", "https://remotive.com/remote-jobs"),
        ("RemoteOK jobs page", "https://remoteok.com/remote-dev-jobs"),
        ("Himalayas detail", "https://himalayas.app/jobs/product-designer/runway"),
    ],
    "hard": [
        ("Footlocker mens shoes", "https://www.footlocker.com/category/mens/shoes.html"),
        ("John Lewis electricals", "https://www.johnlewis.com/browse/electricals/c6000014"),
        ("Nike mens shoes", "https://www.nike.com/w/mens-shoes-nik1zy7ok"),
        ("Dyson air treatment", "https://www.dyson.in/air-treatment"),
    ],
    "ats": [
        ("Greenhouse Doordash", "https://boards.greenhouse.io/embed/job_board?for=doordash"),
        ("Greenhouse Notion", "https://boards.greenhouse.io/embed/job_board?for=notion"),
        ("Lever Figma", "https://jobs.lever.co/figma"),
        ("Lever Linear", "https://jobs.lever.co/linear"),
    ],
    "specialist": [
        ("Adafruit PDP", "https://www.adafruit.com/product/5700"),
        ("SparkFun PDP", "https://www.sparkfun.com/products/19030"),
        ("McMaster listing", "https://www.mcmaster.com/pipe-fittings/high-pressure-stainless-steel-threaded-pipe-fittings/"),
        ("B&H Sony PDP", "https://www.bhphotovideo.com/c/product/1730114-REG/sony_ilce_7rm5_b_alpha_a7r_v_mirrorless.html"),
    ],
}


async def _run_one(run_id: int, name: str, url: str, timeout_seconds: int) -> dict:
    started = time.perf_counter()
    try:
        result = await asyncio.wait_for(acquire(run_id, url), timeout=timeout_seconds)
        blocked = detect_blocked_page(result.html or "").as_dict() if result.content_type == "html" else None
        return {
            "name": name,
            "url": url,
            "ok": True,
            "method": result.method,
            "content_type": result.content_type,
            "html_len": len(result.html or ""),
            "json_kind": type(result.json_data).__name__ if result.json_data is not None else None,
            "network_payloads": len(result.network_payloads or []),
            "blocked": blocked,
            "artifact_path": result.artifact_path,
            "diagnostics_path": result.diagnostics_path,
            "seconds": round(time.perf_counter() - started, 2),
        }
    except Exception as exc:
        return {
            "name": name,
            "url": url,
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "seconds": round(time.perf_counter() - started, 2),
        }


async def _run_batch(batch_name: str, timeout_seconds: int, *, start_run_id: int) -> list[dict]:
    results: list[dict] = []
    for offset, (name, url) in enumerate(BATCHES[batch_name], start=1):
        results.append(await _run_one(start_run_id + offset - 1, name, url, timeout_seconds))
    return results


def _report_dir() -> Path:
    return settings.artifacts_dir / "acquisition_smoke"


def _build_summary(overall: dict[str, list[dict]]) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = {}
    for batch_name, rows in overall.items():
        ok = sum(1 for row in rows if row.get("ok"))
        summary[batch_name] = {"ok": ok, "failed": len(rows) - ok, "total": len(rows)}
    return summary


def _write_report(overall: dict[str, list[dict]], selected: list[str], timeout_seconds: int) -> Path:
    report_dir = _report_dir()
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    batch_slug = "-".join(selected)
    path = report_dir / f"{stamp}__{batch_slug}.json"
    payload = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "timeout_seconds": timeout_seconds,
        "batches": selected,
        "summary": _build_summary(overall),
        "results": overall,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run small acquire-only smoke batches.")
    parser.add_argument("batches", nargs="*", choices=sorted(BATCHES), help="Batch names to run")
    parser.add_argument("--timeout", type=int, default=75, help="Per-site timeout in seconds")
    args = parser.parse_args(argv)

    selected = args.batches or ["api", "commerce"]
    overall: dict[str, list[dict]] = {}
    run_id_base = 40000
    for batch_name in selected:
        overall[batch_name] = await _run_batch(batch_name, args.timeout, start_run_id=run_id_base)
        run_id_base += len(BATCHES[batch_name])

    report_path = _write_report(overall, selected, args.timeout)
    print(json.dumps({"summary": _build_summary(overall), "report_path": str(report_path), "results": overall}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
