from __future__ import annotations

import logging
import re
from typing import Iterable

from bs4 import BeautifulSoup, NavigableString, Tag
from lxml import etree, html as lxml_html
import regex as regex_lib

from app.services.pipeline_config import DOM_PATTERNS

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
    """Extract a value from HTML using XPath, CSS selector, or regex, in that order of precedence.
    Parameters:
        - html_text (str): HTML content to search.
        - css_selector (str | None): CSS selector used to locate the target element.
        - xpath (str | None): XPath expression used to locate the target element.
        - regex (str | None): Regular expression used to extract a matching value.
    Returns:
        - tuple[str | None, int, str | None]: A tuple containing the extracted value, number of matches found, and the selector/pattern used; returns (None, 0, None) if no match is found."""
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
    """Validate an XPath expression for basic policy and syntax correctness.
    Parameters:
        - xpath (str): The XPath expression to validate.
    Returns:
        - tuple[bool, str | None]: A tuple containing a boolean indicating validity and an error message if invalid, otherwise None."""
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


def validate_regex_syntax(pattern: str) -> tuple[bool, str | None]:
    """Validate whether a regex pattern has valid syntax.
    Parameters:
        - pattern (str): The regex pattern to validate.
    Returns:
        - tuple[bool, str | None]: A tuple containing a boolean indicating validity and an error message if invalid, otherwise None."""
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
    """Validate an XPath candidate against HTML and optionally compare the first match to an expected value.
    Parameters:
        - html_text (str): HTML content to evaluate.
        - xpath (str): XPath expression to validate and execute.
        - expected_value (str | None): Optional value to loosely compare against the first matched result.
    Returns:
        - dict: A dictionary with keys `valid` (bool), `matched_value` (str | None), and `count` (int)."""
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


def build_deterministic_selector_suggestions(
    html_text: str,
    field_names: Iterable[str],
    *,
    existing_candidates: dict[str, list[dict]] | None = None,
    selector_defaults: dict[str, list[dict]] | None = None,
) -> dict[str, list[dict]]:
    """Build deterministic selector suggestions for the given fields from HTML and optional candidates.
    Parameters:
        - html_text (str): HTML content to search for matching elements.
        - field_names (Iterable[str]): Field names to generate selector suggestions for.
        - existing_candidates (dict[str, list[dict]] | None): Optional precomputed candidate suggestions to normalize and include.
        - selector_defaults (dict[str, list[dict]] | None): Optional default selector suggestions to normalize and include.
    Returns:
        - dict[str, list[dict]]: A mapping of field names to deduplicated selector suggestion dictionaries."""
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
    """Build an absolute XPath for a BeautifulSoup node.
    Parameters:
        - node (Tag | NavigableString): The BeautifulSoup tag or text node to convert into an XPath.
    Returns:
        - str | None: An absolute XPath string when one can be constructed, otherwise None."""
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


def bs4_tag_to_xpath(node: Tag) -> str:
    """Build an absolute XPath for a BeautifulSoup tag without lxml."""
    components: list[str] = []
    current = node

    while hasattr(current, "name") and current.name and current.name != "[document]":
        parent = getattr(current, "parent", None)
        if not hasattr(parent, "name") or not parent.name or parent.name == "[document]":
            components.append(current.name)
            break

        siblings = [
            sibling
            for sibling in parent.children
            if hasattr(sibling, "name") and sibling.name == current.name
        ]
        if len(siblings) == 1:
            components.append(current.name)
        else:
            index = siblings.index(current) + 1
            components.append(f"{current.name}[{index}]")
        current = parent

    components.reverse()
    return "/" + "/".join(components) if components else ""


def simplify_xpath(xpath: str) -> str:
    """Trim a long absolute XPath to a relative path using the last segments."""
    segments = [segment for segment in str(xpath or "").split("/") if segment]
    if len(segments) <= 4:
        return str(xpath or "")
    return "//" + "/".join(segments[-4:])


def _build_xpath_tree(document_html: str):
    try:
        return lxml_html.fromstring(document_html)
    except (etree.ParserError, ValueError):
        return None


def _validate_xpath_policy(xpath: str) -> str | None:
    """Validate an XPath expression against disallowed patterns and allowed functions.
    Parameters:
        - xpath (str): The XPath expression to validate.
    Returns:
        - str | None: An error message if the XPath is invalid, otherwise None."""
    candidate = str(xpath or "").strip()
    for pattern, message in _XPATH_DISALLOWED_PATTERNS:
        if pattern.search(candidate):
            return message

    for function_name in _XPATH_FUNCTION_PATTERN.findall(candidate):
        if function_name.lower() not in _XPATH_ALLOWED_FUNCTIONS:
            return f"XPath function '{function_name}' is not allowed"
    return None


