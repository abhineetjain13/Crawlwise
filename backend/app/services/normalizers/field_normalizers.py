# Value normalization rules.
from __future__ import annotations

from html import unescape
import re

from bs4 import BeautifulSoup

from app.services.pipeline_config import PRICE_FIELDS, PRICE_REGEX

DESCRIPTION_FIELDS = {"description", "job_description", "summary"}
AVAILABILITY_FIELDS = {"availability"}
PLACEHOLDER_VALUES = {"-", "—", "--", "n/a", "na", "none", "null", "undefined"}
GENERIC_CATEGORY_VALUES = {"detail-page", "detail_page", "product", "page", "pdp"}
GENERIC_TITLE_VALUES = {"chrome", "firefox", "safari", "edge"}


def normalize_value(field_name: str, value: object) -> object:
    if isinstance(value, str):
        text = " ".join(value.split()).strip()
        if text.lower() in PLACEHOLDER_VALUES:
            return ""
        if field_name in PRICE_FIELDS:
            match = re.search(PRICE_REGEX, text)
            return match.group(0) if match else text
        if field_name in DESCRIPTION_FIELDS:
            cleaned = _strip_html(text)
            return cleaned
        if field_name in AVAILABILITY_FIELDS:
            return _normalize_availability(text)
        if field_name == "category" and text.lower() in GENERIC_CATEGORY_VALUES:
            return ""
        if field_name == "title" and text.lower() in GENERIC_TITLE_VALUES:
            return ""
        return text
    return value


def _strip_html(value: str) -> str:
    if "<" not in value or ">" not in value:
        return unescape(value).strip()
    text = BeautifulSoup(value, "html.parser").get_text(" ", strip=True)
    return " ".join(unescape(text).split()).strip()


def _normalize_availability(value: str) -> str:
    text = unescape(value).strip()
    lowered = text.lower()
    if lowered.endswith("/instock"):
        return "in_stock"
    if lowered.endswith("/outofstock"):
        return "out_of_stock"
    if lowered.endswith("/preorder"):
        return "preorder"
    if lowered.endswith("/limitedavailability"):
        return "limited_availability"
    return text
