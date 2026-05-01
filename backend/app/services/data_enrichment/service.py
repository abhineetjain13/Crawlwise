from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionLocal
from app.models.crawl import CrawlRecord, CrawlRun, DataEnrichmentJob, EnrichedProduct
from app.models.user import User
from app.services.config.data_enrichment import (
    DATA_ENRICHMENT_LLM_TASK,
    DATA_ENRICHMENT_SKIP_RECORD_STATUSES,
    DATA_ENRICHMENT_STATUS_DEGRADED,
    DATA_ENRICHMENT_STATUS_ENRICHED,
    DATA_ENRICHMENT_STATUS_FAILED,
    DATA_ENRICHMENT_STATUS_PENDING,
    DATA_ENRICHMENT_STATUS_RUNNING,
    ECOMMERCE_DETAIL_SURFACE,
    data_enrichment_settings,
)
from app.services.crawl_access_service import (
    require_accessible_record,
    require_accessible_run,
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
        (int(product.id), int(product.source_record_id)) for product in products
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
                job = await session.get(DataEnrichmentJob, job_id)
                product = await session.get(EnrichedProduct, product_id)
                record = await session.get(CrawlRecord, record_id)
                if job is None or product is None or record is None:
                    raise
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
    category_match = deterministic.pop("_category_match", None)
    product_attributes = deterministic.pop("_product_attributes", None)
    for key, value in deterministic.items():
        setattr(product, key, value)
    diagnostics: dict[str, object] = {
        "deterministic": True,
        "llm_requested": llm_enabled,
        "category_source": "deterministic" if product.category_path else "",
        "product_category": category_match or {},
        "product_attributes": product_attributes or {},
    }
    if llm_enabled:
        llm_result = await _run_llm_enrichment(
            session,
            job=job,
            record=record,
            product=product,
            source_data=data,
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
    terms = _repository_terms(repository)
    color_family = _normalize_from_terms(
        [
            *_candidate_values(
                data,
                "color",
                "title",
                "category",
                "product_type",
            ),
            *_targeted_candidate_values(
                data,
                {"color", "colour", "shade", "finish", "tone"},
                "variant_axes",
                "selected_variant",
            ),
        ],
        _term_dict(terms, "color_families"),
    )
    size_normalized, size_system = _normalize_sizes(data, terms=terms)
    gender_normalized = _normalize_from_terms(
        _candidate_values(data, "gender", "category", "product_type", "title"),
        _term_dict(terms, "gender_terms"),
    )
    materials_normalized = _normalize_materials(data, terms=terms)
    availability_normalized = _normalize_from_terms(
        [
            *_candidate_values(data, "availability", "product_attributes"),
            *_targeted_candidate_values(
                data,
                {"availability", "stock", "status", "inventory"},
                "variants",
                "selected_variant",
            ),
        ],
        _term_dict(terms, "availability_terms"),
    )
    category_match = _match_category_path(data)
    category_path = category_match.get("category_path") if category_match else None
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
        "_category_match": category_match,
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
) -> dict[str, object]:
    prompt_context = _llm_prompt_context(source_data, product=product)
    result = await run_prompt_task(
        session,
        task_type=DATA_ENRICHMENT_LLM_TASK,
        run_id=record.run_id,
        domain=source_domain(record.source_url),
        variables={
            "product_json": prompt_context,
            "taxonomy_hint": _taxonomy_hint(product.category_path),
        },
    )
    if result.error_message:
        return {
            "applied": False,
            "error": result.error_message,
            "error_category": str(result.error_category or ""),
        }
    payload = result.payload if isinstance(result.payload, dict) else {}
    category_applied = _apply_llm_payload(product, payload)
    return {
        "applied": bool(payload),
        "category_applied": category_applied,
        "provider": result.provider or "",
        "model": result.model or "",
    }


def _apply_llm_payload(product: EnrichedProduct, payload: dict[str, object]) -> bool:
    category_path = text_or_none(payload.get("category_path"))
    category_applied = False
    if category_path:
        product.category_path = category_path
        category_applied = True
    for field_name in (
        "intent_attributes",
        "audience",
        "style_tags",
        "ai_discovery_tags",
        "suggested_bundles",
    ):
        values = _string_list(payload.get(field_name), max_items=10, max_chars=60)
        setattr(product, field_name, values or None)
    return category_applied


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
    data: dict[str, object], *, terms: dict[str, object]
) -> tuple[list[str] | None, str | None]:
    size_config = _term_dict(terms, "size_systems")
    aliases = {
        str(k).casefold(): str(v)
        for k, v in dict(size_config.get("aliases") or {}).items()
    }
    systems = {
        str(system): {str(item).casefold() for item in list(values or [])}
        for system, values in dict(size_config.get("systems") or {}).items()
        if isinstance(values, list)
    }
    values = [
        *_candidate_values(data, "size", "available_sizes"),
        *_targeted_candidate_values(
            data,
            {"size", "width"},
            "variant_axes",
            "selected_variant",
        ),
    ]
    normalized: list[str] = []
    seen: set[str] = set()
    detected_system = None
    for value in _split_values(values):
        cleaned = clean_text(value).strip()
        if not cleaned:
            continue
        if not _plausible_size_value(cleaned, aliases=aliases, systems=systems):
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
) -> bool:
    normalized = clean_text(value).casefold()
    if normalized in aliases:
        return True
    if any(normalized in values for values in systems.values()):
        return True
    return bool(re.fullmatch(r"\d+(?:\.\d+)?(?:\s*(?:m|t|w|y|us|uk|eu))?", normalized))


