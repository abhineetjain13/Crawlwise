from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Pattern

from selectolax.lexbor import LexborHTMLParser


@dataclass(frozen=True, slots=True)
class ScriptTextNode:
    script_id: str
    script_type: str
    text: str


def iter_script_text_nodes(html: str) -> list[ScriptTextNode]:
    parser = LexborHTMLParser(str(html or ""))
    nodes: list[ScriptTextNode] = []
    for node in parser.css("script"):
        attributes = getattr(node, "attributes", {}) or {}
        text = str(node.text(strip=True) or "")
        if not text:
            continue
        nodes.append(
            ScriptTextNode(
                script_id=str(attributes.get("id") or "").strip(),
                script_type=str(attributes.get("type") or "").strip(),
                text=text,
            )
        )
    return nodes


async def iter_script_text_nodes_async(html: str) -> list[ScriptTextNode]:
    return await asyncio.to_thread(iter_script_text_nodes, html)


def extract_script_text_by_id(html: str, script_id: str) -> str | None:
    normalized_id = str(script_id or "").strip().lower()
    if not normalized_id:
        return None
    for node in iter_script_text_nodes(html):
        if node.script_id.lower() != normalized_id:
            continue
        cleaned = node.text.strip()
        return cleaned or None
    return None


def find_script_regex_matches(
    html: str,
    pattern: str | Pattern[str],
) -> list[str]:
    compiled = re.compile(pattern) if isinstance(pattern, str) else pattern
    matches: list[str] = []
    for node in iter_script_text_nodes(html):
        for match in compiled.finditer(node.text):
            if match.lastindex:
                matches.append(match.group(1))
            else:
                matches.append(match.group(0))
    return matches


def find_first_script_text_matching(
    html: str,
    pattern: str | Pattern[str],
) -> str | None:
    compiled = re.compile(pattern) if isinstance(pattern, str) else pattern
    for node in iter_script_text_nodes(html):
        if compiled.search(node.text):
            return node.text
    return None
