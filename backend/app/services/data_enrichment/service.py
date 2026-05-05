from __future__ import annotations
import logging
import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import SessionLocal
from app.models.crawl import CrawlRecord, CrawlRun, DataEnrichmentJob, EnrichedProduct
from app.models.user import User
from app.services.config.data_enrichment import (
    DATA_ENRICHMENT_BASE_REQUIRED_ATTRIBUTES,
    DATA_ENRICHMENT_AVAILABILITY_CANDIDATE_SOURCES,
    DATA_ENRICHMENT_AVAILABILITY_CANDIDATE_TARGETS,
    DATA_ENRICHMENT_COLOR_CANDIDATE_FIELDS,
    DATA_ENRICHMENT_COLOR_CANDIDATE_SOURCES,
    DATA_ENRICHMENT_COLOR_CANDIDATE_TARGETS,
    DATA_ENRICHMENT_LLM_BACKFILL_FIELDS,
    DATA_ENRICHMENT_LLM_TASK,
    DATA_ENRICHMENT_MATERIAL_CONTEXT_STRIP_PATTERNS,
    DATA_ENRICHMENT_MATERIAL_FALLBACK_FIELDS,
    DATA_ENRICHMENT_MATERIAL_PRIMARY_FIELDS,
    DATA_ENRICHMENT_SIZE_CANDIDATE_FIELDS,
    DATA_ENRICHMENT_SIZE_CANDIDATE_SOURCES,
    DATA_ENRICHMENT_SIZE_CANDIDATE_TARGETS,
    DATA_ENRICHMENT_SKIP_RECORD_STATUSES,
    DATA_ENRICHMENT_STATUS_DEGRADED,
    DATA_ENRICHMENT_STATUS_ENRICHED,
    DATA_ENRICHMENT_STATUS_FAILED,
    DATA_ENRICHMENT_STATUS_PENDING,
    DATA_ENRICHMENT_STATUS_RUNNING,
    DATA_ENRICHMENT_TAXONOMY_VERSION,
    ECOMMERCE_DETAIL_SURFACE,
    data_enrichment_settings,
)
from app.services.crawl_access_service import (
    require_accessible_record,
    require_accessible_run,
)
from app.services.data_enrichment.shopify_catalog import (
    attribute_lookup_keys,
    category_attribute_handles,
    load_attribute_repository_data,
    load_taxonomy_index,
    repository_terms,
    taxonomy_reference_for_category_path,
    term_dict,
    top_taxonomy_candidates,
)
from app.services.field_value_core import (
    clean_text,
    extract_currency_code,
    infer_currency_from_page_url,
    strip_html_tags,
    text_or_none,
)
from app.services.llm_runtime import run_prompt_task
from app.services.normalizers import normalize_decimal_price
from app.services.product_intelligence.matching import source_domain

_token_re = re.compile(r"[a-z0-9]+")
_PRICE_RANGE_RE = re.compile(r"(.+?)(?:\s+(?:to)\s+|\s*[-–]\s*)(.+)", re.I)
logger = logging.getLogger(__name__)


async def create_data_enrichment_job(
    session: AsyncSession,
    *,
    user: User,
    payload: dict[str, object],
) -> DataEnrichmentJob:
    options = _normalized_options(payload.get("options"))
    source_run_id = _as_int(payload.get("source_run_id"))
    source_records = await _load_source_records(
        session, user=user, payload=payload, options=options
    )
    if not source_records:
        raise ValueError("Data Enrichment needs at least one ecommerce detail record")
    if source_run_id is not None:
        await require_accessible_run(session, run_id=source_run_id, user=user)
    accepted_records: list[CrawlRecord] = []
    skipped_status = 0
    skipped_surface = 0
    for record in source_records:
        run = await session.get(CrawlRun, record.run_id)
        if (
            run is None
            or str(run.surface or "").strip().lower() != ECOMMERCE_DETAIL_SURFACE
        ):
            skipped_surface += 1
            continue
        if (
            str(record.enrichment_status or "").strip().lower()
            in DATA_ENRICHMENT_SKIP_RECORD_STATUSES
        ):
            skipped_status += 1
            continue
        accepted_records.append(record)
    if not accepted_records:
        raise ValueError("No unenriched ecommerce detail records selected")
    job = DataEnrichmentJob(
        user_id=user.id,
        source_run_id=source_run_id,
        status=DATA_ENRICHMENT_STATUS_PENDING,
        options={
            **options,
            "source_record_ids": [record.id for record in accepted_records],
        },
        summary={
            "requested_count": len(source_records),
            "accepted_count": len(accepted_records),
            "skipped_status_count": skipped_status,
            "skipped_surface_count": skipped_surface,
        },
    )
    session.add(job)
    await session.flush()
    for record in accepted_records:
        record.enrichment_status = DATA_ENRICHMENT_STATUS_PENDING
        record.enriched_at = None
        await _upsert_enriched_product(session, job=job, record=record)
    await session.commit()
    await session.refresh(job)
    return job