def _detect_size_system(value: str, systems: dict[str, set[str]]) -> str | None:
    normalized = clean_text(value).casefold()
    for system, values in systems.items():
        if normalized in values:
            return system
    return None


def _normalize_materials(
    data: dict[str, object], *, terms: dict[str, object]
) -> list[str] | None:
    material_terms = _term_dict(terms, "material_terms")
    found: list[str] = []
    seen: set[str] = set()
    for value in _candidate_values(
        data, "materials", "product_attributes", "description", "title"
    ):
        lowered = clean_text(strip_html_tags(value)).casefold()
        for canonical, tokens in material_terms.items():
            if canonical in seen:
                continue
            if any(_term_present(lowered, token) for token in list(tokens or [])):
                found.append(str(canonical))
                seen.add(str(canonical))
    return found or None


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
            elif any(_term_present(lowered, token) for token in list(tokens or [])):
                return str(canonical)
    return None


def _match_category_path(data: dict[str, object]) -> dict[str, object] | None:
    raw_category = _first_present(data, "category", "product_type")
    category_path = _source_category_path(raw_category, title=data.get("title"))
    if not category_path:
        return None
    match = {
        "category_id": "",
        "category_path": category_path,
        "score": 1.0,
        "source": "source_category",
    }
    gpc_reference = _gpc_reference_for_category(category_path)
    if gpc_reference:
        match["gpc_reference"] = gpc_reference
    return match


def _exact_category_match(
    values: list[object],
    categories: list[dict[str, object]],
    normalized_lookup: dict[str, dict[str, object]],
    scores: tuple[float, float, float],
) -> dict[str, object] | None:
    for value in values:
        normalized = _normalize_category_path(clean_text(value))
        if normalized in normalized_lookup:
            return _category_match_payload(
                normalized_lookup[normalized], score=scores[0], source="exact_path"
            )
        if not normalized:
            continue
        for item in categories:
            path = str(item.get("category_path") or "")
            leaf = _normalize_category_path(path.rsplit(">", 1)[-1])
            if normalized == leaf:
                return _category_match_payload(item, score=scores[1], source="leaf")
            aliases = [
                _normalize_category_path(alias)
                for alias in list(item.get("aliases") or [])
            ]
            if normalized in aliases:
                return _category_match_payload(item, score=scores[2], source="alias")
    return None


def _source_category_path(value: object, *, title: object) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    if _normalize_category_path(text) == _normalize_category_path(title):
        return None
    parts = [
        clean_text(part)
        for part in re.split(r"\s*>\s*", text)
        if clean_text(part)
    ]
    return " > ".join(parts) if parts else None


