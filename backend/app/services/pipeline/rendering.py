"""Rendering functions for markdown and HTML output."""
from __future__ import annotations

from html import unescape
from urllib.parse import urljoin, urlparse

from bs4 import NavigableString, Tag
from app.services.extract.candidate_processing import clean_page_text

from .utils import _compact_dict

TITLE_SELECTOR = "h1 a, h2 a, h3 a, h4 a, h5 a, h1, h2, h3, h4, h5"
ANCHOR_SELECTOR = "a[href]"


def _render_fallback_node_markdown(node: Tag, *, page_url: str) -> str:
    """Render a BeautifulSoup node as markdown."""
    parts: list[str] = []
    for child in node.children:
        if isinstance(child, NavigableString):
            text = clean_page_text(str(child))
            if text:
                parts.append(text)
            continue
        if not isinstance(child, Tag):
            continue
        if child.name == "a":
            text = clean_page_text(child.get_text(" ", strip=True))
            href = str(child.get("href", "") or "").strip()
            resolved_href = urljoin(page_url, href) if href else ""
            if text and resolved_href:
                parts.append(f"[{text}]({resolved_href})")
            elif text:
                parts.append(text)
            continue
        nested = _render_fallback_node_markdown(child, page_url=page_url)
        if nested:
            parts.append(nested)
    return (
        clean_page_text(" ".join(parts))
        if parts
        else clean_page_text(node.get_text(" ", strip=True))
    )


def _render_fallback_card_group(
    root: Tag, *, page_url: str
) -> tuple[list[str], int, list[dict[str, object]]]:
    """Render a group of cards as markdown lines."""
    cards = _find_fallback_card_group(root)
    if not cards:
        return [], 0, []

    lines: list[str] = []
    typed_rows: list[dict[str, object]] = []
    total_chars = 0
    seen_titles: set[str] = set()
    
    for card in cards[:12]:
        title_node = card.select_one(TITLE_SELECTOR)
        title_text = (
            clean_page_text(title_node.get_text(" ", strip=True)) if title_node else ""
        )
        if not title_text or title_text.lower() in seen_titles:
            continue
        seen_titles.add(title_text.lower())
        
        link_node = (
            title_node
            if isinstance(title_node, Tag) and title_node.name == "a"
            else card.select_one(ANCHOR_SELECTOR)
        )
        href = (
            str(link_node.get("href", "") or "").strip()
            if isinstance(link_node, Tag)
            else ""
        )
        resolved_href = urljoin(page_url, href) if href else ""
        title_line = (
            f"## [{title_text}]({resolved_href})"
            if resolved_href
            else f"## {title_text}"
        )
        lines.append(title_line)
        total_chars += len(title_text)
        typed_row: dict[str, object] = {
            "title": title_text,
            "url": resolved_href or None,
        }

        description_node = card.select_one(
            "p, [class*='description' i], [class*='summary' i], [class*='excerpt' i]"
        )
        if description_node:
            description_text = clean_page_text(
                description_node.get_text(" ", strip=True)
            )
            if description_text and description_text.lower() != title_text.lower():
                lines.append(description_text)
                total_chars += len(description_text)
                typed_row["description"] = description_text
        
        typed_rows.append(_compact_dict(typed_row))
        if len(lines) >= 24 or total_chars >= 2400:
            break

    return lines, total_chars, typed_rows


def _find_fallback_card_group(root: Tag) -> list[Tag]:
    """Find the best group of similar cards in the page."""
    best_group: list[Tag] = []
    best_score: tuple[int, int] = (0, 0)
    
    for container in root.select("main, section, div, ul, ol"):
        children = [child for child in container.children if isinstance(child, Tag)]
        if len(children) < 2:
            continue
        
        # Group children by tag name and classes
        grouped: dict[tuple[str, tuple[str, ...]], list[Tag]] = {}
        for child in children:
            key = (child.name, tuple(sorted(child.get("class", []))))
            grouped.setdefault(key, []).append(child)
        
        for _key, group in grouped.items():
            if len(group) < 2:
                continue
            
            # Score the group based on linked titles and descriptions
            linked_titles = 0
            descriptive_cards = 0
            for card in group[:12]:
                if card.select_one(TITLE_SELECTOR) and card.select_one(ANCHOR_SELECTOR):
                    linked_titles += 1
                desc_node = card.select_one(
                    "p, [class*='description' i], [class*='summary' i], [class*='excerpt' i]"
                )
                if (
                    desc_node
                    and len(clean_page_text(desc_node.get_text(" ", strip=True))) >= 40
                ):
                    descriptive_cards += 1
            
            score = (linked_titles, descriptive_cards)
            if linked_titles >= 2 and score > best_score:
                best_group = group
                best_score = score
    
    return best_group


def _should_skip_fallback_node(node: Tag, *, page_url: str) -> bool:
    """Check if a node should be skipped in fallback rendering."""
    text = clean_page_text(node.get_text(" ", strip=True))
    if not text:
        return True
    
    lowered = text.lower()
    
    # Skip navigation items
    if node.name == "li":
        if len(text) <= 30:
            anchor = node.select_one(ANCHOR_SELECTOR)
            href = (
                str(anchor.get("href", "") or "").strip()
                if isinstance(anchor, Tag)
                else ""
            )
            resolved_href = urljoin(page_url, href) if href else ""
            if resolved_href:
                parsed = urlparse(resolved_href)
                segments = [segment for segment in parsed.path.split("/") if segment]
                if len(segments) <= 1:
                    return True
            if lowered in {
                "home",
                "products",
                "services",
                "contact us",
                "blogs",
                "news",
            }:
                return True
    
    # Skip generic call-to-action text
    if lowered in {"read more", "learn more", "view more"}:
        return True
    
    return False


def _normalize_target_url(value: object) -> str:
    """Normalize a target URL by removing whitespace."""
    text = unescape(str(value or "")).strip()
    if not text:
        return ""
    return text.replace(" ", "").replace("\n", "").replace("\t", "")


def _render_manifest_tables_markdown(tables: list[dict] | None) -> str:
    """Render manifest tables as markdown."""
    rendered_tables: list[str] = []
    for table in list(tables or [])[:3]:
        rows = table.get("rows") if isinstance(table, dict) else None
        if not isinstance(rows, list) or not rows:
            continue
        table_lines: list[str] = []
        for index, row in enumerate(rows[:8]):
            cells = row.get("cells") if isinstance(row, dict) else None
            if not isinstance(cells, list):
                continue
            values = [
                clean_page_text(cell.get("text", ""))
                for cell in cells
                if isinstance(cell, dict) and clean_page_text(cell.get("text", ""))
            ]
            if values:
                table_lines.append("| " + " | ".join(values) + " |")
                # Add separator after first row (header)
                if index == 0:
                    separator = "| " + " | ".join(["---"] * len(values)) + " |"
                    table_lines.append(separator)
        if table_lines:
            rendered_tables.append("\n".join(table_lines))
    return "\n\n".join(rendered_tables).strip()
