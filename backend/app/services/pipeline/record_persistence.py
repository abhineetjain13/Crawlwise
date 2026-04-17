from __future__ import annotations

from app.services.publish.record_persistence import (
    DatabaseRecordWriter,
    ExtractionRecordWriter,
    ListingPersistenceCandidate,
    MemoryRecordWriter,
    build_crawl_record,
    build_discovered_data_payload,
    build_listing_record,
    collect_winning_sources,
    dedupe_listing_persistence_candidates,
    listing_fallback_identity_key,
    persist_crawl_record,
    persist_normalized_record,
    persist_normalized_record_to_session,
    record_identity_fingerprint,
    resolve_record_writer,
)

__all__ = [
    "DatabaseRecordWriter",
    "ExtractionRecordWriter",
    "ListingPersistenceCandidate",
    "MemoryRecordWriter",
    "build_crawl_record",
    "build_discovered_data_payload",
    "build_listing_record",
    "collect_winning_sources",
    "dedupe_listing_persistence_candidates",
    "listing_fallback_identity_key",
    "persist_crawl_record",
    "persist_normalized_record",
    "persist_normalized_record_to_session",
    "record_identity_fingerprint",
    "resolve_record_writer",
]
