# Crawl run route handlers.
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Annotated, Any, NoReturn, cast

from app.core.database import SessionLocal
from app.core.dependencies import get_current_user, get_db
from app.core.security import decode_access_token
from app.models.crawl import CrawlRun, CrawlLog
from app.models.user import User
from app.schemas.common import LogEntryResponse, PaginatedResponse, PaginationMeta
from app.schemas.crawl import (
    CrawlCreate,
    DomainRecipePromoteSelectorsRequest,
    DomainRecipeResponse,
    DomainRunProfileLookupResponse,
    DomainRecipeSaveRunProfileRequest,
    CrawlRunResponse,
    FieldCommitRequest,
    FieldCommitResponse,
    LLMCommitRequest,
    LLMCommitResponse,
)
from app.services.crawl_access_service import (
    RUN_NOT_FOUND_DETAIL,
    user_can_access_run,
)
from app.services.crawl_crud import (
    commit_llm_suggestions,
    commit_selected_fields,
    delete_run,
    get_run,
    get_run_logs,
    list_runs,
)
from app.services.crawl_events import serialize_log_event
from app.services.crawl_ingestion_service import (
    create_crawl_run_from_csv,
    create_crawl_run_from_payload,
)
from app.services.crawl_service import kill_run, pause_run, resume_run
from app.services.crawl_state import TERMINAL_STATUSES
from app.services.domain_run_profile_service import load_domain_run_profile
from app.services.domain_utils import normalize_domain
from app.services.review import (
    build_domain_recipe_payload,
    promote_domain_recipe_selectors,
    save_domain_recipe_run_profile,
)
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.websockets import WebSocketState

router = APIRouter(prefix="/api/crawls", tags=["crawls"])

logger = logging.getLogger("app.api.crawls")

RUN_CONFLICT_DETAIL = "Run cannot be cancelled in its current state"
ResponseSpec = dict[int | str, dict[str, Any]]

RUN_NOT_FOUND_RESPONSE: ResponseSpec = {
    status.HTTP_404_NOT_FOUND: {"description": RUN_NOT_FOUND_DETAIL},
}
RUN_CONFLICT_RESPONSE: ResponseSpec = {
    **RUN_NOT_FOUND_RESPONSE,
    status.HTTP_409_CONFLICT: {"description": RUN_CONFLICT_DETAIL},
}


async def _resolve_websocket_user(websocket: WebSocket) -> User | None:
    token = websocket.cookies.get("access_token")
    if not token:
        auth_header = websocket.headers.get("authorization", "")
        scheme, _, credentials = auth_header.partition(" ")
        if scheme.lower() == "bearer" and credentials.strip():
            token = credentials.strip()
    if not token:
        return None
    try:
        payload = decode_access_token(token)
        user_id = int(payload["sub"])
        token_version = int(payload.get("ver", 0))
    except (JWTError, KeyError, ValueError):
        return None

    async with SessionLocal() as session:
        user = await session.get(User, user_id)
        if user is None or not user.is_active:
            return None
        user_token_version = user.token_version if user.token_version is not None else 0
        if user_token_version != token_version:
            return None
        return user


def _raise_http_from_value_error(*, status_code: int, exc: ValueError) -> NoReturn:
    """Translate validation/business ValueError into HTTPException preserving cause."""
    raise HTTPException(status_code=status_code, detail=str(exc)) from exc


async def _get_accessible_run_or_404(
    session: AsyncSession,
    *,
    run_id: int,
    user: User,
) -> CrawlRun:
    try:
        return await _require_accessible_run(session, run_id=run_id, user=user)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


async def _mutate_run_status(
    session: AsyncSession,
    *,
    run_id: int,
    user: User,
    action: Callable[[AsyncSession, CrawlRun], Any],
) -> dict[str, object]:
    run = await _get_accessible_run_or_404(session, run_id=run_id, user=user)
    try:
        updated = await action(session, run)
    except ValueError as exc:
        _raise_http_from_value_error(
            status_code=status.HTTP_409_CONFLICT,
            exc=exc,
        )
    return {"run_id": updated.id, "status": updated.status}


async def _close_websocket_safely(
    websocket: WebSocket, *, code: int, reason: str
) -> None:
    """Close before accept() would otherwise fail to deliver code/reason on some ASGI stacks."""
    if websocket.application_state == WebSocketState.CONNECTING:
        await websocket.accept()
    await websocket.close(code=code, reason=reason)


