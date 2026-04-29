from __future__ import annotations

import logging
import re

import regex as regex_lib
from bs4 import BeautifulSoup, NavigableString, Tag
from cssselect import GenericTranslator, SelectorError
from lxml import etree
from lxml import html as lxml_html

from app.services.config.selectors import (
    XPATH_ALLOWED_FUNCTIONS,
    XPATH_DISALLOWED_PATTERNS,
    XPATH_FUNCTION_PATTERN,
)
from app.services.config.runtime_settings import crawler_runtime_settings

logger = logging.getLogger(__name__)


def extract_selector_value(
    html_text: str,
    *,
    css_selector: str | None = None,
    xpath: str | None = None,
    regex: str | None = None,
) -> tuple[str | None, int, str | None]:
    resolved_xpath: str | None = None
    if xpath:
        resolved_xpath, _ = validate_or_convert_xpath(xpath)
    if resolved_xpath:
        tree = _build_xpath_tree(html_text)
        if tree is not None:
            try:
                matches = tree.xpath(resolved_xpath)
            except etree.XPathError:
                matches = []
            values = _coerce_xpath_matches(matches[:12])
            if values:
                filtered_values = _apply_regex_filter(regex, values)
                if filtered_values:
                    return filtered_values[0], len(filtered_values), resolved_xpath
                if not regex:
                    return values[0], len(values), resolved_xpath
    if css_selector:
        soup = BeautifulSoup(html_text, "html.parser")
        normalized = _normalize_css_selector(css_selector)
        matches = soup.select(normalized) if normalized else []
        if matches:
            values = [value for value in (_node_value(node) for node in matches[:12]) if value]
            filtered_values = _apply_regex_filter(regex, values)
            if filtered_values:
                return filtered_values[0], len(filtered_values), css_selector
            if not regex:
                return values[0], len(values), css_selector
    if regex and not xpath and not css_selector:
        filtered_values = _apply_regex_filter(regex, [html_text])
        if filtered_values:
            return filtered_values[0], len(filtered_values), regex
    return None, 0, None


def validate_or_convert_xpath(candidate: str) -> tuple[str | None, str | None]:
    xpath = str(candidate or "").strip()
    if not xpath:
        return None, "XPath is empty"
    prefer_css_translation = _looks_like_css_selector(xpath)
    valid_xpath, xpath_error = validate_xpath_syntax(xpath)
    if valid_xpath and not prefer_css_translation:
        return xpath, None

    normalized_css = _normalize_css_selector(xpath)
    if not normalized_css:
        return (xpath, None) if valid_xpath else (None, xpath_error)
    try:
        converted = GenericTranslator().css_to_xpath(normalized_css)
    except SelectorError:
        return (xpath, None) if valid_xpath else (None, xpath_error)
    converted = _normalize_translated_css_xpath(converted)

    valid_converted_xpath, converted_error = validate_xpath_syntax(converted)
    if not valid_converted_xpath:
        if valid_xpath:
            return xpath, None
        return None, converted_error or xpath_error
    return converted, None


def validate_xpath_syntax(xpath: str) -> tuple[bool, str | None]:
    candidate = str(xpath or "").strip()
    if not candidate:
        return False, "XPath is empty"
    policy_error = _validate_xpath_policy(candidate)
    if policy_error:
        return False, policy_error
    try:
        etree.XPath(candidate)
    except etree.XPathSyntaxError as exc:
        return False, f"Invalid XPath syntax: {exc}"
    except etree.XPathError as exc:
        return False, f"Invalid XPath syntax: {exc}"
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
    resolved_xpath, _ = validate_or_convert_xpath(xpath)
    if not resolved_xpath:
        return {"valid": False, "matched_value": None, "count": 0}
    try:
        matches = tree.xpath(resolved_xpath)
    except etree.XPathError:
        return {"valid": False, "matched_value": None, "count": 0}
    matched_value = _coerce_xpath_match(matches[:1])
    if matched_value is None:
        return {"valid": False, "matched_value": None, "count": len(matches)}
    if expected_value and not _loose_text_match(matched_value, expected_value):
        return {"valid": False, "matched_value": matched_value, "count": len(matches)}
    return {"valid": True, "matched_value": matched_value, "count": len(matches)}


def build_absolute_xpath(node: Tag | NavigableString) -> str | None:
    if isinstance(node, NavigableString):
        parent = node.parent
        if not isinstance(parent, Tag):
            return None
        node = parent
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


