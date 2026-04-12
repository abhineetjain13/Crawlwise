from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from app.models.crawl import CrawlRecord
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .field_normalization import _sanitize_persisted_record_payload
from .utils import _compact_dict

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ListingPersistenceCandidate:
    source_url: str
    data: dict[str, object]
    raw_data: dict[str, object]
    source_trace: dict[str, object]
    identity_key: str = ""
    fallback_key: str = ""


def build_discovered_data_payload(
    *,
    review_bucket: list[dict[str, object]] | None = None,
    requested_field_coverage: dict[str, object] | None = None,
) -> dict[str, object]:
    return _compact_dict(
        {
            "discovered_fields": review_bucket or None,
            "review_bucket": review_bucket or None,
            "requested_field_coverage": requested_field_coverage or None,
        }
    )


@runtime_checkable
class ExtractionRecordWriter(Protocol):
    async def persist_listing_candidate(
        self,
        *,
        run_id: int,
        candidate: ListingPersistenceCandidate,
        index: int,
        manifest_trace: dict[str, object] | None,
        raw_html_path: str | None,
    ) -> bool:
        ...

    async def persist_normalized_record(
        self,
        *,
        run_id: int,
        source_url: str,
        data: dict[str, object],
        raw_data: dict[str, object],
        review_bucket: list[dict[str, object]] | None = None,
        requested_field_coverage: dict[str, object] | None = None,
        discovered_data: dict[str, object] | None = None,
        source_trace: dict[str, object],
        raw_html_path: str | None,
    ) -> bool:
        ...

    async def flush(self) -> None:
        ...


class DatabaseRecordWriter:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def persist_listing_candidate(
        self,
        *,
        run_id: int,
        candidate: ListingPersistenceCandidate,
        index: int,
        manifest_trace: dict[str, object] | None,
        raw_html_path: str | None,
    ) -> bool:
        db_record = build_listing_record(
            run_id=run_id,
            candidate=candidate,
            index=index,
            manifest_trace=manifest_trace,
            raw_html_path=raw_html_path,
        )
        return await persist_crawl_record(self.session, db_record)

    async def persist_normalized_record(
        self,
        *,
        run_id: int,
        source_url: str,
        data: dict[str, object],
        raw_data: dict[str, object],
        review_bucket: list[dict[str, object]] | None = None,
        requested_field_coverage: dict[str, object] | None = None,
        discovered_data: dict[str, object] | None = None,
        source_trace: dict[str, object],
        raw_html_path: str | None,
    ) -> bool:
        return await persist_normalized_record_to_session(
            self.session,
            run_id=run_id,
            source_url=source_url,
            data=data,
            raw_data=raw_data,
            review_bucket=review_bucket,
            requested_field_coverage=requested_field_coverage,
            discovered_data=discovered_data,
            source_trace=source_trace,
            raw_html_path=raw_html_path,
        )

    async def flush(self) -> None:
        await self.session.flush()


@dataclass(slots=True)
class MemoryRecordWriter:
    records: list[CrawlRecord] = field(default_factory=list)

    async def persist_listing_candidate(
        self,
        *,
        run_id: int,
        candidate: ListingPersistenceCandidate,
        index: int,
        manifest_trace: dict[str, object] | None,
        raw_html_path: str | None,
    ) -> bool:
        self.records.append(
            build_listing_record(
                run_id=run_id,
                candidate=candidate,
                index=index,
                manifest_trace=manifest_trace,
                raw_html_path=raw_html_path,
            )
        )
        return True

    async def persist_normalized_record(
        self,
        *,
        run_id: int,
        source_url: str,
        data: dict[str, object],
        raw_data: dict[str, object],
        review_bucket: list[dict[str, object]] | None = None,
        requested_field_coverage: dict[str, object] | None = None,
        discovered_data: dict[str, object] | None = None,
        source_trace: dict[str, object],
        raw_html_path: str | None,
    ) -> bool:
        record_discovered_data = (
            build_discovered_data_payload(
                review_bucket=review_bucket,
                requested_field_coverage=requested_field_coverage,
            )
            if discovered_data is None
            else discovered_data
        )
        self.records.append(
            build_crawl_record(
                run_id=run_id,
                source_url=source_url,
                data=data,
                raw_data=raw_data,
                discovered_data=record_discovered_data,
                source_trace=source_trace,
                raw_html_path=raw_html_path,
            )
        )
        return True

    async def flush(self) -> None:
        return None