@router.post(
    "",
    responses={status.HTTP_400_BAD_REQUEST: {"description": "Invalid crawl request"}},
)
async def crawls_create(
    payload: CrawlCreate,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict:
    try:
        run = await create_crawl_run_from_payload(
            session, user.id, payload.model_dump()
        )
    except ValueError as exc:
        _raise_http_from_value_error(
            status_code=status.HTTP_400_BAD_REQUEST,
            exc=exc,
        )
    return {"run_id": run.id}


async def _mark_run_failed_with_retry(
    *,
    run_id: int,
    error_message: str,
    session_factory=SessionLocal,
) -> None:
    """Best-effort failure marking."""
    from app.models.crawl import CrawlRun
    from app.services.crawl_state import CrawlStatus, update_run_status

    async with session_factory() as error_session:
        failed_run = await error_session.get(CrawlRun, run_id)
        if failed_run is None:
            return
        if failed_run.status_value in TERMINAL_STATUSES:
            return
        update_run_status(failed_run, CrawlStatus.FAILED)
        failed_run.update_summary(
            error=str(error_message or "background_crawl_error"),
            extraction_verdict="error",
        )
        await error_session.commit()


async def _require_accessible_run(
    session: AsyncSession,
    *,
    run_id: int,
    user: User,
) -> CrawlRun:
    run = await get_run(session, run_id)
    if run is None or not user_can_access_run(user=user, run=run):
        raise ValueError(RUN_NOT_FOUND_DETAIL)
    return run


async def _load_log_stream_snapshot(
    *,
    run_id: int,
    after_id: int | None,
) -> tuple[list[CrawlLog], CrawlRun | None]:
    async with SessionLocal() as session:
        rows = await get_run_logs(session, run_id, after_id=after_id, limit=500)
        run = await get_run(session, run_id)
    return rows, run


@router.post(
    "/csv",
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": "Invalid CSV crawl request or no valid URLs found"
        }
    },
)
async def crawls_create_csv(
    file: Annotated[UploadFile, File(...)],
    surface: Annotated[str, Form(...)],
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    additional_fields: Annotated[str, Form()] = "",
    settings_json: Annotated[str, Form()] = "{}",
) -> dict:
    """Create a crawl run from an uploaded CSV file."""
    content = (await file.read()).decode("utf-8", errors="ignore")
    try:
        run, url_count = await create_crawl_run_from_csv(
            session,
            user.id,
            csv_content=content,
            surface=surface,
            additional_fields=additional_fields,
            settings_json=settings_json,
        )
    except ValueError as exc:
        _raise_http_from_value_error(
            status_code=status.HTTP_400_BAD_REQUEST,
            exc=exc,
        )
    return {"run_id": run.id, "url_count": url_count}


@router.get("/domain-run-profile")
async def crawls_domain_run_profile_lookup(
    url: str,
    surface: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    _user: Annotated[User, Depends(get_current_user)],
) -> DomainRunProfileLookupResponse:
    normalized_domain = normalize_domain(url)
    normalized_surface = str(surface or "").strip().lower()
    if not normalized_domain or not normalized_surface:
        return DomainRunProfileLookupResponse(
            domain=normalized_domain,
            surface=normalized_surface,
            saved_run_profile=None,
        )
    saved_profile = await load_domain_run_profile(
        session,
        domain=normalized_domain,
        surface=normalized_surface,
    )
    return DomainRunProfileLookupResponse(
        domain=normalized_domain,
        surface=normalized_surface,
        saved_run_profile=(
            dict(saved_profile.profile or {}) if saved_profile is not None else None
        ),
    )


@router.get("")
async def crawls_list(
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    run_type: str = "",
    status_value: Annotated[str, Query(alias="status")] = "",
    url_search: str = "",
) -> PaginatedResponse[CrawlRunResponse]:
    user_id = user.id if user.role != "admin" else None
    rows, total = await list_runs(
        session, page, limit, status_value, run_type, url_search, user_id=user_id
    )
    return PaginatedResponse(
        items=[
            CrawlRunResponse.model_validate(row, from_attributes=True) for row in rows
        ],
        meta=PaginationMeta(page=page, limit=limit, total=total),
    )