async def run_data_enrichment_job(job_id: int) -> None:
    async with SessionLocal() as session:
        job = await session.get(DataEnrichmentJob, job_id)
        if job is None or job.status != DATA_ENRICHMENT_STATUS_PENDING:
            return
        await _run_job(session, job)


async def list_data_enrichment_jobs(
    session: AsyncSession,
    *,
    user: User,
    limit: int = 25,
) -> list[DataEnrichmentJob]:
    statement = (
        select(DataEnrichmentJob).order_by(DataEnrichmentJob.id.desc()).limit(limit)
    )
    if user.role != "admin":
        statement = statement.where(DataEnrichmentJob.user_id == user.id)
    return list((await session.scalars(statement)).all())


async def get_data_enrichment_job(
    session: AsyncSession,
    *,
    user: User,
    job_id: int,
) -> DataEnrichmentJob:
    job = await session.get(DataEnrichmentJob, job_id)
    if job is None or (user.role != "admin" and job.user_id != user.id):
        raise LookupError("Data Enrichment job not found")
    return job


async def build_data_enrichment_job_payload(
    session: AsyncSession,
    *,
    job: DataEnrichmentJob,
) -> dict[str, object]:
    products = list(
        (
            await session.scalars(
                select(EnrichedProduct)
                .where(EnrichedProduct.job_id == job.id)
                .order_by(EnrichedProduct.id)
            )
        ).all()
    )
    return {
        "job": job,
        "enriched_products": products,
    }


async def _run_job(session: AsyncSession, job: DataEnrichmentJob) -> None:
    now = datetime.now(UTC)
    job_id = int(job.id)
    job.status = DATA_ENRICHMENT_STATUS_RUNNING
    job.summary = {**dict(job.summary or {}), "started_at": now.isoformat()}
    products = list(
        (
            await session.scalars(
                select(EnrichedProduct)
                .where(EnrichedProduct.job_id == job_id)
                .order_by(EnrichedProduct.id)
            )
        ).all()
    )
    product_refs = [
        (int(product.id), int(product.source_record_id))
        for product in products
        if product.id is not None and product.source_record_id is not None
    ]
    await session.flush()

    enriched_count = 0
    failed_count = 0
    llm_enabled = bool((job.options or {}).get("llm_enabled"))
    for product_id, source_record_id in product_refs:
        product = await session.get(EnrichedProduct, product_id)
        record = await session.get(CrawlRecord, source_record_id)
        if product is None or record is None:
            if product is None:
                failed_count += 1
                continue
            product.status = DATA_ENRICHMENT_STATUS_FAILED
            product.diagnostics = {"error": "source_record_missing"}
            failed_count += 1
            continue
        record_id = record.id
        try:
            await _enrich_product(
                session,
                job=job,
                product=product,
                record=record,
                llm_enabled=llm_enabled,
            )
        except Exception as exc:  # pragma: no cover - defensive job isolation
            if isinstance(exc, SQLAlchemyError):
                await session.rollback()
                refreshed_job = await session.get(DataEnrichmentJob, job_id)
                refreshed_product = await session.get(EnrichedProduct, product_id)
                refreshed_record = await session.get(CrawlRecord, record_id)
                if (
                    refreshed_job is None
                    or refreshed_product is None
                    or refreshed_record is None
                ):
                    raise
                job = refreshed_job
                product = refreshed_product
                record = refreshed_record
            product.status = DATA_ENRICHMENT_STATUS_FAILED
            product.diagnostics = {"error": str(exc)}
            record.enrichment_status = DATA_ENRICHMENT_STATUS_FAILED
            failed_count += 1
        else:
            product.status = DATA_ENRICHMENT_STATUS_ENRICHED
            record.enrichment_status = DATA_ENRICHMENT_STATUS_ENRICHED
            record.enriched_at = datetime.now(UTC)
            enriched_count += 1

    completed_at = datetime.now(UTC)
    job.completed_at = completed_at
    if failed_count and enriched_count:
        job.status = DATA_ENRICHMENT_STATUS_DEGRADED
    elif failed_count:
        job.status = DATA_ENRICHMENT_STATUS_FAILED
    else:
        job.status = DATA_ENRICHMENT_STATUS_ENRICHED
    job.summary = {
        **dict(job.summary or {}),
        "completed_at": completed_at.isoformat(),
        "enriched_count": enriched_count,
        "failed_count": failed_count,
        "llm_enabled": llm_enabled,
    }
    await session.commit()


