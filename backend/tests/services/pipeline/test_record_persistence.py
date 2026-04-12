from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crawl import CrawlRecord, CrawlRun
from app.services.pipeline.record_persistence import (
    ListingPersistenceCandidate,
    build_listing_record,
    persist_crawl_record,
)


@pytest.mark.asyncio
async def test_persist_crawl_record_skips_duplicate_listing_record_without_poisoning_session(
    db_session: AsyncSession,
    test_user,
) -> None:
    run = CrawlRun(
        user_id=test_user.id,
        run_type="batch",
        url="https://example.com/jobs",
        status="running",
        surface="job_listing",
        settings={},
        requested_fields=[],
        result_summary={},
    )
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)

    first_candidate = ListingPersistenceCandidate(
        source_url="https://example.com/jobs/1",
        data={
            "title": "Platform Engineer",
            "url": "https://example.com/jobs/1",
        },
        raw_data={"title": "Platform Engineer"},
        source_trace={"type": "listing"},
        identity_key="job-1",
    )
    duplicate_candidate = ListingPersistenceCandidate(
        source_url="https://example.com/jobs/1",
        data={
            "title": "Platform Engineer",
            "url": "https://example.com/jobs/1",
        },
        raw_data={"title": "Platform Engineer"},
        source_trace={"type": "listing"},
        identity_key="job-1",
    )
    next_candidate = ListingPersistenceCandidate(
        source_url="https://example.com/jobs/2",
        data={
            "title": "Data Engineer",
            "url": "https://example.com/jobs/2",
        },
        raw_data={"title": "Data Engineer"},
        source_trace={"type": "listing"},
        identity_key="job-2",
    )

    assert await persist_crawl_record(
        db_session,
        build_listing_record(
            run_id=run.id,
            candidate=first_candidate,
            index=0,
            manifest_trace=None,
            raw_html_path=None,
        ),
    )
    assert not await persist_crawl_record(
        db_session,
        build_listing_record(
            run_id=run.id,
            candidate=duplicate_candidate,
            index=1,
            manifest_trace=None,
            raw_html_path=None,
        ),
    )
    assert await persist_crawl_record(
        db_session,
        build_listing_record(
            run_id=run.id,
            candidate=next_candidate,
            index=2,
            manifest_trace=None,
            raw_html_path=None,
        ),
    )

    await db_session.commit()

    records = (
        await db_session.execute(
            select(CrawlRecord)
            .where(CrawlRecord.run_id == run.id)
            .order_by(CrawlRecord.source_url.asc())
        )
    ).scalars().all()

    assert [record.source_url for record in records] == [
        "https://example.com/jobs/1",
        "https://example.com/jobs/2",
    ]


@pytest.mark.asyncio
async def test_persist_crawl_record_reraises_non_duplicate_integrity_errors() -> None:
    class _FakeOrig(Exception):
        sqlstate = "23503"

    db_record = CrawlRecord(run_id=1, source_url="https://example.com/jobs/1")

    class _NestedTx:
        async def __aenter__(self):
            return None

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _FakeSession:
        def __init__(self) -> None:
            self._bind = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

        def get_bind(self):
            return self._bind

        def begin_nested(self):
            return _NestedTx()

        def add(self, _record):
            return None

        async def flush(self):
            raise IntegrityError("INSERT", {}, _FakeOrig())

        def __contains__(self, _record):
            return False

    session = _FakeSession()

    with pytest.raises(IntegrityError):
        await persist_crawl_record(session, db_record)


@pytest.mark.asyncio
async def test_persist_crawl_record_uses_sqlite_conflict_ignore_for_identity_key() -> None:
    db_record = CrawlRecord(
        run_id=1,
        source_url="https://example.com/jobs/1",
        url_identity_key="job-1",
        data={},
        raw_data={},
        discovered_data={},
        source_trace={},
    )

    class _FakeSession:
        def __init__(self, rowcount: int) -> None:
            self._bind = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))
            self.rowcount = rowcount
            self.executed = False

        def get_bind(self):
            return self._bind

        async def execute(self, _statement):
            self.executed = True
            return SimpleNamespace(rowcount=self.rowcount)

        def begin_nested(self):
            raise AssertionError("sqlite identity-key inserts should not use savepoints")

    inserted_session = _FakeSession(rowcount=1)
    duplicate_session = _FakeSession(rowcount=0)

    assert await persist_crawl_record(inserted_session, db_record)
    assert inserted_session.executed is True

    assert not await persist_crawl_record(duplicate_session, db_record)
    assert duplicate_session.executed is True
