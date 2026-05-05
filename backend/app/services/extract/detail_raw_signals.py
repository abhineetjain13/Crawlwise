from __future__ import annotations

from difflib import SequenceMatcher
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag

from app.services.config.extraction_rules import (
    DETAIL_BREADCRUMB_CONTAINER_SELECTORS,
    DETAIL_BREADCRUMB_LABEL_PREFIXES,
    DETAIL_BREADCRUMB_MIN_LABEL_LENGTH,
    DETAIL_BREADCRUMB_ROOT_LABELS,
    DETAIL_BREADCRUMB_SEPARATOR_LABELS,
    DETAIL_BREADCRUMB_SELECTORS,
    DETAIL_BREADCRUMB_TITLE_DUPLICATE_RATIO,
    DETAIL_CATEGORY_LABEL_PREFIXES,
    DETAIL_CATEGORY_UI_TOKENS,
    DETAIL_GENDER_TERMS,
)
from app.services.field_value_core import absolute_url, clean_text, text_or_none


def gender_from_text(value: object) -> str | None:
    text = clean_text(value).lower().replace("-", " ")
    if not text:
        return None
    padded = f" {text} "
    matches = [
        str(canonical)
        for canonical, terms in DETAIL_GENDER_TERMS.items()
        if any(f" {str(term).lower().replace('-', ' ')} " in padded for term in terms)
    ]
    return matches[0] if len(set(matches)) == 1 else None


def gender_from_detail_context(*values: object) -> str | None:
    return gender_from_text(" ".join(str(value or "") for value in values))


def breadcrumb_category_from_dom(
    soup: BeautifulSoup,
    *,
    current_title: str | None = None,
    page_url: str = "",
) -> str | None:
    labels = breadcrumb_labels_from_dom(
        soup, current_title=current_title, page_url=page_url
    )
    return " > ".join(labels) if labels else None


def breadcrumb_labels_from_dom(
    soup: BeautifulSoup,
    *,
    current_title: str | None = None,
    page_url: str = "",
) -> list[str]:
    for selector in DETAIL_BREADCRUMB_SELECTORS:
        nodes = soup.select(str(selector))
        if not nodes:
            continue
        # Group by closest nav, ul, ol, or generic div parent to avoid flattening multiple breadcrumbs
        groups = {}
        for node in nodes:
            parent = node.parent
            while parent and parent.name not in ("nav", "ul", "ol", "div", "section"):
                parent = parent.parent
            if not parent:
                parent = node.parent
            groups.setdefault(id(parent), []).append(node)
        for group_nodes in groups.values():
            labels = _clean_breadcrumb_labels(
                node.get_text(" ", strip=True) for node in group_nodes
            )
            labels = _trim_breadcrumb_labels(
                labels, current_title=current_title, page_url=page_url
            )
            if labels:
                return labels
    for selector in DETAIL_BREADCRUMB_CONTAINER_SELECTORS:
        for container in soup.select(str(selector)):
            container_labels = _breadcrumb_labels_from_container(container)
            container_labels = _trim_breadcrumb_labels(
                container_labels, current_title=current_title, page_url=page_url
            )
            if container_labels:
                return container_labels
    return []


def _breadcrumb_labels_from_container(container) -> list[str]:
    item_nodes = container.select("li")
    if not item_nodes:
        item_nodes = container.select("a, [aria-current], span, p")
    labels = _clean_breadcrumb_labels(
        node.get_text(" ", strip=True) for node in item_nodes
    )
    if labels:
        return labels
    return _clean_breadcrumb_labels(str(container.get_text(" ", strip=True)).split(">"))


def _clean_breadcrumb_labels(values) -> list[str]:
    return dedupe_adjacent(
        [cleaned for value in values if (cleaned := _clean_breadcrumb_label(value))]
    )


def _clean_breadcrumb_label(value: object) -> str:
    text = clean_text(value)
    if not text:
        return ""
    strip_chars = "".join(DETAIL_BREADCRUMB_SEPARATOR_LABELS) + " \t\n\r"
    text = clean_text(text.strip(strip_chars))
    if not text:
        return ""
    # Strip CSS icon class names that leak into accessible text (e.g. Herman Miller)
    text = clean_text(re.sub(r"\barrow-right(?:-[a-z]+)?\b", "", text, flags=re.I))
    if not text:
        return ""
    lowered = text.casefold()
    for prefix in tuple(DETAIL_BREADCRUMB_LABEL_PREFIXES or ()):
        if lowered.startswith(str(prefix).casefold()):
            text = clean_text(text[len(str(prefix)) :])
            break
    lowered = str(text).casefold()
    for prefix in tuple(DETAIL_CATEGORY_LABEL_PREFIXES or ()):
        if lowered.startswith(str(prefix).casefold()):
            return ""
    return text


def detail_breadcrumb_is_root_label(text: str, page_url: str = "") -> bool:
    lowered = clean_text(text).casefold()
    root_labels = {
        clean_text(label).casefold()
        for label in tuple(DETAIL_BREADCRUMB_ROOT_LABELS or ())
        if clean_text(label)
    }
    if lowered in root_labels:
        return True
    if page_url:
        try:
            host = urlparse(page_url).netloc.casefold()
            if host.startswith("www."):
                host = host[4:]
            if lowered == host or lowered == host.split(".")[0]:
                return True
        except ValueError:
            pass
    return False