def _validate_xpath_policy(xpath: str) -> str | None:
    candidate = str(xpath or "").strip()
    for pattern, message in XPATH_DISALLOWED_PATTERNS:
        if pattern.search(candidate):
            return message

    for function_name in XPATH_FUNCTION_PATTERN.findall(candidate):
        if function_name.lower() not in XPATH_ALLOWED_FUNCTIONS:
            return f"XPath function '{function_name}' is not allowed"
    return None


def _coerce_xpath_match(results: list[object]) -> str | None:
    values = _coerce_xpath_matches(results)
    return values[0] if values else None


def _coerce_xpath_matches(results: list[object]) -> list[str]:
    values: list[str] = []
    for result in results:
        if isinstance(result, str):
            text = result.strip()
        elif hasattr(result, "text_content"):
            text = result.text_content().strip()
        else:
            text = str(result).strip()
        if text:
            values.append(text)
    return values


def _apply_regex_filter(pattern: str | None, values: list[str]) -> list[str]:
    if not pattern:
        return values
    filtered: list[str] = []
    for value in values:
        try:
            match = regex_lib.search(
                pattern,
                value,
                regex_lib.DOTALL,
                timeout=float(crawler_runtime_settings.selector_regex_timeout_seconds),
            )
        except TimeoutError:
            logger.warning(
                "Timed out while evaluating selector regex",
                extra={"pattern": pattern[:200]},
            )
            return []
        except regex_lib.error:
            logger.warning(
                "Failed to evaluate selector regex", extra={"pattern": pattern[:200]}
            )
            return []
        if not match:
            continue
        if match.groups():
            extracted = next((group for group in match.groups() if group), None)
        else:
            extracted = match.group(0)
        normalized = str(extracted or "").strip()
        if normalized:
            filtered.append(normalized)
    return filtered


def _node_value(node: Tag) -> str | None:
    if node.name == "meta":
        return str(node.get("content") or "").strip() or None
    if node.name == "img":
        return str(node.get("src") or node.get("data-src") or "").strip() or None
    if node.name == "a" and node.get("href"):
        return str(node.get("href") or "").strip() or None
    text = node.get_text(" ", strip=True)
    return text or None


def _normalize_css_selector(selector: str) -> str:
    normalized = str(selector or "").strip()
    if not normalized:
        return normalized
    normalized = normalized.replace("::shadow", " ")
    normalized = normalized.replace(">>>", " ")
    normalized = " ".join(part for part in normalized.split() if part)
    return normalized


def _looks_like_css_selector(candidate: str) -> bool:
    normalized = str(candidate or "").strip()
    if not normalized:
        return False
    if normalized.startswith(("//", ".//", "./", "/", "(", "@", "*", "..")):
        return False
    if "::" in normalized or "@" in normalized:
        return False
    if XPATH_FUNCTION_PATTERN.search(normalized):
        return False
    if "#" in normalized:
        return True
    if re.search(r"(?<!\.)\.[A-Za-z_][\w-]*", normalized):
        return True
    if any(token in normalized for token in (">", "+", "~", ",")):
        return True
    if " " in normalized and "/" not in normalized:
        return True
    if "[" in normalized and "]" in normalized and "=" in normalized:
        return True
    return False


def _normalize_translated_css_xpath(xpath: str) -> str:
    normalized = str(xpath or "").strip()
    if not normalized:
        return normalized
    normalized = re.sub(r"^descendant-or-self::", "//", normalized)
    normalized = re.sub(r"/descendant-or-self::\*/", "//", normalized)
    normalized = re.sub(r"/descendant-or-self::", "//", normalized)
    return normalized


def _unique_anchor_xpath(
    node: Tag, root: BeautifulSoup | Tag, *, allow_class: bool = True
) -> str | None:
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
    siblings = (
        [sibling for sibling in node.parent.find_all(node.name, recursive=False)]
        if isinstance(node.parent, Tag)
        else [node]
    )
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
        classes = {
            str(value).strip()
            for value in (sibling.get("class") or [])
            if str(value).strip()
        }
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
            pieces.append('"\'"')
    return f"concat({', '.join(pieces)})"


def _loose_text_match(actual: str, expected: str) -> bool:
    def normalize(value: object) -> str:
        return " ".join(str(value or "").split()).strip().lower()

    actual_text = normalize(actual)
    expected_text = normalize(expected)
    return bool(
        actual_text
        and expected_text
        and (
            actual_text == expected_text
            or actual_text in expected_text
            or expected_text in actual_text
        )
    )
