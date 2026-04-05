from __future__ import annotations

import logging
from typing import Iterable

from bs4 import BeautifulSoup, NavigableString, Tag
from lxml import etree, html as lxml_html
import regex as regex_lib

from app.services.pipeline_config import DOM_PATTERNS

logger = logging.getLogger(__name__)


def extract_selector_value(
    html_text: str,
    *,
    css_selector: str | None = None,
    xpath: str | None = None,
    regex: str | None = None,
) -> tuple[str | None, int, str | None]:
    if xpath:
        tree = _build_xpath_tree(html_text)
        if tree is not None:
            try:
                matches = tree.xpath(xpath)
            except etree.XPathError:
                matches = []
            value = _coerce_xpath_match(matches[:1])
            if value is not None:
                return value, len(matches), xpath
    if css_selector:
        soup = BeautifulSoup(html_text, "html.parser")
        normalized = _normalize_css_selector(css_selector)
        matches = soup.select(normalized) if normalized else []
        if matches:
            return _node_value(matches[0]), len(matches), css_selector
    if regex:
        try:
            match = regex_lib.search(regex, html_text, regex_lib.DOTALL, timeout=0.05)
        except TimeoutError:
            logger.warning("Timed out while evaluating selector regex", extra={"pattern": regex[:200]})
            match = None
        except regex_lib.error:
            logger.warning("Failed to evaluate selector regex", extra={"pattern": regex[:200]})
            match = None
        if match:
            if match.groups():
                value = next((group for group in match.groups() if group), None)
            else:
                value = match.group(0)
            if value:
                return str(value).strip(), 1, regex
    return None, 0, None


def validate_xpath_syntax(xpath: str) -> tuple[bool, str | None]:
    candidate = str(xpath or "").strip()
    if not candidate:
        return False, "XPath is empty"
    try:
        etree.XPath(candidate)
    except etree.XPathSyntaxError as exc:
        return False, f"Invalid XPath syntax: {exc}"
    except etree.XPathError as exc:
        return False, f"Invalid XPath syntax: {exc}"
    return True, None


def validate_regex_syntax(pattern: str) -> tuple[bool, str | None]:
    candidate = str(pattern or "").strip()
    if not candidate:
        return False, "Regex is empty"
    try:
        regex_lib.compile(candidate)
    except regex_lib.error as exc:
        return False, f"Invalid regex syntax: {exc}"
    return True, None


def validate_xpath_candidate(
    html_text: str,
    xpath: str,
    *,
    expected_value: str | None = None,
) -> dict:
    if not xpath.strip():
        return {"valid": False, "matched_value": None, "count": 0}
    tree = _build_xpath_tree(html_text)
    if tree is None:
        return {"valid": False, "matched_value": None, "count": 0}
    try:
        matches = tree.xpath(xpath)
    except etree.XPathError:
        return {"valid": False, "matched_value": None, "count": 0}
    matched_value = _coerce_xpath_match(matches[:1])
    if matched_value is None:
        return {"valid": False, "matched_value": None, "count": len(matches)}
    if expected_value and not _loose_text_match(matched_value, expected_value):
        return {"valid": False, "matched_value": matched_value, "count": len(matches)}
    return {"valid": True, "matched_value": matched_value, "count": len(matches)}


def build_deterministic_selector_suggestions(
    html_text: str,
    field_names: Iterable[str],
    *,
    existing_candidates: dict[str, list[dict]] | None = None,
    selector_defaults: dict[str, list[dict]] | None = None,
) -> dict[str, list[dict]]:
    soup = BeautifulSoup(html_text, "html.parser")
    suggestions: dict[str, list[dict]] = {}
    existing_candidates = existing_candidates or {}
    selector_defaults = selector_defaults or {}

    for field_name in field_names:
        rows: list[dict] = []
        for candidate in existing_candidates.get(field_name, []):
            row = _normalize_suggestion(candidate)
            if row:
                rows.append(row)
        for selector in selector_defaults.get(field_name, []):
            row = _normalize_suggestion(selector)
            if row:
                rows.append(row)
        if not rows:
            dom_selector = DOM_PATTERNS.get(field_name)
            if dom_selector:
                node = soup.select_one(dom_selector)
                if node:
                    rows.append({
                        "field_name": field_name,
                        "xpath": build_absolute_xpath(node),
                        "css_selector": dom_selector,
                        "regex": None,
                        "status": "deterministic",
                        "sample_value": _node_value(node),
                        "source": "deterministic_dom",
                    })
        if rows:
            suggestions[field_name] = _dedupe_suggestions(rows)
    return suggestions


def build_absolute_xpath(node: Tag | NavigableString) -> str | None:
    if isinstance(node, NavigableString):
        node = node.parent
    if not isinstance(node, Tag):
        return None
    soup = _document_root(node)
    if not isinstance(soup, (BeautifulSoup, Tag)):
        return None

    anchored = _unique_anchor_xpath(node, soup, allow_class=False)
    if anchored:
        return anchored

    segments: list[str] = []
    current: Tag | None = node
    while isinstance(current, Tag) and current.name != "[document]":
        anchor = _unique_anchor_xpath(current, soup, allow_class=current is not node)
        if anchor:
            if not segments:
                return anchor
            return f"{anchor}/{'/'.join(reversed(segments))}"
        segments.append(_relative_segment(current))
        current = current.parent if isinstance(current.parent, Tag) else None
    if not segments:
        return None
    return f"//{'/'.join(reversed(segments))}"


def _build_xpath_tree(document_html: str):
    try:
        return lxml_html.fromstring(document_html)
    except (etree.ParserError, ValueError):
        return None


