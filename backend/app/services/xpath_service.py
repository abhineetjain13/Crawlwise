from __future__ import annotations

import logging
import re

import regex as regex_lib
from bs4 import BeautifulSoup, NavigableString, Tag
from lxml import etree
from lxml import html as lxml_html

logger = logging.getLogger(__name__)

_XPATH_ALLOWED_FUNCTIONS = {
    "comment",
    "concat",
    "contains",
    "last",
    "normalize-space",
    "node",
    "not",
    "position",
    "processing-instruction",
    "starts-with",
    "string",
    "text",
}
_XPATH_DISALLOWED_PATTERNS = (
    (re.compile(r"\|"), "XPath unions are not supported"),
    (
        re.compile(
            r"(?<![\w-])(ancestor|ancestor-or-self|descendant-or-self|following|following-sibling|namespace|preceding|preceding-sibling|self)::"
        ),
        "XPath axis is not allowed",
    ),
    (re.compile(r"\$[A-Za-z_][\w.-]*"), "XPath variables are not allowed"),
)
# This validator intentionally accepts common node tests that also look like
# function calls in the raw XPath source, such as node() and comment().
_XPATH_FUNCTION_PATTERN = re.compile(r"(?<![:\w-])([A-Za-z_][\w.-]*)\s*\(")


def extract_selector_value(
    html_text: str,
    *,
    css_selector: str | None = None,
    xpath: str | None = None,
    regex: str | None = None,
) -> tuple[str | None, int, str | None]:
    if xpath:
        valid_xpath, _ = validate_xpath_syntax(xpath)
        if not valid_xpath:
            xpath = None
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
            logger.warning(
                "Timed out while evaluating selector regex",
                extra={"pattern": regex[:200]},
            )
            match = None
        except regex_lib.error:
            logger.warning(
                "Failed to evaluate selector regex", extra={"pattern": regex[:200]}
            )
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
    valid_xpath, _ = validate_xpath_syntax(xpath)
    if not valid_xpath:
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


def _validate_xpath_policy(xpath: str) -> str | None:
    candidate = str(xpath or "").strip()
    for pattern, message in _XPATH_DISALLOWED_PATTERNS:
        if pattern.search(candidate):
            return message

    for function_name in _XPATH_FUNCTION_PATTERN.findall(candidate):
        if function_name.lower() not in _XPATH_ALLOWED_FUNCTIONS:
            return f"XPath function '{function_name}' is not allowed"
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


def _normalize_css_selector(selector: str) -> str:
    normalized = str(selector or "").strip()
    if not normalized:
        return normalized
    normalized = normalized.replace("::shadow", " ")
    normalized = normalized.replace(">>>", " ")
    normalized = " ".join(part for part in normalized.split() if part)
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