def resolve_record_writer(
    session: AsyncSession,
    record_writer: ExtractionRecordWriter | None = None,
) -> ExtractionRecordWriter:
    return record_writer if record_writer is not None else DatabaseRecordWriter(session)


async def persist_normalized_record_to_session(
    session: AsyncSession,
    *,
    run_id: int,
    source_url: str,
    data: dict[str, object],
    raw_data: dict[str, object],
    review_bucket: list[dict[str, object]] | None = None,
    requested_field_coverage: dict[str, object] | None = None,
    discovered_data: dict[str, object] | None = None,
    source_trace: dict[str, object],
    raw_html_path: str | None,
) -> bool:
    record_discovered_data = (
        build_discovered_data_payload(
            review_bucket=review_bucket,
            requested_field_coverage=requested_field_coverage,
        )
        if discovered_data is None
        else discovered_data
    )
    db_record = build_crawl_record(
        run_id=run_id,
        source_url=source_url,
        data=data,
        raw_data=raw_data,
        discovered_data=record_discovered_data,
        source_trace=source_trace,
        raw_html_path=raw_html_path,
    )
    return await persist_crawl_record(session, db_record)


async def persist_normalized_record(
    session: AsyncSession,
    *,
    run_id: int,
    source_url: str,
    data: dict[str, object],
    raw_data: dict[str, object],
    review_bucket: list[dict[str, object]] | None = None,
    requested_field_coverage: dict[str, object] | None = None,
    discovered_data: dict[str, object] | None = None,
    source_trace: dict[str, object],
    raw_html_path: str | None,
) -> bool:
    return await persist_normalized_record_to_session(
        session,
        run_id=run_id,
        source_url=source_url,
        data=data,
        raw_data=raw_data,
        review_bucket=review_bucket,
        requested_field_coverage=requested_field_coverage,
        discovered_data=discovered_data,
        source_trace=source_trace,
        raw_html_path=raw_html_path,
    )


def build_crawl_record(
    *,
    run_id: int,
    source_url: str,
    data: dict[str, object],
    raw_data: dict[str, object],
    discovered_data: dict[str, object] | None,
    source_trace: dict[str, object],
    raw_html_path: str | None,
) -> CrawlRecord:
    persisted_data, persisted_discovered_data = _sanitize_persisted_record_payload(
        data,
        discovered_data=discovered_data,
    )
    return CrawlRecord(
        run_id=run_id,
        source_url=source_url,
        url_identity_key=record_identity_fingerprint(
            source_url=source_url,
            data=persisted_data,
            raw_data=raw_data,
        ),
        data=persisted_data,
        raw_data=raw_data,
        discovered_data=persisted_discovered_data,
        source_trace=source_trace,
        raw_html_path=raw_html_path,
    )


def build_listing_record(
    *,
    run_id: int,
    candidate: ListingPersistenceCandidate,
    index: int,
    manifest_trace: dict[str, object] | None,
    raw_html_path: str | None,
) -> CrawlRecord:
    raw_identity = str(candidate.identity_key or "").strip()
    if not raw_identity:
        raw_identity = str(candidate.fallback_key or "").strip()
    url_identity_key: str | None = None
    if raw_identity:
        hash_input = f"{candidate.source_url}|{raw_identity}"
        url_identity_key = hashlib.sha256(
            hash_input.encode("utf-8", errors="replace")
        ).hexdigest()[:64]

    record_source_trace = dict(candidate.source_trace)
    if index == 0 and manifest_trace:
        record_source_trace["manifest_trace"] = manifest_trace

    return CrawlRecord(
        run_id=run_id,
        source_url=candidate.source_url,
        url_identity_key=url_identity_key,
        data=dict(candidate.data),
        raw_data=dict(candidate.raw_data),
        discovered_data={},
        source_trace=record_source_trace,
        raw_html_path=raw_html_path,
    )


def record_identity_fingerprint(*, source_url: str, data: object, raw_data: object) -> str:
    payload = {"data": data, "raw_data": raw_data}
    encoded = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(
        f"{source_url}|{encoded}".encode("utf-8", errors="replace")
    ).hexdigest()[:64]