def _coerce_xpath_match(results: list[object]) -> str | None:
    if not results:
        return None
    first = results[0]
    if isinstance(first, str):
        return first.strip() or None
    if hasattr(first, "text_content"):
        text = first.text_content().strip()
        return text or None
    text = str(first).strip()
    return text or None


def _node_value(node: Tag) -> str | None:
    if node.name == "meta":
        return str(node.get("content") or "").strip() or None
    if node.name == "img":
        return str(node.get("src") or node.get("data-src") or "").strip() or None
    if node.name == "a" and node.get("href"):
        return str(node.get("href") or "").strip() or None
    text = node.get_text(" ", strip=True)
    return text or None


def _normalize_suggestion(value: dict) -> dict | None:
    xpath = str(value.get("xpath") or "").strip() or None
    css_selector = str(value.get("css_selector") or "").strip() or None
    regex = str(value.get("regex") or "").strip() or None
    if not any([xpath, css_selector, regex]):
        return None
    normalized_css_selector = _normalize_css_selector(css_selector) if css_selector else None
    return {
        "field_name": str(value.get("field_name") or "").strip() or None,
        "xpath": xpath,
        "css_selector": normalized_css_selector if normalized_css_selector else None,
        "regex": regex,
        "status": str(value.get("status") or "validated"),
        "sample_value": str(value.get("sample_value") or value.get("value") or "").strip() or None,
        "source": str(value.get("source") or "selector_memory"),
    }


def _dedupe_suggestions(rows: list[dict]) -> list[dict]:
    seen: set[tuple[str | None, str | None, str | None]] = set()
    deduped: list[dict] = []
    for row in rows:
        key = (row.get("xpath"), row.get("css_selector"), row.get("regex"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _normalize_css_selector(selector: str) -> str:
    normalized = str(selector or "").strip()
    if not normalized:
        return normalized
    normalized = normalized.replace("::shadow", " ")
    normalized = normalized.replace(">>>", " ")
    normalized = " ".join(part for part in normalized.split() if part)
    return normalized


def _unique_anchor_xpath(node: Tag, root: BeautifulSoup | Tag, *, allow_class: bool = True) -> str | None:
    attr_candidates = [
        "id",
        "data-testid",
        "data-test",
        "data-qa",
        "itemprop",
        "name",
        "aria-label",
        "title",
    ]
    for attr_name in attr_candidates:
        attr_value = _stable_attr_value(node.get(attr_name))
        if not attr_value:
            continue
        selector = _attribute_xpath(node.name, attr_name, attr_value)
        if _is_unique_xpath(root, selector):
            return selector

    class_value = _stable_class_value(node.get("class"))
    if allow_class and class_value:
        class_literal = _xpath_literal(f" {class_value} ")
        selector = f"//{node.name}[contains(concat(' ', normalize-space(@class), ' '), {class_literal})]"
        if _is_unique_xpath(root, selector):
            return selector
    return None


def _relative_segment(node: Tag) -> str:
    class_value = _stable_class_value(node.get("class"))
    if class_value and _is_unique_class_among_siblings(node, class_value):
        class_literal = _xpath_literal(f" {class_value} ")
        selector = f"{node.name}[contains(concat(' ', normalize-space(@class), ' '), {class_literal})]"
        return selector
    siblings = [
        sibling
        for sibling in node.parent.find_all(node.name, recursive=False)
    ] if isinstance(node.parent, Tag) else [node]
    index = siblings.index(node) + 1 if len(siblings) > 1 else 1
    return f"{node.name}[{index}]"


def _is_unique_xpath(root: BeautifulSoup | Tag, xpath: str) -> bool:
    html_text = str(root)
    tree = _build_xpath_tree(html_text)
    if tree is None:
        return False
    try:
        return len(tree.xpath(xpath)) == 1
    except etree.XPathError:
        return False


def _document_root(node: Tag) -> BeautifulSoup | Tag:
    current: BeautifulSoup | Tag = node
    while isinstance(current.parent, Tag):
        current = current.parent
    return current


def _is_unique_class_among_siblings(node: Tag, class_value: str) -> bool:
    if not isinstance(node.parent, Tag):
        return True
    sibling_matches = 0
    for sibling in node.parent.find_all(node.name, recursive=False):
        classes = {str(value).strip() for value in (sibling.get("class") or []) if str(value).strip()}
        if class_value in classes:
            sibling_matches += 1
    return sibling_matches == 1


def _attribute_xpath(tag_name: str, attr_name: str, attr_value: str) -> str:
    return f"//{tag_name}[@{attr_name}={_xpath_literal(attr_value)}]"


def _stable_attr_value(value: object) -> str | None:
    text = str(value or "").strip()
    if not text or any(ch.isspace() for ch in text):
        return None
    return text


def _stable_class_value(value: object) -> str | None:
    classes = value if isinstance(value, list) else str(value or "").split()
    for class_name in classes:
        candidate = str(class_name or "").strip()
        if not candidate or candidate.isdigit() or len(candidate) < 3:
            continue
        return candidate
    return None


def _xpath_literal(value: str) -> str:
    if "'" not in value:
        return f"'{value}'"
    if '"' not in value:
        return f'"{value}"'
    parts = value.split("'")
    pieces = []
    for index, part in enumerate(parts):
        if part:
            pieces.append(f"'{part}'")
        if index < len(parts) - 1:
            pieces.append("\"'\"")
    return f"concat({', '.join(pieces)})"


def _loose_text_match(actual: str, expected: str) -> bool:
    def normalize(value: object) -> str:
        return " ".join(str(value or "").split()).strip().lower()

    actual_text = normalize(actual)
    expected_text = normalize(expected)
    return bool(
        actual_text
        and expected_text
        and (actual_text == expected_text or actual_text in expected_text or expected_text in actual_text)
    )