def _coerce_xpath_match(results: list[object]) -> str | None:
    """Coerce the first XPath match result into a cleaned string or None.
    Parameters:
        - results (list[object]): List of XPath match results to inspect.
    Returns:
        - str | None: The first match as a stripped string, or None if no usable value is found."""
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
    """Extract a meaningful value from a BeautifulSoup tag based on its element type.
    Parameters:
        - node (Tag): The BeautifulSoup tag to inspect.
    Returns:
        - str | None: The extracted value from the tag, or None if no usable value is found."""
    if node.name == "meta":
        return str(node.get("content") or "").strip() or None
    if node.name == "img":
        return str(node.get("src") or node.get("data-src") or "").strip() or None
    if node.name == "a" and node.get("href"):
        return str(node.get("href") or "").strip() or None
    text = node.get_text(" ", strip=True)
    return text or None


def _normalize_suggestion(value: dict) -> dict | None:
    """Normalize a suggestion dictionary and discard empty suggestions.
    Parameters:
        - value (dict): Input suggestion data containing optional selector and metadata fields.
    Returns:
        - dict | None: A normalized suggestion dictionary, or None if no xpath, css_selector, or regex is provided."""
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
    """Remove duplicate suggestion rows based on xpath, css_selector, and regex.
    Parameters:
        - rows (list[dict]): List of suggestion dictionaries to deduplicate.
    Returns:
        - list[dict]: Deduplicated list of suggestion dictionaries, preserving first occurrences."""
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
    """Normalize a CSS selector string by stripping whitespace and replacing deprecated deep-combinator syntax.
    Parameters:
        - selector (str): The CSS selector string to normalize.
    Returns:
        - str: The normalized selector string, or an empty string if the input is empty or falsy."""
    normalized = str(selector or "").strip()
    if not normalized:
        return normalized
    normalized = normalized.replace("::shadow", " ")
    normalized = normalized.replace(">>>", " ")
    normalized = " ".join(part for part in normalized.split() if part)
    return normalized


def _unique_anchor_xpath(node: Tag, root: BeautifulSoup | Tag, *, allow_class: bool = True) -> str | None:
    """Generate a unique XPath for a node using stable attributes or class name.
    Parameters:
        - node (Tag): The target BeautifulSoup tag to build an XPath for.
        - root (BeautifulSoup | Tag): The document or subtree used to verify XPath uniqueness.
        - allow_class (bool): Whether class-based matching is allowed if no stable attribute is unique.
    Returns:
        - str | None: A unique XPath string if one can be determined; otherwise, None."""
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
    """Build a relative XPath-like selector segment for a BeautifulSoup tag node.
    Parameters:
        - node (Tag): The target tag to generate a selector segment for.
    Returns:
        - str: A selector segment using a unique class when available, otherwise a positional index."""
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
    """Check whether an XPath expression matches exactly one element within the given BeautifulSoup or Tag root.
    Parameters:
        - root (BeautifulSoup | Tag): The HTML root used to build the XPath tree.
        - xpath (str): The XPath expression to evaluate.
    Returns:
        - bool: True if the XPath resolves to exactly one node; otherwise False."""
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
    """Check whether a class value appears only once among a node's siblings of the same tag.
    Parameters:
        - node (Tag): The current BeautifulSoup tag to inspect.
        - class_value (str): The class name to test for uniqueness among sibling tags.
    Returns:
        - bool: True if the class appears exactly once among sibling tags of the same name, or if the node has no tag parent; otherwise False."""
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
    """Extract the first valid stable class name from a value.
    Parameters:
        - value (object): Input value that may be a list, string, or other object containing class names.
    Returns:
        - str | None: The first non-empty, non-numeric class name with at least 3 characters, or None if no valid class is found."""
    classes = value if isinstance(value, list) else str(value or "").split()
    for class_name in classes:
        candidate = str(class_name or "").strip()
        if not candidate or candidate.isdigit() or len(candidate) < 3:
            continue
        return candidate
    return None


def _xpath_literal(value: str) -> str:
    """Build a safe XPath string literal from a Python string.
    Parameters:
        - value (str): The input string to convert into an XPath-compatible literal.
    Returns:
        - str: An XPath expression representing the input string, using quotes or concat() as needed."""
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
    """Compare two text values with loose normalization and substring matching.
    Parameters:
        - actual (str): The actual text value to compare.
        - expected (str): The expected text value to compare against.
    Returns:
        - bool: True if both normalized texts are non-empty and match exactly or one contains the other; otherwise False."""
    def normalize(value: object) -> str:
        return " ".join(str(value or "").split()).strip().lower()

    actual_text = normalize(actual)
    expected_text = normalize(expected)
    return bool(
        actual_text
        and expected_text
        and (actual_text == expected_text or actual_text in expected_text or expected_text in actual_text)
    )