async def persist_crawl_record(
    session: AsyncSession,
    db_record: CrawlRecord,
) -> bool:
    bind = session.get_bind()
    dialect_name = getattr(getattr(bind, "dialect", None), "name", "")
    if dialect_name == "postgresql" and db_record.url_identity_key:
        statement = pg_insert(CrawlRecord.__table__).values(
            run_id=db_record.run_id,
            source_url=db_record.source_url,
            url_identity_key=db_record.url_identity_key,
            data=db_record.data,
            raw_data=db_record.raw_data,
            discovered_data=db_record.discovered_data,
            source_trace=db_record.source_trace,
            raw_html_path=db_record.raw_html_path,
        ).on_conflict_do_nothing(
            index_elements=[
                CrawlRecord.__table__.c.run_id,
                CrawlRecord.__table__.c.url_identity_key,
            ],
            index_where=CrawlRecord.__table__.c.url_identity_key.isnot(None),
        )
        result = await session.execute(statement)
        return bool(getattr(result, "rowcount", 0) or 0)

    try:
        async with session.begin_nested():
            session.add(db_record)
            await session.flush()
        return True
    except IntegrityError as exc:
        if not _is_duplicate_integrity_error(exc):
            raise
        if db_record in session:
            session.expunge(db_record)
        logger.debug(
            "Skipping duplicate crawl record for run_id=%s source_url=%s",
            db_record.run_id,
            db_record.source_url,
            exc_info=True,
        )
        return False


def _is_duplicate_integrity_error(exc: IntegrityError) -> bool:
    orig = getattr(exc, "orig", None)
    sqlstate = getattr(orig, "pgcode", None) or getattr(orig, "sqlstate", None)
    if sqlstate == "23505":
        return True
    message = str(orig or exc).lower()
    return "duplicate key" in message or "unique constraint failed" in message


def listing_fallback_identity_key(record: dict[str, object]) -> str:
    return "|".join(
        [
            str(record.get("title") or "").strip().lower(),
            str(record.get("url") or record.get("apply_url") or "").strip().lower(),
        ]
    ).strip("|")


def dedupe_listing_persistence_candidates(
    candidates: list[ListingPersistenceCandidate],
    *,
    on_duplicate: Callable[[str], object] | None = None,
) -> tuple[list[ListingPersistenceCandidate], dict[str, int]]:
    deduped: list[ListingPersistenceCandidate] = []
    stats = {"duplicate_drops": 0}
    seen_identity_keys: set[str] = set()
    seen_fallback_keys: set[str] = set()

    for candidate in candidates:
        identity_key = str(candidate.identity_key or "").strip()
        fallback_key = str(candidate.fallback_key or "").strip()
        collision_key = ""

        if identity_key and identity_key in seen_identity_keys:
            collision_key = identity_key
        elif fallback_key and fallback_key in seen_fallback_keys:
            collision_key = fallback_key

        if collision_key:
            stats["duplicate_drops"] += 1
            if on_duplicate is not None:
                on_duplicate(collision_key)
            continue

        if identity_key:
            seen_identity_keys.add(identity_key)
        if fallback_key:
            seen_fallback_keys.add(fallback_key)
        deduped.append(candidate)

    return deduped, stats


def collect_winning_sources(
    source_trace: dict[str, object],
    saved_record: dict[str, object] | None,
) -> list[str]:
    if not saved_record:
        return []
    winning_sources: list[str] = []
    committed_fields = (
        source_trace.get("committed_fields")
        if isinstance(source_trace.get("committed_fields"), dict)
        else {}
    )
    field_discovery = (
        source_trace.get("field_discovery")
        if isinstance(source_trace.get("field_discovery"), dict)
        else {}
    )
    for field_name in saved_record.keys():
        src_map = committed_fields.get(field_name) or field_discovery.get(field_name, {})
        if isinstance(src_map, dict):
            source = src_map.get("source")
            if source:
                winning_sources.append(f"{field_name}:{source}")
                continue
            sources = src_map.get("sources")
            if isinstance(sources, list) and sources:
                winning_sources.append(f"{field_name}:{sources[0]}")
                continue
            if isinstance(sources, str):
                winning_sources.append(f"{field_name}:{sources}")
                continue
        winning_sources.append(f"{field_name}:unknown")
    return winning_sources
