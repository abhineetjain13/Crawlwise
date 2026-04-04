"""
Site audit script — runs 5 target URLs through the crawl pipeline
and reports extraction results, verdicts, and field coverage.

Usage:
    cd backend
    set PYTHONPATH=.
    python test_sites_audit.py
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import re
import sys
import time
from datetime import UTC, datetime

# Patch SQLAlchemy for Windows event loop
import sqlalchemy.util._concurrency_py3k as _sa_conc
if not hasattr(_sa_conc, "_orig_await_only"):
    _sa_conc._orig_await_only = _sa_conc.await_only
    def _patched_await_only(awaitable):
        try:
            return _sa_conc._orig_await_only(awaitable)
        except Exception:
            import greenlet
            if greenlet.getcurrent().parent is None:
                loop = asyncio.get_event_loop()
                return loop.run_until_complete(awaitable)
            raise
    _sa_conc.await_only = _patched_await_only

from sqlalchemy import select, func, text
from app.core.database import SessionLocal, engine, Base
from app.models.crawl import CrawlRun, CrawlRecord, CrawlLog
from app.services.crawl_service import create_crawl_run, process_run

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("site_audit")

# ── Test sites ──
TEST_SITES = [
    # -- Rich data PDPs with specs/tables --
    {
        "name": "Open Food Facts - Coca Cola (data tables)",
        "url": "https://world.openfoodfacts.org/product/5449000000996/coca-cola-original-taste",
        "surface": "ecommerce_detail",
        "run_type": "crawl",
        "expected_fields": ["title", "brand", "description", "category", "image_url"],
    },
    {
        "name": "Adafruit Product (electronics specs)",
        "url": "https://www.adafruit.com/product/5700",
        "surface": "ecommerce_detail",
        "run_type": "crawl",
        "expected_fields": ["title", "price", "description", "image_url", "sku"],
    },
    {
        "name": "SparkFun Product (electronics specs)",
        "url": "https://www.sparkfun.com/products/19030",
        "surface": "ecommerce_detail",
        "run_type": "crawl",
        "expected_fields": ["title", "price", "description", "image_url", "sku"],
    },
    {
        "name": "REI Osprey Backpack (outdoor gear specs)",
        "url": "https://www.rei.com/product/216223/osprey-atmos-ag-65-pack-mens",
        "surface": "ecommerce_detail",
        "run_type": "crawl",
        "expected_fields": ["title", "price", "brand", "description", "image_url", "rating"],
    },
    {
        "name": "B&H Photo Sony Camera (deep specs)",
        "url": "https://www.bhphotovideo.com/c/product/1730114-REG/sony_ilce_7rm5_b_alpha_a7r_v_mirrorless.html",
        "surface": "ecommerce_detail",
        "run_type": "crawl",
        "expected_fields": ["title", "price", "brand", "description", "image_url", "sku"],
    },
    # -- Listing pages --
    {
        "name": "Allbirds Men's Collection (Shopify listing)",
        "url": "https://www.allbirds.com/collections/mens",
        "surface": "ecommerce_listing",
        "run_type": "crawl",
        "expected_fields": ["title", "price", "url", "image_url"],
    },
    {
        "name": "Gymshark All Products (Shopify listing)",
        "url": "https://www.gymshark.com/collections/all-products",
        "surface": "ecommerce_listing",
        "run_type": "crawl",
        "expected_fields": ["title", "price", "url", "image_url"],
    },
    {
        "name": "Open Food Facts Sodas JSON API",
        "url": "https://world.openfoodfacts.org/category/sodas.json",
        "surface": "ecommerce_listing",
        "run_type": "crawl",
        "expected_fields": ["title", "url", "brand", "category"],
    },
]

CRITICAL_FIELDS = {"price", "availability"}
PLACEHOLDER_VALUES = {"text", "normal", "ymal for pdp", "n/a", "na", "null", "none", "--", ""}
PRODUCT_TITLE_PATTERN = re.compile(r"[A-Za-z].{4,}")
IMAGE_URL_PATTERN = re.compile(r"^https?://", re.IGNORECASE)


async def ensure_test_user(session) -> int:
    """Return a user_id, creating a test user if needed."""
    if not _is_test_environment():
        raise RuntimeError("ensure_test_user may only run in a test environment.")
    from app.models.user import User
    test_email = os.getenv("AUDIT_TEST_EMAIL", "audit@test.local")
    result = await session.execute(select(User).where(User.email == test_email).limit(1))
    user = result.scalar_one_or_none()
    if user:
        return user.id
    # Create a minimal test user
    from app.core.security import hash_password
    test_password = os.getenv("AUDIT_TEST_PASSWORD") or secrets.token_urlsafe(24)
    test_user = User(
        email=test_email,
        hashed_password=hash_password(test_password),
        role="admin",
        is_active=True,
    )
    session.add(test_user)
    await session.commit()
    await session.refresh(test_user)
    return test_user.id


async def run_single_site(site: dict, user_id: int) -> dict:
    """Run pipeline for a single site and return diagnostic report."""
    name = site["name"]
    logger.info(f"\n{'='*70}\nSTARTING: {name}\nURL: {site['url']}\n{'='*70}")

    start = time.time()
    report = {
        "name": name,
        "url": site["url"],
        "surface": site["surface"],
        "status": None,
        "verdict": None,
        "record_count": 0,
        "fields_found": [],
        "fields_missing": [],
        "expected_fields": site["expected_fields"],
        "coverage": 0.0,
        "sample_data": None,
        "validation_errors": [],
        "error": None,
        "elapsed_seconds": 0,
        "acquisition_method": None,
        "logs_summary": [],
    }

    try:
        # Use separate sessions for create vs process to avoid SQLite contention
        async with SessionLocal() as create_session:
            run = await create_crawl_run(create_session, user_id, {
                "run_type": site["run_type"],
                "url": site["url"],
                "surface": site["surface"],
                "settings": {
                    "max_records": 50,
                    "max_pages": 3,
                    "sleep_ms": 500,
                    "advanced_mode": "auto",
                    "llm_enabled": False,
                },
                "additional_fields": site.get("expected_fields", []),
            })
            run_id = run.id
            logger.info(f"Created run {run_id} for {name}")

        async with SessionLocal() as session:
            await process_run(session, run_id)

        # Fetch results in a separate session
        async with SessionLocal() as session:
            run = await session.get(CrawlRun, run_id)
            report["status"] = run.status
            report["record_count"] = (run.result_summary or {}).get("record_count", 0)
            report["result_summary"] = run.result_summary

            result = await session.execute(
                select(CrawlRecord).where(CrawlRecord.run_id == run_id).limit(5)
            )
            records = list(result.scalars().all())

            if records:
                first = records[0]
                report["sample_data"] = _normalize_sample_data(first.data, site["surface"])
                report["acquisition_method"] = (first.source_trace or {}).get("method") or (first.source_trace or {}).get("type")
                all_fields = set()
                for r in records:
                    all_fields.update((r.data or {}).keys())
                report["fields_found"] = sorted(all_fields)
                report["fields_missing"] = [
                    f for f in site["expected_fields"]
                    if f not in all_fields
                ]
                report["coverage"] = _coverage(report["fields_found"], site["expected_fields"])
                report["validation_errors"] = _validate_sample_data(report["sample_data"])

            report["verdict"] = _compute_audit_verdict(report)

            log_result = await session.execute(
                select(CrawlLog)
                .where(CrawlLog.run_id == run_id)
                .order_by(CrawlLog.created_at.asc())
            )
            logs = list(log_result.scalars().all())
            report["logs_summary"] = [
                f"[{log.level.upper()}] {log.message}"
                for log in logs
                if log.level in ("warning", "error") or "[ACQUIRE]" in log.message or "[BLOCKED]" in log.message or "[EXTRACT]" in log.message or "[PUBLISH]" in log.message or "verdict" in log.message.lower()
            ]

    except Exception as exc:
        import traceback
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["status"] = "error"
        logger.error(f"FAILED: {name} -- {exc}")
        traceback.print_exc()

    report["elapsed_seconds"] = round(time.time() - start, 1)
    return report


async def main():
    # Ensure tables exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with SessionLocal() as session:
        user_id = await ensure_test_user(session)

    reports = []
    for site in TEST_SITES:
        report = await run_single_site(site, user_id)
        reports.append(report)
        _print_report(report)

    # Final summary
    print("\n" + "=" * 70)
    print("AUDIT SUMMARY")
    print("=" * 70)
    for r in reports:
        status_icon = "PASS" if r["verdict"] == "success" else "WARN" if r["verdict"] in ("partial", "partial_success") else "FAIL"
        print(f"  [{status_icon}] {r['name']}")
        print(f"       Status: {r['status']} | Verdict: {r['verdict']} | Records: {r['record_count']} | Time: {r['elapsed_seconds']}s")
        if r["fields_found"]:
            print(f"       Fields: {', '.join(r['fields_found'][:15])}")
        if r["fields_missing"]:
            print(f"       Missing: {', '.join(r['fields_missing'])}")
        if r.get("validation_errors"):
            print(f"       Validation: {', '.join(r['validation_errors'])}")
        if r["error"]:
            print(f"       Error: {r['error'][:120]}")
        print()

    # Write full report
    report_path = "audit_report.json"
    with open(report_path, "w") as f:
        json.dump(reports, f, indent=2, default=str)
    print(f"Full report saved to {report_path}")


def _print_report(report: dict):
    print(f"\n{'-'*50}")
    print(f"RESULT: {report['name']}")
    print(f"  URL:      {report['url']}")
    print(f"  Status:   {report['status']}")
    print(f"  Verdict:  {report['verdict']}")
    print(f"  Records:  {report['record_count']}")
    print(f"  Method:   {report['acquisition_method']}")
    print(f"  Time:     {report['elapsed_seconds']}s")
    if report["fields_found"]:
        print(f"  Fields:   {', '.join(report['fields_found'][:20])}")
    if report["fields_missing"]:
        print(f"  Missing:  {', '.join(report['fields_missing'])}")
    if report.get("validation_errors"):
        print(f"  Checks:   {', '.join(report['validation_errors'])}")
    if report.get("sample_data"):
        print(f"  Sample:   {json.dumps(report['sample_data'], indent=4, default=str, ensure_ascii=True)[:500]}")
    if report["error"]:
        print(f"  Error:    {report['error'][:200]}")
    for log_line in report.get("logs_summary", [])[:10]:
        print(f"  Log: {log_line[:120]}")
    print(f"{'-'*50}")


def _is_test_environment() -> bool:
    env = os.getenv("APP_ENV", "development").strip().lower()
    testing = os.getenv("TESTING", "").strip().lower()
    return env in {"test", "testing"} or testing in {"1", "true", "yes"}


def _normalize_sample_data(sample_data: dict | None, surface: str | None = None) -> dict | None:
    if not isinstance(sample_data, dict):
        return None
    normalized = dict(sample_data)
    if "sku" in normalized and normalized["sku"] is not None:
        normalized["sku"] = str(normalized["sku"])
    if surface:
        normalized.setdefault("surface", surface)
        if "listing" in surface:
            normalized.setdefault("is_listing", True)
    return normalized


def _coverage(fields_found: list[str], expected_fields: list[str]) -> float:
    if not expected_fields:
        return 0.0
    matched = {field for field in expected_fields if field in set(fields_found)}
    return round(len(matched) / len(expected_fields), 3)


def _compute_audit_verdict(report: dict) -> str:
    expected_fields = report.get("expected_fields") or []
    fields_missing = report.get("fields_missing") or []
    coverage = float(report.get("coverage") or 0.0)
    validation_errors = report.get("validation_errors") or []

    if validation_errors:
        return "failure"
    if any(field in CRITICAL_FIELDS for field in fields_missing):
        return "failure"
    if not expected_fields:
        return "failure"
    if not fields_missing and coverage >= 0.9:
        return "success"
    if coverage >= 0.5:
        return "partial_success"
    return "failure"


def _validate_sample_data(sample_data: dict | None) -> list[str]:
    if not isinstance(sample_data, dict):
        return ["sample_data_missing"]

    errors: list[str] = []
    title = str(sample_data.get("title") or "").strip()
    surface = str(sample_data.get("surface") or "").strip().lower()
    is_listing = bool(sample_data.get("is_listing")) or surface in {"listing", "tiles", "ecommerce_listing"}
    if not title or title.lower() in PLACEHOLDER_VALUES:
        errors.append("invalid_title")
    elif not is_listing and not PRODUCT_TITLE_PATTERN.search(title):
        errors.append("invalid_title")

    description = str(sample_data.get("description") or "").strip()
    if description and description.lower() in PLACEHOLDER_VALUES:
        errors.append("invalid_description")

    image_url = str(sample_data.get("image_url") or sample_data.get("image") or "").strip()
    if image_url and not IMAGE_URL_PATTERN.match(image_url):
        errors.append("invalid_image_url")

    category = str(sample_data.get("category") or "").strip()
    if category and category.lower() in PLACEHOLDER_VALUES:
        errors.append("invalid_category")

    return errors


if __name__ == "__main__":
    asyncio.run(main())
