# Crawl run route handlers.
from __future__ import annotations

import logging
from typing import Annotated, NoReturn

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    UploadFile,
    File,
    Form,
    status,
)
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionLocal
from app.core.dependencies import get_current_user, get_db
from app.core.security import decode_access_token
from app.models.crawl import CrawlLog
from app.models.user import User
from app.schemas.common import LogEntryResponse, PaginatedResponse, PaginationMeta
from app.schemas.crawl import (
    CrawlCreate,
    CrawlRunResponse,
    FieldCommitRequest,
    FieldCommitResponse,
    LLMCommitRequest,
    LLMCommitResponse,
)
from app.services.crawl_crud import (
    commit_llm_suggestions,
    commit_selected_fields,
    create_crawl_run,
    delete_run,
    get_run,
    get_run_logs,
    list_runs,
    parse_csv_urls,
)
from app.services.crawl_events import (
    serialize_log_event,
    serialize_run_snapshot,
)
from app.services.crawl_state import TERMINAL_STATUSES, normalize_status
from app.services.db_utils import with_retry
from app.services.crawl_service import (
    kill_run,
    pause_run,
    resume_run,
)

router = APIRouter(prefix="/api/crawls", tags=["crawls"])

logger = logging.getLogger("app.api.crawls")

RUN_NOT_FOUND_DETAIL = "Run not found"
RUN_CONFLICT_DETAIL = "Run cannot be cancelled in its current state"
RUN_NOT_FOUND_RESPONSE = {
    status.HTTP_404_NOT_FOUND: {"description": RUN_NOT_FOUND_DETAIL},
}
RUN_CONFLICT_RESPONSE = {
    **RUN_NOT_FOUND_RESPONSE,
    status.HTTP_409_CONFLICT: {"description": RUN_CONFLICT_DETAIL},
}


def _raise_http_from_value_error(
    *, status_code: int, exc: ValueError
) -> NoReturn:
    """Translate validation/business ValueError into HTTPException preserving cause."""
    raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.post(
    "",
    responses={status.HTTP_400_BAD_REQUEST: {"description": "Invalid crawl request"}},
)
async def crawls_create(
    payload: CrawlCreate,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict:
    data = payload.model_dump()
    # For batch runs, store URLs in settings so in-process runner can access them
    if payload.run_type == "batch" and payload.urls:
        data.setdefault("settings", {})["urls"] = payload.urls
    try:
        run = await create_crawl_run(session, user.id, data)
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
    """Best-effort failure marking that retries status + summary mutation together."""
    from app.models.crawl import CrawlRun
    from app.services.crawl_state import CrawlStatus, update_run_status

    async with session_factory() as error_session:
        async def _mutation(retry_session: AsyncSession) -> None:
            failed_run = await retry_session.get(CrawlRun, run_id)
            if failed_run is None:
                return
            if normalize_status(failed_run.status) in TERMINAL_STATUSES:
                return
            update_run_status(failed_run, CrawlStatus.FAILED)
            summary = dict(failed_run.result_summary or {})
            summary["error"] = str(error_message or "background_crawl_error")
            summary["extraction_verdict"] = "error"
            failed_run.result_summary = summary

        await with_retry(error_session, _mutation)


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
    import json

    content = (await file.read()).decode("utf-8", errors="ignore")
    urls = parse_csv_urls(content)
    if not urls:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No valid URLs found in CSV",
        )

    extra_fields = [f.strip() for f in additional_fields.split(",") if f.strip()]
    try:
        crawl_settings = json.loads(settings_json)
    except json.JSONDecodeError:
        crawl_settings = {}
    crawl_settings["csv_content"] = content

    data = {
        "run_type": "csv",
        "url": urls[0],
        "urls": urls,
        "surface": surface,
        "settings": crawl_settings,
        "additional_fields": extra_fields,
    }
    data["settings"]["urls"] = urls
    try:
        run = await create_crawl_run(session, user.id, data)
    except ValueError as exc:
        _raise_http_from_value_error(
            status_code=status.HTTP_400_BAD_REQUEST,
            exc=exc,
        )
    return {"run_id": run.id, "url_count": len(urls)}


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
    run = await get_run(session, run_id)
    if run is None or (user.role != "admin" and run.user_id != user.id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=RUN_NOT_FOUND_DETAIL
        )
    return CrawlRunResponse.model_validate(run, from_attributes=True)