async def _enrich_product(
    session: AsyncSession,
    *,
    job: DataEnrichmentJob,
    product: EnrichedProduct,
    record: CrawlRecord,
    llm_enabled: bool,
) -> None:
    data = dict(record.data or {})
    deterministic = _build_deterministic_enrichment(data, source_url=record.source_url)
    category_match = deterministic.pop("_taxonomy_match", None)
    category_candidates = deterministic.pop("_taxonomy_candidates", None)
    product_attributes = deterministic.pop("_product_attributes", None)
    for key, value in deterministic.items():
        setattr(product, key, value)
    product.taxonomy_version = DATA_ENRICHMENT_TAXONOMY_VERSION
    diagnostics: dict[str, object] = {
        "deterministic": True,
        "llm_requested": llm_enabled,
        "category_source": "deterministic" if product.category_path else "",
        "product_category": category_match or {},
        "product_attributes": product_attributes or {},
    }
    if category_candidates:
        diagnostics["category_candidates"] = category_candidates
    if llm_enabled:
        llm_result = await _run_llm_enrichment(
            session,
            job=job,
            record=record,
            product=product,
            source_data=data,
            category_candidates=category_candidates or [],
        )
        diagnostics["llm"] = llm_result
        if llm_result.get("category_applied"):
            diagnostics["category_source"] = "llm"
    else:
        product.intent_attributes = None
        product.audience = None
        product.style_tags = None
        product.ai_discovery_tags = None
        product.suggested_bundles = None
    product.diagnostics = diagnostics


def _build_deterministic_enrichment(
    data: dict[str, object], *, source_url: str
) -> dict[str, object]:
    attribute_data = {**data, "source_url": source_url}
    price_normalized = _normalize_price(data, source_url=source_url)
    repository = _load_attribute_repository()
    terms = repository_terms(repository)
    category_candidates = _top_taxonomy_candidates(data)
    category_match = category_candidates[0] if category_candidates else None
    category_path = (
        text_or_none(category_match.get("category_path")) if category_match else None
    )
    color_family = _normalize_from_terms(
        [
            *_candidate_values(
                data,
                *DATA_ENRICHMENT_COLOR_CANDIDATE_FIELDS,
            ),
            *_targeted_candidate_values(
                data,
                DATA_ENRICHMENT_COLOR_CANDIDATE_TARGETS,
                *DATA_ENRICHMENT_COLOR_CANDIDATE_SOURCES,
            ),
        ],
        term_dict(terms, "color_families"),
    )
    size_normalized, size_system = _normalize_sizes(
        data,
        terms=terms,
        category_match=category_match,
    )
    gender_normalized = _normalize_from_terms(
        _candidate_values(data, "gender", "category", "product_type", "title"),
        term_dict(terms, "gender_terms"),
    )
    materials_normalized = _normalize_materials(data, terms=terms)
    availability_normalized = _normalize_from_terms(
        [
            *_candidate_values(data, "availability", "product_attributes"),
            *_targeted_candidate_values(
                data,
                DATA_ENRICHMENT_AVAILABILITY_CANDIDATE_TARGETS,
                *DATA_ENRICHMENT_AVAILABILITY_CANDIDATE_SOURCES,
            ),
        ],
        term_dict(terms, "availability_terms"),
    )
    seo_keywords = _build_seo_keywords(
        data,
        color_family=color_family,
        size_values=size_normalized,
        gender=gender_normalized,
        materials=materials_normalized,
        category_path=category_path,
    )
    return {
        "price_normalized": price_normalized,
        "color_family": color_family,
        "size_normalized": size_normalized,
        "size_system": size_system,
        "gender_normalized": gender_normalized,
        "materials_normalized": materials_normalized,
        "availability_normalized": availability_normalized,
        "seo_keywords": seo_keywords,
        "category_path": category_path,
        "_taxonomy_match": category_match,
        "_taxonomy_candidates": category_candidates,
        "_product_attributes": _product_attribute_diagnostics(
            attribute_data, category_match
        ),
    }


async def _run_llm_enrichment(
    session: AsyncSession,
    *,
    job: DataEnrichmentJob,
    record: CrawlRecord,
    product: EnrichedProduct,
    source_data: dict[str, object],
    category_candidates: list[dict[str, object]],
) -> dict[str, object]:
    prompt_context = _llm_prompt_context(
        source_data,
        product=product,
        category_candidates=category_candidates,
    )
    result = await run_prompt_task(
        session,
        task_type=DATA_ENRICHMENT_LLM_TASK,
        run_id=record.run_id,
        domain=source_domain(record.source_url),
        variables={
            "product_json": prompt_context,
            "taxonomy_hint": _taxonomy_hint(
                product.category_path,
                category_candidates=category_candidates,
                missing_fields=_missing_llm_backfill_fields(product),
            ),
        },
    )
    if result.error_message:
        return {
            "applied": False,
            "error": result.error_message,
            "error_category": str(result.error_category or ""),
        }
    if isinstance(result.payload, dict):
        payload = result.payload
    elif hasattr(result.payload, "model_dump"):
        payload = dict(result.payload.model_dump(exclude_none=True))
    else:
        payload = {}
    applied_fields = _apply_llm_payload(product, payload)
    return {
        "applied": bool(applied_fields),
        "category_applied": "category_path" in applied_fields,
        "applied_fields": applied_fields,
        "provider": result.provider or "",
        "model": result.model or "",
    }


