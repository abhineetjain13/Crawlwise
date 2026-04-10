from __future__ import annotations

import json
import logging

from app.services.crawl_crud import create_crawl_run
from app.services.crawl_service import dispatch_run
from app.services.crawl_utils import parse_csv_urls
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def _parse_additional_fields(additional_fields: str) -> list[str]:
    return [field.strip() for field in additional_fields.split(",") if field.strip()]


def _parse_settings_json(settings_json: str) -> dict:
    try:
        parsed = json.loads(settings_json)
    except json.JSONDecodeError as exc:
        logger.debug(
            "_parse_settings_json failed to decode settings JSON",
            extra={"settings_json": settings_json},
            exc_info=exc,
        )
        raise ValueError("_parse_settings_json failed to decode settings JSON") from exc
    if not isinstance(parsed, dict):
        logger.debug(
            "_parse_settings_json expected a JSON object",
            extra={"parsed_type": type(parsed).__name__, "parsed_value": parsed},
        )
        raise ValueError(
            f"_parse_settings_json expected a JSON object, got {type(parsed).__name__}"
        )
    return parsed


def prepare_crawl_create_payload(payload: dict) -> dict:
    """Normalize crawl creation payloads before persistence."""
    data = dict(payload or {})
    if data.get("run_type") == "batch" and data.get("urls"):
        settings = dict(data.get("settings") or {})
        settings["urls"] = data.get("urls") or []
        data["settings"] = settings
    return data


def build_csv_crawl_payload(
    *,
    csv_content: str,
    surface: str,
    additional_fields: str = "",
    settings_json: str = "{}",
) -> tuple[dict, int]:
    urls = parse_csv_urls(csv_content)
    if not urls:
        raise ValueError("No valid URLs found in CSV")

    crawl_settings = _parse_settings_json(settings_json)
    crawl_settings["csv_content"] = csv_content
    crawl_settings["urls"] = urls
    data = {
        "run_type": "csv",
        "url": urls[0],
        "urls": urls,
        "surface": surface,
        "settings": crawl_settings,
        "additional_fields": _parse_additional_fields(additional_fields),
    }
    return data, len(urls)


async def create_crawl_run_from_payload(
    session: AsyncSession, user_id: int, payload: dict
):
    data = prepare_crawl_create_payload(payload)
    run = await create_crawl_run(session, user_id, data)
    return await dispatch_run(session, run)


async def create_crawl_run_from_csv(
    session: AsyncSession,
    user_id: int,
    *,
    csv_content: str,
    surface: str,
    additional_fields: str = "",
    settings_json: str = "{}",
):
    data, url_count = build_csv_crawl_payload(
        csv_content=csv_content,
        surface=surface,
        additional_fields=additional_fields,
        settings_json=settings_json,
    )
    run = await create_crawl_run(session, user_id, data)
    run = await dispatch_run(session, run)
    return run, url_count
