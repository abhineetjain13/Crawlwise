from __future__ import annotations

import contextlib
import json
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import pytest
from app.models.crawl import CrawlRecord, CrawlRun
from app.services.crawl_service import create_crawl_run, process_run
from app.services.url_safety import ValidatedTarget
from sqlalchemy import select

PRODUCT_NAME = "Deterministic Smoke Test Product"
PRODUCT_PRICE = "19.99"


class _ProductHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path != "/product/1":
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        payload = {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": PRODUCT_NAME,
            "brand": {"@type": "Brand", "name": "SmokeCo"},
            "offers": {
                "@type": "Offer",
                "priceCurrency": "USD",
                "price": PRODUCT_PRICE,
                "availability": "https://schema.org/InStock",
            },
        }
        html = f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <title>{PRODUCT_NAME}</title>
    <script type="application/ld+json">{json.dumps(payload)}</script>
  </head>
  <body>
    <main>
      <h1>{PRODUCT_NAME}</h1>
      <p>Local smoke-test product page for deterministic crawl verification.</p>
    </main>
  </body>
</html>
"""
        body = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


@pytest.fixture
def local_product_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ProductHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        yield {
            "bind_host": host,
            "port": port,
            "url": f"http://localhost:{port}/product/1",
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def allow_localhost_crawl_targets(monkeypatch: pytest.MonkeyPatch):
    async def _allow_localhost_target(url: str) -> ValidatedTarget:
        parsed = urlparse(str(url or "").strip())
        hostname = str(parsed.hostname or "").strip().lower()
        if hostname in {"localhost", "127.0.0.1"}:
            return ValidatedTarget(
                hostname=hostname,
                scheme=str(parsed.scheme or "http").lower(),
                port=int(parsed.port or 80),
                resolved_ips=("127.0.0.1",),
                dns_resolved=False,
            )
        return await _original_validate_public_target(url)

    async def _allow_localhost_targets(_urls) -> None:
        return None

    from app.services import crawl_crud
    from app.services.acquisition import acquirer, browser_client, http_client, traversal
    from app.services.url_safety import validate_public_target as _original_validate_public_target

    monkeypatch.setattr(crawl_crud, "ensure_public_crawl_targets", _allow_localhost_targets)
    monkeypatch.setattr(http_client, "validate_public_target", _allow_localhost_target)
    monkeypatch.setattr(acquirer, "validate_public_target", _allow_localhost_target)
    monkeypatch.setattr(browser_client, "validate_public_target", _allow_localhost_target)
    monkeypatch.setattr(traversal, "validate_public_target", _allow_localhost_target)


@pytest.mark.asyncio
async def test_smoke_crawl_persists_local_product_page(
    db_session,
    test_user,
    local_product_server,
    allow_localhost_crawl_targets,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": local_product_server["url"],
            "surface": "ecommerce_detail",
        },
    )

    await process_run(db_session, run.id)
    await db_session.refresh(run)

    records = (
        (
            await db_session.execute(
                select(CrawlRecord)
                .where(CrawlRecord.run_id == run.id)
                .order_by(CrawlRecord.created_at.asc())
            )
        )
        .scalars()
        .all()
    )

    assert records, "expected at least one persisted product record"

    record = records[0]
    assert record.data["title"] == PRODUCT_NAME
    assert str(record.data["price"]) == PRODUCT_PRICE

    refreshed_run = await db_session.get(CrawlRun, run.id)
    assert refreshed_run is not None
    assert refreshed_run.result_summary.get("extraction_verdict") in {"success", "partial"}
    assert refreshed_run.status != "failed"

    with contextlib.suppress(KeyError):
        assert record.data["brand"] == "SmokeCo"