def _apply_llm_payload(
    product: EnrichedProduct, payload: dict[str, object]
) -> list[str]:
    applied: list[str] = []
    repository = _load_attribute_repository()
    terms = repository_terms(repository)
    category_path = text_or_none(payload.get("category_path"))
    if product.category_path is None and category_path:
        if taxonomy_reference := taxonomy_reference_for_category_path(
            category_path,
            _load_taxonomy_index(),
        ):
            product.category_path = str(taxonomy_reference.get("category_path") or "")
            applied.append("category_path")
    if product.color_family is None:
        color_family = _normalize_from_terms(
            _string_list(payload.get("color_family"), max_items=1, max_chars=60)
            or [payload.get("color_family")],
            term_dict(terms, "color_families"),
        )
        if color_family:
            product.color_family = color_family
            applied.append("color_family")
    if product.size_normalized is None:
        size_normalized, size_system = _normalize_sizes(
            {
                "size": payload.get("size_normalized"),
                "size_system": payload.get("size_system"),
                "category": product.category_path,
            },
            terms=terms,
            category_match=_match_category_path({"category": product.category_path}),
        )
        if size_normalized:
            product.size_normalized = size_normalized
            applied.append("size_normalized")
        if product.size_system is None and size_system:
            product.size_system = size_system
            applied.append("size_system")
    if product.size_system is None:
        size_system = text_or_none(payload.get("size_system"))
        known_systems = {
            str(key)
            for key in _object_dict(
                term_dict(terms, "size_systems").get("systems")
            ).keys()
        }
        if size_system and size_system in known_systems:
            product.size_system = size_system
            applied.append("size_system")
    if product.gender_normalized is None:
        gender_normalized = _normalize_from_terms(
            _string_list(payload.get("gender_normalized"), max_items=1, max_chars=60)
            or [payload.get("gender_normalized")],
            term_dict(terms, "gender_terms"),
        )
        if gender_normalized:
            product.gender_normalized = gender_normalized
            applied.append("gender_normalized")
    if product.materials_normalized is None:
        materials_normalized = _normalize_materials(
            {"materials": payload.get("materials_normalized")},
            terms=terms,
        )
        if materials_normalized:
            product.materials_normalized = materials_normalized
            applied.append("materials_normalized")
    if product.availability_normalized is None:
        availability_normalized = _normalize_from_terms(
            _string_list(
                payload.get("availability_normalized"), max_items=1, max_chars=60
            )
            or [payload.get("availability_normalized")],
            term_dict(terms, "availability_terms"),
        )
        if availability_normalized:
            product.availability_normalized = availability_normalized
            applied.append("availability_normalized")
    for field_name in (
        "intent_attributes",
        "audience",
        "style_tags",
        "ai_discovery_tags",
        "suggested_bundles",
    ):
        values = _string_list(payload.get(field_name), max_items=10, max_chars=60)
        setattr(product, field_name, values or None)
        if values:
            applied.append(field_name)
    product.taxonomy_version = DATA_ENRICHMENT_TAXONOMY_VERSION
    return applied


async def _upsert_enriched_product(
    session: AsyncSession,
    *,
    job: DataEnrichmentJob,
    record: CrawlRecord,
) -> EnrichedProduct:
    existing = (
        await session.scalars(
            select(EnrichedProduct).where(EnrichedProduct.source_record_id == record.id)
        )
    ).first()
    if existing is not None:
        existing.job_id = job.id
        existing.source_run_id = record.run_id
        existing.source_url = record.source_url
        existing.status = DATA_ENRICHMENT_STATUS_PENDING
        _clear_enriched_fields(existing)
        existing.diagnostics = {}
        return existing
    product = EnrichedProduct(
        job_id=job.id,
        source_run_id=record.run_id,
        source_record_id=record.id,
        source_url=record.source_url,
        status=DATA_ENRICHMENT_STATUS_PENDING,
        diagnostics={},
    )
    session.add(product)
    return product


async def _load_source_records(
    session: AsyncSession,
    *,
    user: User,
    payload: dict[str, object],
    options: dict[str, object],
) -> list[CrawlRecord]:
    record_ids = _source_record_ids(payload)
    if record_ids:
        records: list[CrawlRecord] = []
        for record_id in record_ids[: _option_int(options, "max_source_records")]:
            records.append(
                await require_accessible_record(session, record_id=record_id, user=user)
            )
        return records

    source_run_id = _as_int(payload.get("source_run_id"))
    if source_run_id is None:
        return []
    run = await require_accessible_run(session, run_id=source_run_id, user=user)
    return list(
        (
            await session.scalars(
                select(CrawlRecord)
                .where(CrawlRecord.run_id == run.id)
                .order_by(CrawlRecord.id)
                .limit(_option_int(options, "max_source_records"))
            )
        ).all()
    )


def _normalize_price(
    data: dict[str, object], *, source_url: str
) -> dict[str, object] | None:
    raw_price = _first_present(data, "price", "sale_price", "original_price")
    if raw_price in (None, "", [], {}):
        return None
    currency = (
        extract_currency_code(data.get("currency"))
        or extract_currency_code(raw_price)
        or infer_currency_from_page_url(source_url)
    )
    range_match = _PRICE_RANGE_RE.fullmatch(clean_text(raw_price))
    if range_match:
        price_min = _decimal_text(range_match.group(1))
        price_max = _decimal_text(range_match.group(2))
        if price_min is None or price_max is None:
            return None
        return _without_empty(
            {
                "price_min": float(price_min),
                "price_max": float(price_max),
                "currency": currency,
            }
        )
    amount = _decimal_text(raw_price)
    if amount is None:
        return None
    return _without_empty({"amount": float(amount), "currency": currency})