def _trim_breadcrumb_labels(
    labels: list[str],
    *,
    current_title: str | None = None,
    page_url: str = "",
) -> list[str]:
    rows = list(labels)
    if not rows:
        return []

    if len(rows) > 1 and detail_breadcrumb_is_root_label(rows[-1], page_url) and not detail_breadcrumb_is_root_label(rows[0], page_url):
        rows.reverse()

    category_ui_tokens = {
        clean_text(token).casefold()
        for token in tuple(DETAIL_CATEGORY_UI_TOKENS or ())
        if clean_text(token)
    }
    rows = [
        row
        for row in rows
        if not detail_breadcrumb_is_root_label(row, page_url)
        and clean_text(row).casefold() not in category_ui_tokens
    ]
    if not rows:
        return []
    title = clean_text(current_title).casefold()
    if title and _breadcrumb_label_matches_title(rows[-1], title):
        rows = rows[:-1]
    return rows


def _breadcrumb_label_matches_title(label: object, title: str) -> bool:
    label_normalized = _breadcrumb_title_key(label)
    title_normalized = _breadcrumb_title_key(title)
    if not label_normalized or not title_normalized:
        return False
    if len(label_normalized) < int(DETAIL_BREADCRUMB_MIN_LABEL_LENGTH):
        return False
    if label_normalized == title_normalized:
        return True
    return SequenceMatcher(None, label_normalized, title_normalized).ratio() >= float(
        DETAIL_BREADCRUMB_TITLE_DUPLICATE_RATIO
    )


def _breadcrumb_title_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", clean_text(value).casefold())

def dedupe_adjacent(values: list[str]) -> list[str]:
    rows: list[str] = []
    for value in values:
        cleaned = clean_text(value)
        if cleaned and (not rows or rows[-1].lower() != cleaned.lower()):
            rows.append(cleaned)
    return rows


def prune_irrelevant_detail_dom_nodes(
    soup: BeautifulSoup,
    *,
    page_url: str,
    requested_page_url: str,
) -> None:
    from app.services.extract.detail_identity import (
        _detail_url_matches_requested_identity as _url_matches,
        _record_matches_requested_detail_identity as _record_matches,
    )

    # 1. Prune irrelevant JSON-LD scripts
    pruned_product_names: list[str] = []
    for script in soup.select("script[type='application/ld+json']"):
        try:
            import json
            payload = json.loads(script.get_text())
            if isinstance(payload, list):
                items = [
                    graph_item
                    for item in payload
                    for graph_item in (
                        item.get("@graph")
                        if isinstance(item, dict) and isinstance(item.get("@graph"), list)
                        else [item]
                    )
                ]
            elif isinstance(payload, dict):
                graph = payload.get("@graph")
                items = graph if isinstance(graph, list) else [payload]
            else:
                continue

            # If any item in the script matches, we keep the whole script
            # (as it might be a @graph or BreadcrumbList + Product)
            match_found = False
            script_product_name = ""
            for item in items:
                if not isinstance(item, dict):
                    continue
                # If it doesn't look like a product, don't prune based on it
                if not any(k in item for k in ("name", "offers", "sku", "mpn")):
                    match_found = True
                    break
                if not script_product_name:
                    raw_name = item.get("name")
                    if isinstance(raw_name, str):
                        script_product_name = raw_name.strip()

                raw_url = item.get("url") or item.get("@id")
                if not raw_url:
                    match_found = True
                    break

                abs_url = absolute_url(page_url, raw_url)
                if _url_matches(abs_url, requested_page_url=requested_page_url):
                    match_found = True
                    break

                candidate = {
                    "title": item.get("name"),
                    "sku": item.get("sku") or item.get("productId"),
                }
                if _record_matches(candidate, requested_page_url=requested_page_url):
                    match_found = True
                    break

            if not match_found:
                if script_product_name:
                    pruned_product_names.append(script_product_name)
                script.decompose()
        except Exception:
            continue

    # When product-level JSON-LD was pruned for identity mismatch AND the DOM
    # H1 disagrees with the pruned product name, the H1 is likely part of an
    # unrelated/cross-product shell and should not emit a lone title record.
    # If the H1 agrees with the pruned name, the JSON-LD URL was a placeholder
    # (e.g. ``/undefined/``) but the page genuinely represents that product,
    # so we keep the DOM signal intact.
    if pruned_product_names:
        def _norm(value: str) -> str:
            return " ".join(value.lower().split())

        pruned_norms = {_norm(name) for name in pruned_product_names if name}
        for h1 in soup.find_all("h1"):
            h1_text = _norm(h1.get_text(separator=" ", strip=True))
            if h1_text and h1_text in pruned_norms:
                continue
            h1.decompose()

    # 2. Prune common cross-product UI noise sections
    noise_selectors = (
        "[id*='recently-viewed']",
        "[class*='recently-viewed']",
        "[id*='similar-products']",
        "[class*='similar-products']",
        "[id*='recommendations']",
        "[class*='recommendations']",
        "[id*='people-also-bought']",
        "[class*='people-also-bought']",
        ".upsell",
        ".related-products",
    )
    for selector in noise_selectors:
        for node in soup.select(selector):
            node.decompose()