@router.get("/{run_id}", responses=RUN_NOT_FOUND_RESPONSE)
async def crawls_detail(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> CrawlRunResponse:
    try:
        run = await _require_accessible_run(session, run_id=run_id, user=user)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return CrawlRunResponse.model_validate(run, from_attributes=True)


@router.delete(
    "/{run_id}", status_code=status.HTTP_204_NO_CONTENT, responses=RUN_CONFLICT_RESPONSE
)
async def crawls_delete(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> None:
    try:
        run = await _require_accessible_run(session, run_id=run_id, user=user)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    try:
        await delete_run(session, run)
    except ValueError as exc:
        _raise_http_from_value_error(
            status_code=status.HTTP_409_CONFLICT,
            exc=exc,
        )


@router.post("/{run_id}/pause", responses=RUN_CONFLICT_RESPONSE)
async def crawls_pause(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict:
    return await _mutate_run_status(
        session,
        run_id=run_id,
        user=user,
        action=pause_run,
    )


@router.post("/{run_id}/llm-commit", responses=RUN_NOT_FOUND_RESPONSE)
async def crawls_llm_commit(
    run_id: int,
    payload: LLMCommitRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> LLMCommitResponse:
    run = await _get_accessible_run_or_404(session, run_id=run_id, user=user)
    updated_records, updated_fields = await commit_llm_suggestions(
        session,
        run=run,
        items=[item.model_dump() for item in payload.items],
    )
    return LLMCommitResponse(
        run_id=run.id, updated_records=updated_records, updated_fields=updated_fields
    )


@router.post("/{run_id}/commit-fields", responses=RUN_NOT_FOUND_RESPONSE)
async def crawls_commit_fields(
    run_id: int,
    payload: FieldCommitRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> FieldCommitResponse:
    run = await _get_accessible_run_or_404(session, run_id=run_id, user=user)
    updated_records, updated_fields = await commit_selected_fields(
        session,
        run=run,
        items=[item.model_dump() for item in payload.items],
    )
    return FieldCommitResponse(
        run_id=run.id, updated_records=updated_records, updated_fields=updated_fields
    )


@router.get("/{run_id}/domain-recipe", responses=RUN_NOT_FOUND_RESPONSE)
async def crawls_domain_recipe(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> DomainRecipeResponse:
    run = await _get_accessible_run_or_404(session, run_id=run_id, user=user)
    payload = await build_domain_recipe_payload(session, run=run)
    return DomainRecipeResponse.model_validate(payload)


@router.post("/{run_id}/domain-recipe/promote-selectors", responses=RUN_NOT_FOUND_RESPONSE)
async def crawls_promote_domain_recipe_selectors(
    run_id: int,
    payload: DomainRecipePromoteSelectorsRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> list[dict[str, object]]:
    run = await _get_accessible_run_or_404(session, run_id=run_id, user=user)
    return await promote_domain_recipe_selectors(
        session,
        run=run,
        selectors=[item.model_dump() for item in payload.selectors],
    )


@router.post("/{run_id}/domain-recipe/save-run-profile", responses=RUN_NOT_FOUND_RESPONSE)
async def crawls_save_domain_run_profile(
    run_id: int,
    payload: DomainRecipeSaveRunProfileRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, object]:
    run = await _get_accessible_run_or_404(session, run_id=run_id, user=user)
    return await save_domain_recipe_run_profile(
        session,
        run=run,
        profile=payload.profile.model_dump(),
    )


@router.post("/{run_id}/resume", responses=RUN_CONFLICT_RESPONSE)
async def crawls_resume(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict:
    return await _mutate_run_status(
        session,
        run_id=run_id,
        user=user,
        action=resume_run,
    )


@router.post(
    "/{run_id}/kill",
    responses=cast(ResponseSpec, {
        status.HTTP_404_NOT_FOUND: {"description": RUN_NOT_FOUND_DETAIL},
        status.HTTP_409_CONFLICT: {
            "description": "Run cannot be killed in its current state"
        },
    }),
)
async def crawls_kill(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict:
    return await _mutate_run_status(
        session,
        run_id=run_id,
        user=user,
        action=kill_run,
    )


@router.post(
    "/{run_id}/cancel",
    responses=cast(ResponseSpec, {
        status.HTTP_404_NOT_FOUND: {"description": RUN_NOT_FOUND_DETAIL},
        status.HTTP_409_CONFLICT: {"description": RUN_CONFLICT_DETAIL},
    }),
)
async def crawls_cancel(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict:
    return await crawls_kill(run_id, session, user)


@router.get("/{run_id}/logs", responses=RUN_NOT_FOUND_RESPONSE)
async def crawls_logs(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    after_id: int | None = None,
    limit: int = 500,
) -> list[LogEntryResponse]:
    try:
        await _require_accessible_run(session, run_id=run_id, user=user)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    safe_limit = max(1, min(limit, 2000))
    rows = await get_run_logs(session, run_id, after_id=after_id, limit=safe_limit)
    return [LogEntryResponse.model_validate(row, from_attributes=True) for row in rows]


@router.websocket("/{run_id}/logs/ws")
async def crawls_logs_ws(
    websocket: WebSocket, run_id: int, after_id: int | None = None
) -> None:
    user = await _resolve_websocket_user(websocket)
    if user is None:
        await _close_websocket_safely(websocket, code=1008, reason="Not authenticated")
        return

    async with SessionLocal() as session:
        try:
            run = await _require_accessible_run(session, run_id=run_id, user=user)
        except ValueError:
            await _close_websocket_safely(
                websocket, code=1008, reason=RUN_NOT_FOUND_DETAIL
            )
            return

        await websocket.accept()
        cursor = after_id
        try:
            while True:
                rows, next_run = await _load_log_stream_snapshot(
                    run_id=run_id,
                    after_id=cursor,
                )

                for row in rows:
                    await websocket.send_json(serialize_log_event(row))
                    cursor = row.id

                if next_run is None:
                    await websocket.close(code=1008, reason=RUN_NOT_FOUND_DETAIL)
                    return
                run = next_run
                if run.status_value in TERMINAL_STATUSES and not rows:
                    await websocket.close(code=1000, reason="Run completed")
                    return
                await asyncio.sleep(0.25)

        except WebSocketDisconnect:
            return
        except Exception as exc:
            logger.exception("Run logs websocket stream failed for run %s", run_id)
            try:
                await websocket.close(
                    code=1011, reason=f"stream_error: {type(exc).__name__}"
                )
            except Exception:
                logger.debug(
                    "Failed to close websocket after stream error", exc_info=True
                )