def _normalize_sizes(
    data: dict[str, object],
    *,
    terms: dict[str, object],
    category_match: dict[str, object] | None = None,
) -> tuple[list[str] | None, str | None]:
    size_config = term_dict(terms, "size_systems")
    aliases_value = size_config.get("aliases")
    aliases_dict = aliases_value if isinstance(aliases_value, dict) else {}
    aliases = {str(k).casefold(): str(v) for k, v in aliases_dict.items()}
    systems_value = size_config.get("systems")
    systems_dict = systems_value if isinstance(systems_value, dict) else {}
    systems = {
        str(system): {str(item).casefold() for item in list(values or [])}
        for system, values in systems_dict.items()
        if isinstance(values, list)
    }
    values = [
        *_candidate_values(data, *DATA_ENRICHMENT_SIZE_CANDIDATE_FIELDS),
        *_targeted_candidate_values(
            data,
            DATA_ENRICHMENT_SIZE_CANDIDATE_TARGETS,
            *DATA_ENRICHMENT_SIZE_CANDIDATE_SOURCES,
        ),
    ]
    category_supports_size = (
        _category_supports_attribute(category_match, "size")
        if category_match
        # With no taxonomy match, only assume size support when category text is absent.
        else not clean_text(data.get("category") or data.get("product_type"))
    )
    if not values and not category_supports_size:
        return None, None
    normalized: list[str] = []
    seen: set[str] = set()
    detected_system = None
    for value in _split_values(values):
        cleaned = clean_text(value).strip()
        if not cleaned:
            continue
        if not _plausible_size_value(
            cleaned,
            aliases=aliases,
            systems=systems,
            require_strong=not category_supports_size,
        ):
            continue
        canonical = aliases.get(
            cleaned.casefold(), cleaned.upper() if len(cleaned) <= 4 else cleaned
        )
        key = canonical.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(canonical)
        if detected_system is None:
            detected_system = _detect_size_system(canonical, systems)
    return (normalized or None), detected_system


def _plausible_size_value(
    value: str,
    *,
    aliases: dict[str, str],
    systems: dict[str, set[str]],
    require_strong: bool = False,
) -> bool:
    normalized = clean_text(value).casefold()
    if normalized in aliases:
        return True
    if require_strong and not re.search(r"[a-z]", normalized):
        return False
    if any(normalized in values for values in systems.values()):
        return True
    if require_strong:
        return False
    return bool(re.fullmatch(r"\d+(?:\.\d+)?(?:\s*(?:m|t|w|y|us|uk|eu))?", normalized))


def _category_supports_attribute(
    category_match: dict[str, object],
    attribute_handle: str,
) -> bool:
    taxonomy_reference = _object_dict(category_match.get("taxonomy_reference"))
    handles = {
        str(item).replace("-", "_")
        for item in _object_list(taxonomy_reference.get("attribute_handles"))
        if str(item or "").strip()
    }
    return str(attribute_handle or "").replace("-", "_") in handles


def _detect_size_system(value: str, systems: dict[str, set[str]]) -> str | None:
    normalized = clean_text(value).casefold()
    for system, values in systems.items():
        if normalized in values:
            return system
    return None


def _normalize_materials(
    data: dict[str, object], *, terms: dict[str, object]
) -> list[str] | None:
    material_terms = term_dict(terms, "material_terms")
    found: list[str] = []
    seen: set[str] = set()
    values = _candidate_values(data, *DATA_ENRICHMENT_MATERIAL_PRIMARY_FIELDS)
    fallback_values = _candidate_values(data, *DATA_ENRICHMENT_MATERIAL_FALLBACK_FIELDS)
    for value in [*values, *fallback_values]:
        lowered = _strip_material_context_noise(
            clean_text(strip_html_tags(value)).casefold()
        )
        for canonical, tokens in material_terms.items():
            if canonical in seen:
                continue
            if isinstance(tokens, list) and any(
                _term_present(lowered, token) for token in tokens
            ):
                found.append(str(canonical))
                seen.add(str(canonical))
    return found or None


def _compiled_material_strip_patterns() -> tuple[re.Pattern[str], ...]:
    compiled: list[re.Pattern[str]] = []
    for pattern in tuple(DATA_ENRICHMENT_MATERIAL_CONTEXT_STRIP_PATTERNS or ()):
        try:
            compiled.append(re.compile(str(pattern), re.I))
        except re.error:
            logger.warning("Skipping invalid material strip pattern: %r", pattern)
    return tuple(compiled)


def _material_strip_patterns() -> tuple[re.Pattern[str], ...]:
    return _compiled_material_strip_patterns()


def _strip_material_context_noise(value: str) -> str:
    cleaned = value
    for pattern in _material_strip_patterns():
        cleaned = pattern.sub("", cleaned)
    return clean_text(cleaned)


