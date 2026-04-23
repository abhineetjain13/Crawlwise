from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionLocal
from app.models.crawl import HostProtectionMemory
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.domain_utils import normalize_host


@dataclass(slots=True)
class HostProtectionPolicy:
    host: str
    prefer_browser: bool = False
    prefer_proxy: bool = False
    last_block_vendor: str | None = None
    hard_block_count: int = 0


def _now() -> datetime:
    return datetime.now(UTC)


def _ttl_delta() -> timedelta:
    return timedelta(
        seconds=max(1, int(crawler_runtime_settings.pacing_host_cache_ttl_seconds))
    )


def _is_recent(value: datetime | None, *, now: datetime) -> bool:
    if value is None:
        return False
    return value >= now - _ttl_delta()


def _coerce_method(value: object) -> str:
    return str(value or "").strip().lower()


async def load_host_protection_policy(
    value: str | None,
    *,
    session: AsyncSession | None = None,
) -> HostProtectionPolicy:
    normalized = normalize_host(value or "")
    if not normalized:
        return HostProtectionPolicy(host="")
    if session is None:
        async with SessionLocal() as owned_session:
            return await load_host_protection_policy(normalized, session=owned_session)
    row = await _load_row(session, host=normalized)
    if row is None:
        return HostProtectionPolicy(host=normalized)
    now = _now()
    return HostProtectionPolicy(
        host=normalized,
        prefer_browser=bool(row.browser_first_until and row.browser_first_until > now),
        prefer_proxy=bool(row.proxy_required_until and row.proxy_required_until > now),
        last_block_vendor=str(row.last_block_vendor or "").strip() or None,
        hard_block_count=int(row.hard_block_count or 0),
    )


async def note_host_hard_block(
    value: str | None,
    *,
    method: str,
    vendor: str | None = None,
    status_code: int | None = None,
    session: AsyncSession | None = None,
) -> HostProtectionPolicy:
    normalized = normalize_host(value or "")
    if not normalized:
        return HostProtectionPolicy(host="")
    if session is None:
        async with SessionLocal() as owned_session:
            policy = await note_host_hard_block(
                normalized,
                method=method,
                vendor=vendor,
                status_code=status_code,
                session=owned_session,
            )
            await owned_session.commit()
            return policy
    row = await _ensure_row(session, host=normalized)
    if row is None:
        return HostProtectionPolicy(host=normalized)
    now = _now()
    if not _is_recent(row.last_blocked_at, now=now):
        row.hard_block_count = 0
        row.browser_first_until = None
        row.proxy_required_until = None
    row.hard_block_count = int(row.hard_block_count or 0) + 1
    row.last_block_vendor = str(vendor or "").strip() or None
    row.last_block_status_code = int(status_code) if status_code is not None else None
    row.last_block_method = _coerce_method(method) or None
    row.last_blocked_at = now
    threshold = max(
        1,
        int(getattr(crawler_runtime_settings, "browser_first_host_block_threshold", 2)),
    )
    if row.last_block_method != "browser":
        if row.last_block_vendor:
            row.browser_first_until = now + _ttl_delta()
        elif row.hard_block_count >= threshold:
            row.browser_first_until = now + _ttl_delta()
    await session.flush()
    return await load_host_protection_policy(normalized, session=session)


async def note_host_usable_fetch(
    value: str | None,
    *,
    session: AsyncSession | None = None,
) -> HostProtectionPolicy:
    normalized = normalize_host(value or "")
    if not normalized:
        return HostProtectionPolicy(host="")
    if session is None:
        async with SessionLocal() as owned_session:
            policy = await note_host_usable_fetch(normalized, session=owned_session)
            await owned_session.commit()
            return policy
    row = await _load_row(session, host=normalized)
    if row is None:
        return HostProtectionPolicy(host=normalized)
    now = _now()
    row.last_success_at = now
    if not (
        row.browser_first_until is not None
        and row.browser_first_until > now
        and int(row.hard_block_count or 0) > 0
    ):
        row.browser_first_until = None
        row.hard_block_count = 0
    await session.flush()
    return await load_host_protection_policy(normalized, session=session)


async def reset_host_protection_memory(
    *,
    session: AsyncSession | None = None,
) -> None:
    if session is None:
        async with SessionLocal() as owned_session:
            await reset_host_protection_memory(session=owned_session)
            await owned_session.commit()
            return
    try:
        await session.execute(delete(HostProtectionMemory))
        await session.flush()
    except (OperationalError, ProgrammingError) as exc:
        if "host_protection_memory" not in str(exc).lower():
            raise
        await session.rollback()
        return


async def _load_row(
    session: AsyncSession,
    *,
    host: str,
) -> HostProtectionMemory | None:
    try:
        result = await session.execute(
            select(HostProtectionMemory)
            .where(HostProtectionMemory.host == host)
            .order_by(HostProtectionMemory.updated_at.desc(), HostProtectionMemory.id.desc())
            .limit(1)
        )
    except (OperationalError, ProgrammingError) as exc:
        if "host_protection_memory" not in str(exc).lower():
            raise
        await session.rollback()
        return None
    return result.scalar_one_or_none()


async def _ensure_row(
    session: AsyncSession,
    *,
    host: str,
) -> HostProtectionMemory | None:
    row = await _load_row(session, host=host)
    if row is not None:
        return row
    row = HostProtectionMemory(host=host)
    session.add(row)
    try:
        await session.flush()
    except (OperationalError, ProgrammingError) as exc:
        if "host_protection_memory" not in str(exc).lower():
            raise
        await session.rollback()
        return None
    return row