@router.delete(
    "/{run_id}", status_code=status.HTTP_204_NO_CONTENT, responses=RUN_CONFLICT_RESPONSE
)
async def crawls_delete(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> None:
    run = await get_run(session, run_id)
    if run is None or (user.role != "admin" and run.user_id != user.id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=RUN_NOT_FOUND_DETAIL
        )
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
    run = await get_run(session, run_id)
    if run is None or (user.role != "admin" and run.user_id != user.id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=RUN_NOT_FOUND_DETAIL
        )
    try:
        updated = await pause_run(session, run)
    except ValueError as exc:
        _raise_http_from_value_error(
            status_code=status.HTTP_409_CONFLICT,
            exc=exc,
        )
    return {"run_id": updated.id, "status": updated.status}


@router.post("/{run_id}/llm-commit", responses=RUN_NOT_FOUND_RESPONSE)
async def crawls_llm_commit(
    run_id: int,
    payload: LLMCommitRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> LLMCommitResponse:
    run = await get_run(session, run_id)
    if run is None or (user.role != "admin" and run.user_id != user.id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=RUN_NOT_FOUND_DETAIL
        )
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
    run = await get_run(session, run_id)
    if run is None or (user.role != "admin" and run.user_id != user.id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=RUN_NOT_FOUND_DETAIL
        )
    updated_records, updated_fields = await commit_selected_fields(
        session,
        run=run,
        items=[item.model_dump() for item in payload.items],
    )
    return FieldCommitResponse(
        run_id=run.id, updated_records=updated_records, updated_fields=updated_fields
    )


@router.post("/{run_id}/resume", responses=RUN_CONFLICT_RESPONSE)
async def crawls_resume(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict:
    run = await get_run(session, run_id)
    if run is None or (user.role != "admin" and run.user_id != user.id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=RUN_NOT_FOUND_DETAIL
        )
    try:
        updated = await resume_run(session, run)
    except ValueError as exc:
        _raise_http_from_value_error(
            status_code=status.HTTP_409_CONFLICT,
            exc=exc,
        )
    return {"run_id": updated.id, "status": updated.status}


@router.post(
    "/{run_id}/kill",
    responses={
        status.HTTP_404_NOT_FOUND: {"description": RUN_NOT_FOUND_DETAIL},
        status.HTTP_409_CONFLICT: {
            "description": "Run cannot be killed in its current state"
        },
    },
)
async def crawls_kill(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict:
    run = await get_run(session, run_id)
    if run is None or (user.role != "admin" and run.user_id != user.id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=RUN_NOT_FOUND_DETAIL
        )
    try:
        updated = await kill_run(session, run)
    except ValueError as exc:
        _raise_http_from_value_error(
            status_code=status.HTTP_409_CONFLICT,
            exc=exc,
        )
    return {"run_id": updated.id, "status": updated.status}


@router.post(
    "/{run_id}/cancel",
    responses={
        status.HTTP_404_NOT_FOUND: {"description": RUN_NOT_FOUND_DETAIL},
        status.HTTP_409_CONFLICT: {"description": RUN_CONFLICT_DETAIL},
    },
)
async def crawls_cancel(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict:
    run = await get_run(session, run_id)
    if run is None or (user.role != "admin" and run.user_id != user.id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=RUN_NOT_FOUND_DETAIL
        )
    try:
        updated = await kill_run(session, run)
    except ValueError as exc:
        _raise_http_from_value_error(
            status_code=status.HTTP_409_CONFLICT,
            exc=exc,
        )
    return {"run_id": updated.id, "status": updated.status}


@router.get("/{run_id}/logs", responses=RUN_NOT_FOUND_RESPONSE)
async def crawls_logs(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> list[LogEntryResponse]:
    run = await get_run(session, run_id)
    if run is None or (user.role != "admin" and run.user_id != user.id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=RUN_NOT_FOUND_DETAIL
        )
    rows = await get_run_logs(session, run_id)
    return [LogEntryResponse.model_validate(row, from_attributes=True) for row in rows]