def _normalize_from_terms(values: list[object], terms: dict[str, object]) -> str | None:
    for value in values:
        lowered = clean_text(value).casefold()
        if not lowered:
            continue
        if lowered in terms and not isinstance(terms[lowered], list):
            return str(terms[lowered])
        for canonical, tokens in terms.items():
            if isinstance(tokens, str):
                if _term_present(lowered, canonical) or _term_present(lowered, tokens):
                    return tokens
            elif isinstance(tokens, list):
                canonical_text = clean_text(canonical).casefold().replace(" ", "_")
                lowered_key = lowered.replace(" ", "_")
                if canonical_text == lowered_key or any(
                    _term_present(lowered, token) for token in tokens
                ):
                    return str(canonical)
    return None


def _top_taxonomy_candidates(
    data: dict[str, object], *, limit: int | None = None
) -> list[dict[str, object]]:
    if limit is None:
        limit = data_enrichment_settings.llm_taxonomy_hint_count
    return top_taxonomy_candidates(
        data,
        load_taxonomy_index(data_enrichment_settings.taxonomy_path),
        category_match_threshold=data_enrichment_settings.category_match_threshold,
        limit=limit,
        candidate_values=_category_match_values(data),
        candidate_value_loader=_candidate_values,
    )


def _match_category_path(data: dict[str, object]) -> dict[str, object] | None:
    candidates = _top_taxonomy_candidates(data, limit=1)
    return candidates[0] if candidates else None


def _category_match_values(data: dict[str, object]) -> list[object]:
    values: list[object] = []
    for key in ("category", "product_type", "title"):
        value = _first_present(data, key)
        if value in (None, "", [], {}):
            continue
        values.append(value)
    return values


def _missing_llm_backfill_fields(product: EnrichedProduct) -> list[str]:
    rows: list[str] = []
    for field_name in DATA_ENRICHMENT_LLM_BACKFILL_FIELDS:
        if getattr(product, field_name) in (None, "", [], {}):
            rows.append(str(field_name))
    return rows


def _build_seo_keywords(
    data: dict[str, object],
    *,
    color_family: str | None,
    size_values: list[str] | None,
    gender: str | None,
    materials: list[str] | None,
    category_path: str | None,
) -> list[str] | None:
    stopwords = {
        str(item).casefold()
        for item in _object_list(
            repository_terms(_load_attribute_repository()).get("seo_stopwords")
        )
    }
    raw_parts = [
        data.get("title"),
        data.get("brand"),
        data.get("category"),
        data.get("product_type"),
        color_family,
        gender,
        category_path,
        *(size_values or []),
        *(materials or []),
    ]
    keywords: list[str] = []
    seen: set[str] = set()
    title_tokens = _keyword_tokens(data.get("title"), stopwords)
    unigram_tokens = _keyword_tokens(
        " ".join(clean_text(part) for part in raw_parts), stopwords
    )
    for token in [
        *unigram_tokens,
        *_semantic_bigrams(title_tokens, set(unigram_tokens)),
    ]:
        cleaned = clean_text(token).casefold()
        if len(cleaned) < 3 or cleaned in stopwords or cleaned in seen:
            continue
        seen.add(cleaned)
        keywords.append(cleaned)
        if len(keywords) >= data_enrichment_settings.max_seo_keywords:
            break
    return keywords or None


def _semantic_bigrams(tokens: list[str], unigrams: set[str]) -> list[str]:
    phrases: list[str] = []
    seen: set[str] = set()
    for index in range(len(tokens) - 1):
        first = tokens[index]
        second = tokens[index + 1]
        if first not in unigrams or second not in unigrams:
            continue
        phrase = clean_text(f"{first} {second}").casefold()
        if not phrase or phrase in seen:
            continue
        seen.add(phrase)
        phrases.append(phrase)
    return phrases


def _llm_prompt_context(
    source_data: dict[str, object],
    *,
    product: EnrichedProduct,
    category_candidates: list[dict[str, object]],
) -> dict[str, object]:
    description = clean_text(strip_html_tags(source_data.get("description")))
    category_anchor = product.category_path or text_or_none(
        category_candidates[0].get("category_path") if category_candidates else None
    )
    context = _without_empty(
        {
            "title": clean_text(source_data.get("title")),
            "brand": clean_text(source_data.get("brand")),
            "category": clean_text(source_data.get("category")),
            "product_type": clean_text(source_data.get("product_type")),
            "price_normalized": product.price_normalized,
            "color_family": product.color_family,
            "size_normalized": product.size_normalized,
            "size_system": product.size_system,
            "gender_normalized": product.gender_normalized,
            "materials_normalized": product.materials_normalized,
            "availability_normalized": product.availability_normalized,
            "seo_keywords": product.seo_keywords,
            "category_path": product.category_path,
            "taxonomy_version": DATA_ENRICHMENT_TAXONOMY_VERSION,
            "missing_backfill_fields": _missing_llm_backfill_fields(product),
            "taxonomy_candidates": [
                _without_empty(
                    {
                        "category_id": candidate.get("category_id"),
                        "category_path": candidate.get("category_path"),
                        "score": candidate.get("score"),
                    }
                )
                for candidate in category_candidates[
                    : data_enrichment_settings.llm_taxonomy_hint_count
                ]
            ],
            "category_attributes": _category_attribute_handles(category_anchor),
        }
    )
    if description:
        context["description_excerpt"] = description[
            : data_enrichment_settings.llm_description_excerpt_chars
        ]
    return context


