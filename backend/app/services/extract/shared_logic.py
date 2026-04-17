from __future__ import annotations

from urllib.parse import urljoin, urlparse

_EMPTY_VALUES = (None, "", [], {})
_DEFAULT_IMAGE_KEYS = ("src", "url", "contentUrl", "image", "thumbnail")
_DEFAULT_TEXT_KEYS = (
    "url",
    "href",
    "src",
    "contentUrl",
    "name",
    "title",
    "value",
    "content",
    "text",
    "description",
)
def find_alias_values(
    data: object,
    aliases: list[str],
    *,
    max_depth: int,
    list_limit: int = 30,
) -> list[object]:
    alias_tokens = {
        "".join(ch for ch in str(alias or "").strip().lower() if ch.isalnum())
        for alias in aliases
        if "".join(ch for ch in str(alias or "").strip().lower() if ch.isalnum())
    }
    if not alias_tokens or max_depth <= 0:
        return []

    values: list[object] = []

    def _visit(node: object, depth: int) -> None:
        if depth <= 0 or node in _EMPTY_VALUES:
            return
        if isinstance(node, dict):
            for key, value in node.items():
                if (
                    "".join(ch for ch in str(key or "").strip().lower() if ch.isalnum())
                    in alias_tokens
                    and value not in _EMPTY_VALUES
                ):
                    values.append(value)
                _visit(value, depth - 1)
            return
        if isinstance(node, list):
            for item in node[:list_limit]:
                _visit(item, depth - 1)

    _visit(data, max_depth)
    return values


def coerce_scalar_text(
    value: object,
    *,
    keys: tuple[str, ...] = _DEFAULT_TEXT_KEYS,
) -> str:
    if isinstance(value, dict):
        for key in keys:
            nested = value.get(key)
            if nested not in _EMPTY_VALUES:
                return coerce_scalar_text(nested, keys=keys)
        return ""
    if isinstance(value, list):
        for item in value:
            text = coerce_scalar_text(item, keys=keys)
            if text:
                return text
        return ""
    return str(value).strip() if value not in _EMPTY_VALUES else ""
def resolve_slug_url(slug: str, *, page_url: str) -> str:
    text = str(slug or "").strip()
    if not text or not page_url:
        return ""
    parsed = urlparse(page_url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    if text.startswith(("http://", "https://", "/")):
        return urljoin(page_url, text)
    origin = f"{parsed.scheme}://{parsed.netloc}/"
    return urljoin(origin, text)


def extract_image_candidates(value: object, *, page_url: str = "") -> list[str]:
    if value in _EMPTY_VALUES:
        return []
    raw_items: list[object] = value if isinstance(value, list) else [value]

    images: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        candidate = ""
        if isinstance(item, dict):
            media_type = str(item.get("type") or "").strip().upper()
            if media_type == "VIDEO":
                continue
            candidate = str(
                item.get("url") or item.get("contentUrl") or item.get("src") or ""
            ).strip()
        else:
            candidate = str(item).strip()
        if not candidate:
            continue
        resolved = urljoin(page_url, candidate) if page_url else candidate
        if urlparse(resolved).path.lower().endswith(
            (".woff", ".woff2", ".ttf", ".otf", ".eot", ".css", ".js", ".map")
        ):
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        images.append(resolved)
    return images


def extract_image_values(
    value: object,
    *,
    page_url: str,
    list_limit: int = 30,
) -> list[str]:
    images: list[str] = []
    seen: set[str] = set()

    def _append(candidate: str) -> None:
        resolved = urljoin(page_url, candidate) if candidate and page_url else candidate
        if not resolved or resolved in seen:
            return
        seen.add(resolved)
        images.append(resolved)

    def _visit(node: object) -> None:
        if node in _EMPTY_VALUES:
            return
        if isinstance(node, dict):
            for key in _DEFAULT_IMAGE_KEYS:
                candidate = node.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    _append(candidate.strip())
            for nested in node.values():
                if nested is not node:
                    _visit(nested)
            return
        if isinstance(node, list):
            for item in node[:list_limit]:
                _visit(item)
            return
        text = str(node).strip()
        if text:
            _append(text)

    _visit(value)
    return images
