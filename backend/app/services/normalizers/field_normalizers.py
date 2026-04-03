# Value normalization rules.
from __future__ import annotations

from html import unescape
import re

from bs4 import BeautifulSoup

from app.services.pipeline_config import PRICE_FIELDS, PRICE_REGEX

DESCRIPTION_FIELDS = {"description", "job_description", "summary"}


def normalize_value(field_name: str, value: object) -> object:
    if isinstance(value, str):
        text = " ".join(value.split()).strip()
        if field_name in PRICE_FIELDS:
            match = re.search(PRICE_REGEX, text)
            return match.group(0) if match else text
        if field_name in DESCRIPTION_FIELDS:
            cleaned = _strip_html(text)
            return cleaned
        return text
    return value


def _strip_html(value: str) -> str:
    if "<" not in value or ">" not in value:
        return unescape(value).strip()
    text = BeautifulSoup(value, "html.parser").get_text(" ", strip=True)
    return " ".join(unescape(text).split()).strip()