def _taxonomy_hint(
    category_path: str | None,
    *,
    category_candidates: list[dict[str, object]],
    missing_fields: list[str],
) -> str:
    if category_path:
        return (
            f"Use Shopify taxonomy version {DATA_ENRICHMENT_TAXONOMY_VERSION}. "
            f"Current deterministic category is {category_path}. "
            f"Only fill missing fields: {', '.join(missing_fields) or 'none'}."
        )
    candidate_paths = ", ".join(
        str(item.get("category_path") or "")
        for item in category_candidates[
            : data_enrichment_settings.llm_taxonomy_hint_count
        ]
        if str(item.get("category_path") or "").strip()
    )
    if candidate_paths:
        return (
            f"Use Shopify taxonomy version {DATA_ENRICHMENT_TAXONOMY_VERSION}. "
            f"Prefer one of these candidates when supported by evidence: {candidate_paths}. "
            f"Only fill missing fields: {', '.join(missing_fields) or 'none'}."
        )
    return (
        f"Use Shopify taxonomy version {DATA_ENRICHMENT_TAXONOMY_VERSION}. "
        f"Return only real Shopify category paths. "
        f"Only fill missing fields: {', '.join(missing_fields) or 'none'}."
    )


def _source_record_ids(payload: dict[str, object]) -> list[int]:
    ids = _int_list(payload.get("source_record_ids"))
    source_records = payload.get("source_records")
    if isinstance(source_records, list):
        for item in source_records:
            if isinstance(item, dict):
                record_id = _as_int(item.get("id"))
                if record_id is not None:
                    ids.append(record_id)
    return list(dict.fromkeys(ids))


def _normalized_options(value: object) -> dict[str, object]:
    raw = dict(value or {}) if isinstance(value, dict) else {}
    return {
        "max_source_records": _bounded_int(
            raw.get("max_source_records"),
            data_enrichment_settings.max_source_records,
            ceiling=data_enrichment_settings.max_source_records,
        ),
        "llm_enabled": bool(raw.get("llm_enabled", False)),
        "taxonomy_path": str(data_enrichment_settings.taxonomy_path),
        "attributes_path": str(data_enrichment_settings.attributes_path),
        "taxonomy_version": DATA_ENRICHMENT_TAXONOMY_VERSION,
        "max_concurrency": data_enrichment_settings.max_concurrency,
    }


def _option_int(options: dict[str, object], key: str) -> int:
    return _bounded_int(
        options.get(key),
        data_enrichment_settings.max_source_records,
        ceiling=data_enrichment_settings.max_source_records,
    )


def _clear_enriched_fields(product: EnrichedProduct) -> None:
    for field_name in (
        "price_normalized",
        "color_family",
        "size_normalized",
        "size_system",
        "gender_normalized",
        "materials_normalized",
        "availability_normalized",
        "seo_keywords",
        "category_path",
        "taxonomy_version",
        "intent_attributes",
        "audience",
        "style_tags",
        "ai_discovery_tags",
        "suggested_bundles",
    ):
        setattr(product, field_name, None)


def _product_attribute_diagnostics(
    data: dict[str, object],
    category_match: dict[str, object] | None,
) -> dict[str, object]:
    required = [str(item) for item in DATA_ENRICHMENT_BASE_REQUIRED_ATTRIBUTES]
    recommended: list[str] = []
    if category_match:
        taxonomy_reference = _object_dict(category_match.get("taxonomy_reference"))
        recommended.extend(
            str(item)
            for item in _object_list(taxonomy_reference.get("attribute_handles"))
            if str(item or "").strip()
        )
    attributes = [
        str(item) for item in [*required, *recommended] if str(item or "").strip()
    ]
    attributes = list(dict.fromkeys(attributes))
    present: list[str] = []
    missing: list[str] = []
    for attribute in attributes:
        if _product_attribute_value(data, attribute) in (None, "", [], {}):
            missing.append(attribute)
        else:
            present.append(attribute)
    return {
        "present_attributes": present,
        "null_attributes": missing,
        "required_attributes": required,
        "recommended_attributes": recommended,
    }


def _product_attribute_value(data: dict[str, object], attribute: str) -> object | None:
    keys = _attribute_lookup_keys(attribute)
    return _first_present(data, *keys)


def _attribute_lookup_keys(attribute: str) -> tuple[str, ...]:
    return attribute_lookup_keys(attribute)


def _category_attribute_handles(category_path: str | None) -> list[str]:
    return category_attribute_handles(
        category_path,
        load_taxonomy_index(data_enrichment_settings.taxonomy_path),
    )


