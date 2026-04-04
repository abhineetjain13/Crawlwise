"""
Quick pipeline audit — runs reachable TEST_SITES through the crawl pipeline.

Usage:
    cd backend
    set PYTHONPATH=.
    python run_audit.py
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import secrets
import sys
import time
from datetime import UTC, datetime

from sqlalchemy import inspect, select
from sqlalchemy.exc import MissingGreenlet

# SQLAlchemy 2.x on Windows can raise MissingGreenlet when async helpers are
# called from this standalone script outside the usual greenlet bridge. This
# patch is intentionally narrow, touches a private symbol, and should fail safe
# if SQLAlchemy changes its internal concurrency module shape in the future.
import sqlalchemy.util._concurrency_py3k as _sa_conc
if not hasattr(_sa_conc, "await_only"):
    logging.getLogger("audit").warning("SQLAlchemy await_only symbol missing; audit concurrency patch skipped")
elif not hasattr(_sa_conc, "_orig_await_only"):
    _sa_conc._orig_await_only = _sa_conc.await_only

    def _patched_await_only(awaitable):
        try:
            return _sa_conc._orig_await_only(awaitable)
        except MissingGreenlet:
            import greenlet

            if greenlet.getcurrent().parent is not None:
                raise
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                try:
                    return loop.run_until_complete(awaitable)
                finally:
                    loop.close()
            raise

    _sa_conc.await_only = _patched_await_only

from app.core.database import SessionLocal, engine, Base
from app.models.crawl import CrawlRun, CrawlRecord, CrawlLog
from app.services.crawl_service import create_crawl_run, process_run

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("audit")
_AUDIT_TEST_EMAIL = "audit@test.local"

TEST_SITES = [
    # JSON API — easiest, should always work
    {
        "name": "Allbirds products.json (Shopify JSON)",
        "url": "https://www.allbirds.com/products.json",
        "surface": "ecommerce_listing",
        "run_type": "crawl",
        "expected_fields": ["title", "price", "url", "image_url"],
    },
    {
        "name": "Remotive API (JSON jobs)",
        "url": "https://remotive.com/api/remote-jobs",
        "surface": "job_listing",
        "run_type": "crawl",
        "expected_fields": ["title", "company_name", "url", "category"],
    },
    # Shopify HTML
    {
        "name": "Allbirds Wool Runners (Shopify PDP)",
        "url": "https://www.allbirds.com/products/mens-wool-runners",
        "surface": "ecommerce_detail",
        "run_type": "crawl",
        "expected_fields": ["title", "price", "description", "image_url"],
    },
    {
        "name": "Allbirds Mens Collection (Shopify listing)",
        "url": "https://www.allbirds.com/collections/mens",
        "surface": "ecommerce_listing",
        "run_type": "crawl",
        "expected_fields": ["title", "price", "url", "image_url"],
    },
    # Medium difficulty
    {
        "name": "Converse Mens Shoes (listing)",
        "url": "https://www.converse.com/shop/mens-shoes",
        "surface": "ecommerce_listing",
        "run_type": "crawl",
        "expected_fields": ["title", "price", "url", "image_url"],
    },
    {
        "name": "Puma Mens (listing)",
        "url": "https://us.puma.com/us/en/men/shop-all-mens",
        "surface": "ecommerce_listing",
        "run_type": "crawl",
        "expected_fields": ["title", "price", "url", "image_url"],
    },
    # Job detail
    {
        "name": "Himalayas job detail",
        "url": "https://himalayas.app/jobs/product-designer/runway",
        "surface": "job_detail",
        "run_type": "crawl",
        "expected_fields": ["title", "company_name", "description"],
    },
    # Hard — Amazon
    {
        "name": "Amazon India shoes search (listing)",
        "url": "https://www.amazon.in/s?k=shoes",
        "surface": "ecommerce_listing",
        "run_type": "crawl",
        "expected_fields": ["title", "price", "url", "image_url"],
    },
]


def _is_truthy_env(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _ensure_audit_allowed() -> None:
    if _is_truthy_env(os.getenv("AUDIT_ALLOW_PROD")):
        return
    app_env = str(os.getenv("APP_ENV") or os.getenv("ENV") or "development").strip().lower()
    if app_env == "production":
        raise RuntimeError("Refusing to run audit in production without AUDIT_ALLOW_PROD=1")


async def _prepare_schema(*, create_tables: bool) -> None:
    async with engine.begin() as conn:
        if create_tables:
            await conn.run_sync(Base.metadata.create_all)
            return
        missing_tables = await conn.run_sync(
            lambda sync_conn: sorted(
                {
                    "users",
                    "crawl_runs",
                    "crawl_records",
                    "crawl_logs",
                }
                - {
                    table_name
                    for table_name in inspect(sync_conn).get_table_names()
                }
            )
        )
    if missing_tables:
        raise RuntimeError(
            "Audit requires migrated tables. Missing tables: "
            + ", ".join(missing_tables)
            + ". Run migrations first or pass --create-tables for an opt-in bootstrap."
        )


async def ensure_test_user(session) -> tuple[int, bool]:
    from app.models.user import User
    result = await session.execute(select(User).where(User.email == _AUDIT_TEST_EMAIL).limit(1))
    user = result.scalar_one_or_none()
    if user:
        return user.id, False
    from app.core.security import hash_password
    test_user = User(
        email=_AUDIT_TEST_EMAIL,
        hashed_password=hash_password(secrets.token_urlsafe(24)),
        role="audit",
        is_active=True,
    )
    session.add(test_user)
    await session.commit()
    await session.refresh(test_user)
    return test_user.id, True


async def cleanup_test_user(session, user_id: int, *, created: bool) -> None:
    if not created:
        return
    from app.models.user import User
    user = await session.get(User, user_id)
    if user is None:
        return
    await session.delete(user)
    await session.commit()


async def run_site(site: dict, user_id: int) -> dict:
    name = site["name"]
    logger.info(f"\n{'='*60}\n  {name}\n  {site['url']}\n{'='*60}")
    start = time.time()
    report: dict = {
        "name": name, "url": site["url"], "surface": site["surface"],
        "status": None, "verdict": None, "record_count": 0,
        "fields_found": [], "fields_missing": [], "expected_fields": site["expected_fields"],
        "coverage": 0.0, "sample_data": None, "error": None,
        "elapsed_seconds": 0, "acquisition_method": None, "key_logs": [],
    }
    try:
        async with SessionLocal() as s:
            run = await create_crawl_run(s, user_id, {
                "run_type": site["run_type"], "url": site["url"],
                "surface": site["surface"],
                "settings": {"max_records": 30, "max_pages": 2, "sleep_ms": 500, "advanced_mode": "auto", "llm_enabled": False},
                "additional_fields": site.get("expected_fields", []),
            })
            run_id = run.id

        async with SessionLocal() as s:
            await process_run(s, run_id)

        async with SessionLocal() as s:
            run = await s.get(CrawlRun, run_id)
            report["status"] = run.status
            rs = run.result_summary or {}
            report["record_count"] = rs.get("record_count", 0)
            report["verdict"] = rs.get("extraction_verdict")

            recs = list((await s.execute(select(CrawlRecord).where(CrawlRecord.run_id == run_id).limit(5))).scalars())
            if recs:
                report["sample_data"] = {k: v for k, v in (recs[0].data or {}).items() if v not in (None, "", [], {})}
                report["acquisition_method"] = (recs[0].source_trace or {}).get("method")
                all_fields: set[str] = set()
                for r in recs:
                    all_fields.update((r.data or {}).keys())
                report["fields_found"] = sorted(all_fields)
                report["fields_missing"] = [f for f in site["expected_fields"] if f not in all_fields]
                exp = site["expected_fields"]
                report["coverage"] = round(len([f for f in exp if f in all_fields]) / len(exp), 2) if exp else 0

            logs = list((await s.execute(
                select(CrawlLog).where(CrawlLog.run_id == run_id).order_by(CrawlLog.created_at.asc())
            )).scalars())
            report["key_logs"] = [
                f"[{l.level.upper()}] {l.message}"
                for l in logs
                if l.level in ("warning", "error") or any(k in l.message for k in ("[ACQUIRE]", "[BLOCKED]", "[EXTRACT]", "[PUBLISH]", "verdict"))
            ][:15]

    except Exception as exc:
        import traceback
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["status"] = "error"
        traceback.print_exc()

    report["elapsed_seconds"] = round(time.time() - start, 1)
    return report


async def main(*, create_tables: bool = False):
    _ensure_audit_allowed()

    user_id: int | None = None
    created_test_user = False
    await _prepare_schema(create_tables=create_tables)
    try:
        async with SessionLocal() as s:
            user_id, created_test_user = await ensure_test_user(s)

        reports = []
        for site in TEST_SITES:
            r = await run_site(site, user_id)
            reports.append(r)
            icon = "PASS" if r["verdict"] == "success" else "WARN" if r["verdict"] in ("partial",) else "FAIL"
            print(f"\n  [{icon}] {r['name']}")
            print(f"       Status={r['status']}  Verdict={r['verdict']}  Records={r['record_count']}  Coverage={r['coverage']}  Time={r['elapsed_seconds']}s")
            if r["fields_found"]:
                print(f"       Fields: {', '.join(r['fields_found'][:15])}")
            if r["fields_missing"]:
                print(f"       Missing: {', '.join(r['fields_missing'])}")
            if r["error"]:
                print(f"       Error: {r['error'][:150]}")
            for log in r.get("key_logs", [])[:5]:
                print(f"       > {log[:120]}")

        print(f"\n{'='*60}")
        passed = sum(1 for r in reports if r["verdict"] == "success")
        partial = sum(1 for r in reports if r["verdict"] == "partial")
        failed = len(reports) - passed - partial
        print(f"  TOTAL: {len(reports)} sites | {passed} passed | {partial} partial | {failed} failed")
        print(f"{'='*60}")

        with open("audit_report.json", "w") as f:
            json.dump(reports, f, indent=2, default=str)
        print("Report saved to audit_report.json")
    finally:
        if user_id is not None:
            async with SessionLocal() as s:
                await cleanup_test_user(s, user_id, created=created_test_user)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the crawler pipeline audit suite.")
    parser.add_argument(
        "--create-tables",
        action="store_true",
        help="Opt in to creating missing tables before the audit runs.",
    )
    args = parser.parse_args()
    asyncio.run(main(create_tables=args.create_tables))