def _gpc_reference_for_category(category_path: str) -> dict[str, object] | None:
    categories = _load_taxonomy()
    if not categories:
        return None
    normalized_lookup = {
        _normalize_category_path(path): item
        for item in categories
        if isinstance(item, dict)
        for path in [item.get("category_path")]
        if path
    }
    return _exact_category_match(
        [category_path], categories, normalized_lookup, (1.0, 0.9, 0.86)
    )


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
        for item in list(
            _repository_terms(_load_attribute_repository()).get("seo_stopwords") or []
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
    for token in [
        *_keyword_tokens(" ".join(clean_text(part) for part in raw_parts), stopwords),
        *list(_bigrams(title_tokens)),
    ]:
        cleaned = clean_text(token).casefold()
        if len(cleaned) < 3 or cleaned in stopwords or cleaned in seen:
            continue
        seen.add(cleaned)
        keywords.append(cleaned)
        if len(keywords) >= data_enrichment_settings.max_seo_keywords:
            break
    return keywords or None


def _llm_prompt_context(
    source_data: dict[str, object], *, product: EnrichedProduct
) -> dict[str, object]:
    description = clean_text(strip_html_tags(source_data.get("description")))
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
        }
    )
    if description:
        context["description_excerpt"] = description[
            : data_enrichment_settings.llm_description_excerpt_chars
        ]
    return context


def _taxonomy_hint(category_path: str | None) -> str:
    if category_path:
        return f"Existing source category: {category_path}"
    return "Infer a plain ecommerce category path only if product evidence is strong."


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
    repository = _load_attribute_repository()
    rules = dict(repository.get("attribute_rules") or {})
    required = [str(item) for item in list(rules.get("base_required") or [])]
    recommended = [str(item) for item in list(rules.get("base_recommended") or [])]
    if category_match:
        category_rules = dict(rules.get("category_rules") or {})
        gpc_reference = category_match.get("gpc_reference")
        path = str(
            dict(gpc_reference).get("category_path")
            if isinstance(gpc_reference, dict)
            else category_match.get("category_path") or ""
        )
        matched_keys = [
            key
            for key in category_rules
            if _normalize_category_path(key)
            and _normalize_category_path(key) in _normalize_category_path(path)
        ]
        for key in matched_keys:
            rule = dict(category_rules.get(key) or {})
            required.extend(str(item) for item in list(rule.get("required") or []))
            recommended.extend(
                str(item) for item in list(rule.get("recommended") or [])
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
    attributes = dict(_load_attribute_repository().get("attributes") or {})
    config = dict(attributes.get(attribute) or {})
    keys = tuple(str(item) for item in list(config.get("crawl_fields") or [])) or (
        attribute,
    )
    return _first_present(data, *keys)


def _category_match_payload(
    item: dict[str, object], *, score: float, source: str
) -> dict[str, object]:
    return {
        "category_id": item.get("category_id") or "",
        "category_path": item.get("category_path") or "",
        "score": round(float(score), 3),
        "source": source,
    }


def _candidate_values(data: dict[str, object], *keys: str) -> list[object]:
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
        token
        for token in _tokens(value)
        if len(token) >= 3 and token not in stopwords
    ]


def _bigrams(tokens: list[str]):
    for index in range(len(tokens) - 1):
        yield f"{tokens[index]} {tokens[index + 1]}"


def _term_present(text: str, term: object) -> bool:
    normalized = clean_text(term).casefold()
    if not normalized:
        return False
    return (
        re.search(rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])", text)
        is not None
    )


def _normalize_category_path(value: object) -> str:
    return " > ".join(
        " ".join(_tokens(part))
        for part in clean_text(value).split(">")
        if _tokens(part)
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


@lru_cache(maxsize=16)
def _load_json_dict(path: Path) -> dict[str, object]:
    with Path(path).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Data enrichment JSON must be an object: {path}")
    return payload


@lru_cache(maxsize=1)
def _load_attribute_repository() -> dict[str, object]:
    return _load_json_dict(data_enrichment_settings.attributes_path)


def _repository_terms(repository: dict[str, object]) -> dict[str, object]:
    terms = repository.get("normalization_terms")
    return dict(terms) if isinstance(terms, dict) else {}


def _term_dict(terms: dict[str, object], key: str) -> dict[str, object]:
    value = terms.get(key)
    return dict(value) if isinstance(value, dict) else {}


@lru_cache(maxsize=1)
def _load_taxonomy() -> tuple[dict[str, str], ...]:
    rows: list[dict[str, str]] = []
    with Path(data_enrichment_settings.taxonomy_path).open(
        "r", encoding="utf-8"
    ) as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            category_id = ""
            category_path = line
            match = re.match(r"^(\d+)\s+-\s+(.+)$", line)
            if match:
                category_id = match.group(1)
                category_path = match.group(2)
            rows.append({"category_id": category_id, "category_path": category_path})
    return tuple(rows)