def _candidate_values(data: dict[str, object], *keys: str) -> list[object]:
    # Keys come from config data-enrichment candidate field lists.
    values: list[object] = []
    for key in keys:
        value = data.get(key)
        if value in (None, "", [], {}):
            continue
        if isinstance(value, dict):
            values.extend(_flatten_dict_values(value))
        elif isinstance(value, list):
            values.extend(_flatten_list_values(value))
        else:
            values.append(value)
    return values


def _targeted_candidate_values(
    data: dict[str, object], target_keys: set[str], *keys: str
) -> list[object]:
    # Source and target keys come from config data-enrichment candidate maps.
    normalized_targets = {str(key).casefold() for key in target_keys}
    values: list[object] = []
    for key in keys:
        value = data.get(key)
        if value in (None, "", [], {}):
            continue
        if isinstance(value, dict):
            values.extend(_flatten_targeted_dict_values(value, normalized_targets))
        elif isinstance(value, list):
            values.extend(_flatten_targeted_list_values(value, normalized_targets))
        else:
            values.append(value)
    return values


def _flatten_dict_values(value: dict[str, object]) -> list[object]:
    values: list[object] = []
    for item in value.values():
        if isinstance(item, dict):
            values.extend(_flatten_dict_values(item))
        elif isinstance(item, list):
            values.extend(_flatten_list_values(item))
        else:
            values.append(item)
    return values


def _flatten_list_values(value: list[object]) -> list[object]:
    values: list[object] = []
    for item in value:
        if isinstance(item, dict):
            values.extend(_flatten_dict_values(item))
        elif isinstance(item, list):
            values.extend(_flatten_list_values(item))
        else:
            values.append(item)
    return values


def _flatten_targeted_dict_values(
    value: dict[str, object], target_keys: set[str]
) -> list[object]:
    values: list[object] = []
    for key, item in value.items():
        if str(key).casefold() in target_keys and item not in (None, "", [], {}):
            if isinstance(item, dict):
                values.extend(_flatten_dict_values(item))
            elif isinstance(item, list):
                values.extend(_flatten_list_values(item))
            else:
                values.append(item)
            continue
        if isinstance(item, dict):
            values.extend(_flatten_targeted_dict_values(item, target_keys))
        elif isinstance(item, list):
            values.extend(_flatten_targeted_list_values(item, target_keys))
    return values


def _flatten_targeted_list_values(
    value: list[object], target_keys: set[str]
) -> list[object]:
    values: list[object] = []
    for item in value:
        if isinstance(item, dict):
            values.extend(_flatten_targeted_dict_values(item, target_keys))
        elif isinstance(item, list):
            values.extend(_flatten_targeted_list_values(item, target_keys))
    return values


def _split_values(values: list[object]) -> list[str]:
    rows: list[str] = []
    for value in values:
        text = clean_text(value)
        if not text:
            continue
        rows.extend(
            clean_text(part) for part in re.split(r"[,/|]", text) if clean_text(part)
        )
    return rows


def _tokens(value: object) -> list[str]:
    return [
        token
        for token in _token_re.findall(clean_text(strip_html_tags(value)).casefold())
        if token
    ]


def _keyword_tokens(value: object, stopwords: set[str]) -> list[str]:
    return [
        token for token in _tokens(value) if len(token) >= 3 and token not in stopwords
    ]


def _term_present(text: str, term: object) -> bool:
    normalized = clean_text(term).casefold()
    if not normalized:
        return False
    return (
        re.search(rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])", text)
        is not None
    )


def _decimal_text(value: object) -> Decimal | None:
    normalized = normalize_decimal_price(value)
    if normalized is None:
        normalized = normalize_decimal_price(value, interpret_integral_as_cents=False)
    if normalized is None:
        return None
    try:
        return Decimal(normalized)
    except (InvalidOperation, ValueError):
        return None


def _first_present(data: dict[str, object], *keys: str) -> object | None:
    for key in keys:
        value = data.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _without_empty(value: dict[str, object]) -> dict[str, object]:
    return {key: item for key, item in value.items() if item not in (None, "", [], {})}


def _object_dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _object_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _string_list(value: object, *, max_items: int, max_chars: int) -> list[str]:
    if not isinstance(value, list):
        return []
    rows: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = clean_text(item)[:max_chars]
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        rows.append(text)
        if len(rows) >= max_items:
            break
    return rows


def _bounded_int(value: object, default: int, *, ceiling: int) -> int:
    try:
        parsed = int(value) if isinstance(value, (int, float)) else int(str(value))
    except (TypeError, ValueError):
        parsed = int(default)
    return min(max(1, parsed), int(ceiling))


def _int_list(value: object) -> list[int]:
    if not isinstance(value, list):
        return []
    return [parsed for item in value if (parsed := _as_int(item)) is not None]


def _as_int(value: object) -> int | None:
    try:
        parsed = int(value) if isinstance(value, (int, float)) else int(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


@lru_cache(maxsize=1)
def _load_attribute_repository() -> dict[str, object]:
    return load_attribute_repository_data(data_enrichment_settings.attributes_path)


@lru_cache(maxsize=1)
def _load_taxonomy_index():
    return load_taxonomy_index(data_enrichment_settings.taxonomy_path)
