from __future__ import annotations

import re
import time
from collections.abc import Iterable
from typing import Any

from app.services.config.extraction_rules import (
    BROWSER_DETAIL_EXPAND_KEYWORDS,
    DETAIL_BLOCKED_TOKENS,
    DETAIL_EXPAND_KEYWORD_EXTENSIONS,
    DETAIL_EXPAND_SELECTORS,
)
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.field_policy import (
    exact_requested_field_key,
    NORMALIZED_REQUESTED_FIELD_ALIASES,
    normalize_requested_field,
)
from app.services.field_value_core import _coerce_int

_DETAIL_EXPAND_KEYWORDS: dict[str, tuple[str, ...]] = {
    str(key): tuple(str(item) for item in list(value or []))
    for key, value in dict(BROWSER_DETAIL_EXPAND_KEYWORDS or {}).items()
}
_AOM_EXPAND_ROLES = {"button", "tab", "link", "menuitem"}


def _string_list(value: object) -> list[str]:
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes, dict)):
        return []
    return [str(item) for item in value]


def detail_expansion_skip(reason: str) -> dict[str, object]:
    return {
        "status": "skipped",
        "reason": reason,
        "clicked_count": 0,
        "expanded_elements": [],
        "interaction_failures": [],
        "dom": {},
        "aom": {},
    }


async def expand_detail_content_if_needed_impl(
    page: Any,
    *,
    surface: str,
    readiness_probe: dict[str, object],
    requested_fields: list[str] | None,
    expand_all_interactive_elements,
    probe_browser_readiness,
    expand_interactive_elements_via_accessibility,
) -> dict[str, object]:
    current_probe = dict(readiness_probe or {})
    if "detail" not in str(surface or "").lower():
        return detail_expansion_skip("non_detail_surface")
    if readiness_probe and not current_probe.get("detail_like"):
        return detail_expansion_skip("not_detail_like")
    dom = await expand_all_interactive_elements(
        page,
        surface=surface,
        requested_fields=requested_fields,
        max_elapsed_ms=int(crawler_runtime_settings.detail_expand_max_elapsed_ms),
    )
    if dom.get("clicked_count", 0):
        current_probe = await probe_browser_readiness(
            page,
            url=str(getattr(page, "url", "") or ""),
            surface=surface,
        )
    aom = {
        "status": "skipped",
        "reason": "not_needed",
        "clicked_count": 0,
        "expanded_elements": [],
        "interaction_failures": [],
        "limit": int(crawler_runtime_settings.detail_aom_expand_max_interactions),
        "max_elapsed_ms": int(crawler_runtime_settings.detail_aom_expand_max_elapsed_ms),
        "attempted": False,
    }
    if not current_probe.get("is_ready"):
        aom = await expand_interactive_elements_via_accessibility(
            page,
            surface=surface,
            requested_fields=requested_fields,
            max_elapsed_ms=int(crawler_runtime_settings.detail_aom_expand_max_elapsed_ms),
        )
    return {
        "status": "expanded"
        if dom.get("clicked_count", 0) or aom.get("clicked_count", 0)
        else "attempted",
        "reason": "missing_detail_content",
        "clicked_count": _coerce_int(dom.get("clicked_count"), default=0)
        + _coerce_int(aom.get("clicked_count"), default=0),
        "expanded_elements": [
            *_string_list(dom.get("expanded_elements")),
            *_string_list(aom.get("expanded_elements")),
        ],
        "interaction_failures": [
            *_string_list(dom.get("interaction_failures")),
            *_string_list(aom.get("interaction_failures")),
        ],
        "dom": dom,
        "aom": aom,
    }


async def expand_all_interactive_elements_impl(
    page: Any,
    *,
    surface: str,
    requested_fields: list[str] | None,
    detail_expand_selectors: tuple[str, ...] | list[str],
    detail_expansion_keywords,
    interactive_candidate_snapshot,
    elapsed_ms,
    max_elapsed_ms: int | None = None,
) -> dict[str, object]:
    started_at = time.perf_counter()
    click_timeout_ms = int(crawler_runtime_settings.detail_expand_click_timeout_ms)
    diagnostics: dict[str, object] = {
        "status": "attempted",
        "buttons_found": 0,
        "clicked_count": 0,
        "expanded_elements": [],
        "interaction_failures": [],
        "limit": int(crawler_runtime_settings.detail_expand_max_interactions),
        "max_elapsed_ms": max_elapsed_ms,
    }
    keywords = detail_expansion_keywords(surface, requested_fields=requested_fields)
    requested_keywords = requested_field_tokens(requested_fields)
    expanded_elements: list[str] = []
    interaction_failures: list[str] = []
    max_interactions = max(
        0,
        min(
            int(crawler_runtime_settings.detail_expand_max_interactions),
            int(crawler_runtime_settings.accordion_expand_max),
        ),
    )
    max_per_selector = max(1, int(crawler_runtime_settings.detail_expand_max_per_selector))
    clicked_count = 0
    seen_candidates: set[tuple[str, str, str]] = set()
    selectors = [
        str(selector).strip()
        for selector in list(detail_expand_selectors or [])
        if str(selector).strip()
    ]
    for selector in selectors:
        if clicked_count >= max_interactions:
            diagnostics["status"] = "interaction_limit_reached"
            break
        if max_elapsed_ms is not None and elapsed_ms(started_at) >= int(max_elapsed_ms):
            diagnostics["status"] = "time_budget_reached"
            break
        try:
            candidates = await page.locator(selector).element_handles()
        except Exception as exc:
            interaction_failures.append(f"locator_failed:{selector}:{exc}")
            continue
        diagnostics["buttons_found"] = _coerce_int(diagnostics["buttons_found"]) + len(candidates)
        selector_clicks = 0
        for handle in candidates:
            if clicked_count >= max_interactions:
                diagnostics["status"] = "interaction_limit_reached"
                break
            if max_elapsed_ms is not None and elapsed_ms(started_at) >= int(max_elapsed_ms):
                diagnostics["status"] = "time_budget_reached"
                break
            if selector_clicks >= max_per_selector:
                break
            try:
                snapshot = await interactive_candidate_snapshot(handle)
                probe = str(snapshot.get("probe") or "").strip().lower()
                label = str(snapshot.get("label") or "").strip().lower()
                aria_expanded = str(snapshot.get("aria_expanded") or "").strip().lower()
                href = str(snapshot.get("href") or "").strip().lower()
                aria_controls = str(snapshot.get("aria_controls") or "").strip()
                data_qa_action = str(snapshot.get("data_qa_action") or "").strip().lower()
                class_name = str(snapshot.get("class_name") or "").strip().lower()
                tag_name = str(snapshot.get("tag_name") or "").strip().lower()
                requested_keyword_probe = " ".join(
                    part for part in (label, aria_controls, data_qa_action) if part
                ).strip()
                keyword_probe = " ".join(
                    part for part in (label, probe, data_qa_action, class_name) if part
                ).strip()
                non_content_probe = " ".join(
                    part for part in (label, probe, data_qa_action, class_name) if part
                ).strip()
                candidate_key = (label or probe, aria_controls, tag_name)
                if candidate_key in seen_candidates:
                    continue
                seen_candidates.add(candidate_key)
                size_toggle_hint = any(
                    token in f"{data_qa_action} {class_name}"
                    for token in ("size selector", "size-selector", "open-size-selector")
                )
                navigational_anchor = bool(
                    tag_name == "a"
                    and href
                    and not href.startswith(("#", "javascript:", "mailto:", "tel:"))
                    and not aria_controls
                    and not size_toggle_hint
                )
                if any(
                    token in non_content_probe
                    for token in (
                        "add-to-wishlist",
                        "gallery",
                        "media-zoom",
                        "thumbnail",
                        "wishlist",
                    )
                ):
                    continue
                if navigational_anchor:
                    continue
                if (
                    probe
                    and any(token in probe for token in DETAIL_BLOCKED_TOKENS)
                    and not size_toggle_hint
                ):
                    continue
                matches_requested_keywords = bool(
                    requested_keywords
                    and any(
                        keyword in requested_keyword_probe
                        for keyword in requested_keywords
                    )
                )
                matches_generic_requested_keywords = any(
                    keyword in requested_keyword_probe for keyword in keywords
                )
                matches_generic_keywords = any(
                    keyword in keyword_probe for keyword in keywords
                )
                if (
                    list(requested_fields or [])
                    and not (
                        matches_requested_keywords
                        or matches_generic_requested_keywords
                        or size_toggle_hint
                    )
                ):
                    continue
                looks_expandable = bool(
                    selector
                    in {
                        "summary",
                        "details > summary",
                        "[aria-expanded='false']",
                        "button[aria-controls]",
                        "[role='button'][aria-controls]",
                        "[role='tab'][aria-controls]",
                    }
                    or aria_expanded == "false"
                    or aria_controls
                    or tag_name == "summary"
                    or matches_requested_keywords
                    or matches_generic_keywords
                )
                if not looks_expandable:
                    continue
                if not bool(snapshot.get("visible")) or not bool(snapshot.get("actionable")):
                    continue
                if max_elapsed_ms is not None and elapsed_ms(started_at) >= int(max_elapsed_ms):
                    diagnostics["status"] = "time_budget_reached"
                    break
                await handle.scroll_into_view_if_needed()
                try:
                    await handle.click(timeout=click_timeout_ms)
                except Exception:
                    await handle.evaluate(
                        "(node) => node instanceof HTMLElement && node.click()"
                    )
                if int(crawler_runtime_settings.accordion_expand_wait_ms) > 0:
                    await page.wait_for_timeout(
                        int(crawler_runtime_settings.accordion_expand_wait_ms)
                    )
                clicked_count += 1
                selector_clicks += 1
                expanded_label = label or probe
                if expanded_label:
                    expanded_elements.append(expanded_label)
                if max_elapsed_ms is not None and elapsed_ms(started_at) >= int(max_elapsed_ms):
                    diagnostics["status"] = "time_budget_reached"
                    break
            except Exception as exc:
                interaction_failures.append(str(exc))
    if diagnostics["status"] == "attempted":
        diagnostics["status"] = "expanded" if clicked_count > 0 else "no_matches"
    diagnostics["clicked_count"] = clicked_count
    diagnostics["expanded_elements"] = expanded_elements
    diagnostics["interaction_failures"] = interaction_failures
    diagnostics["elapsed_ms"] = elapsed_ms(started_at)
    return diagnostics


async def expand_interactive_elements_via_accessibility_impl(
    page: Any,
    *,
    surface: str,
    requested_fields: list[str] | None,
    accessibility_expand_candidates,
    detail_expansion_keywords,
    elapsed_ms,
    max_elapsed_ms: int | None = None,
) -> dict[str, object]:
    started_at = time.perf_counter()
    click_timeout_ms = int(crawler_runtime_settings.detail_expand_click_timeout_ms)
    visibility_timeout_ms = int(
        crawler_runtime_settings.detail_expand_visibility_timeout_ms
    )
    diagnostics: dict[str, object] = {
        "status": "attempted",
        "attempted": False,
        "limit": int(crawler_runtime_settings.detail_aom_expand_max_interactions),
        "max_elapsed_ms": max_elapsed_ms,
        "buttons_found": 0,
        "clicked_count": 0,
        "expanded_elements": [],
        "interaction_failures": [],
    }
    clicked_count = 0
    expanded_elements: list[str] = []
    interaction_failures: list[str] = []
    accessibility = getattr(page, "accessibility", None)
    snapshot_fn = getattr(accessibility, "snapshot", None)
    if snapshot_fn is None:
        diagnostics["status"] = "skipped"
        diagnostics["reason"] = "accessibility_unavailable"
        diagnostics["elapsed_ms"] = elapsed_ms(started_at)
        return diagnostics
    diagnostics["attempted"] = True
    try:
        snapshot = await snapshot_fn()
    except Exception as exc:
        diagnostics["status"] = "snapshot_failed"
        diagnostics["interaction_failures"] = [f"snapshot_failed:{exc}"]
        diagnostics["elapsed_ms"] = elapsed_ms(started_at)
        return diagnostics
    candidates = accessibility_expand_candidates(
        snapshot,
        surface=surface,
        requested_fields=requested_fields,
    )
    diagnostics["buttons_found"] = len(candidates)
    max_interactions = max(0, int(crawler_runtime_settings.detail_aom_expand_max_interactions))
    if len(candidates) > max_interactions:
        keywords = detail_expansion_keywords(surface, requested_fields=requested_fields)
        if keywords:
            prioritized = [
                item for item in candidates if any(keyword in item[1] for keyword in keywords)
            ]
            prioritized_set = set(prioritized)
            candidates = prioritized + [
                item for item in candidates if item not in prioritized_set
            ]
        diagnostics["skipped_count"] = len(candidates) - max_interactions
    for role, name in candidates[:max_interactions]:
        if max_elapsed_ms is not None and elapsed_ms(started_at) >= int(max_elapsed_ms):
            diagnostics["status"] = "time_budget_reached"
            break
        try:
            locator_factory = getattr(page, "get_by_role", None)
            if locator_factory is None:
                interaction_failures.append("get_by_role_unavailable")
                diagnostics["status"] = "locator_unavailable"
                break
            locator = locator_factory(role, name=name, exact=True)
            locator = getattr(locator, "first", locator)
            if hasattr(locator, "count") and await locator.count() == 0:
                continue
            wait_for = getattr(locator, "wait_for", None)
            if callable(wait_for):
                try:
                    await wait_for(state="visible", timeout=visibility_timeout_ms)
                except Exception:
                    continue
            elif hasattr(locator, "is_visible") and not await locator.is_visible():
                continue
            if hasattr(locator, "is_disabled") and await locator.is_disabled():
                continue
            await locator.click(timeout=click_timeout_ms)
            if int(crawler_runtime_settings.accordion_expand_wait_ms) > 0:
                await page.wait_for_timeout(
                    int(crawler_runtime_settings.accordion_expand_wait_ms)
                )
            clicked_count += 1
            expanded_elements.append(name)
        except Exception as exc:
            interaction_failures.append(str(exc))
    if diagnostics["status"] == "attempted":
        diagnostics["status"] = (
            "expanded" if clicked_count > 0 else "no_matches"
        )
    diagnostics["clicked_count"] = clicked_count
    diagnostics["expanded_elements"] = expanded_elements
    diagnostics["interaction_failures"] = interaction_failures
    diagnostics["elapsed_ms"] = elapsed_ms(started_at)
    return diagnostics

def accessibility_expand_candidates_impl(
    snapshot: dict[str, object] | None,
    *,
    surface: str,
    requested_fields: list[str] | None,
    aom_expand_roles: set[str],
    detail_expansion_keywords,
) -> list[tuple[str, str]]:
    keywords = detail_expansion_keywords(surface, requested_fields=requested_fields)
    if not snapshot:
        return []
    results: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def _walk(node: dict[str, object]) -> None:
        role = str(node.get("role") or "").strip().lower()
        name = " ".join(str(node.get("name") or "").split()).strip().lower()
        candidate = (role, name)
        if (
            role in aom_expand_roles
            and name
            and not any(token in name for token in DETAIL_BLOCKED_TOKENS)
            and (not keywords or any(keyword in name for keyword in keywords))
            and candidate not in seen
        ):
            seen.add(candidate)
            results.append(candidate)
        children = node.get("children")
        for child in children if isinstance(children, list) else []:
            if isinstance(child, dict):
                _walk(child)

    _walk(snapshot)
    return results


def requested_field_tokens(requested_fields: list[str] | None) -> tuple[str, ...]:
    tokens: list[str] = []
    seen: set[str] = set()
    for field_name in list(requested_fields or []):
        exact_key = exact_requested_field_key(str(field_name or ""))
        for token in re.split(r"[_\W]+", exact_key):
            cleaned = str(token or "").strip().lower()
            if len(cleaned) < 3 or cleaned in seen:
                continue
            seen.add(cleaned)
            tokens.append(cleaned)
        normalized = normalize_requested_field(str(field_name or ""))
        if not normalized:
            continue
        aliases = NORMALIZED_REQUESTED_FIELD_ALIASES.get(normalized, [normalized])
        for alias in aliases:
            for token in re.split(r"[_\W]+", str(alias or "")):
                cleaned = str(token or "").strip().lower()
                if len(cleaned) < 3 or cleaned in seen:
                    continue
                seen.add(cleaned)
                tokens.append(cleaned)
    return tuple(tokens)


def detail_expansion_keywords(
    surface: str,
    *,
    requested_fields: list[str] | None = None,
) -> tuple[str, ...]:
    lowered = str(surface or "").strip().lower()
    if "ecommerce" in lowered:
        base_keywords = _DETAIL_EXPAND_KEYWORDS.get("ecommerce", ())
        extended_keywords = DETAIL_EXPAND_KEYWORD_EXTENSIONS.get("ecommerce", ())
    elif "job" in lowered:
        base_keywords = _DETAIL_EXPAND_KEYWORDS.get("job", ())
        extended_keywords = DETAIL_EXPAND_KEYWORD_EXTENSIONS.get("job", ())
    else:
        base_keywords = ()
        extended_keywords = ()
    dynamic_keywords = requested_field_tokens(requested_fields)
    keywords = [*base_keywords]
    if extended_keywords:
        keywords.extend(extended_keywords)
    if dynamic_keywords:
        keywords.extend(dynamic_keywords)
    return tuple(dict.fromkeys(keywords))


def accessibility_expand_candidates(
    snapshot: dict[str, object] | None,
    *,
    surface: str,
    requested_fields: list[str] | None = None,
) -> list[tuple[str, str]]:
    return accessibility_expand_candidates_impl(
        snapshot,
        surface=surface,
        requested_fields=requested_fields,
        aom_expand_roles=_AOM_EXPAND_ROLES,
        detail_expansion_keywords=detail_expansion_keywords,
    )


async def interactive_label(handle: Any) -> str:
    value = await handle.evaluate(
        """(node) => {
            const pieces = [
                node.innerText,
                node.textContent,
                node.getAttribute('aria-label'),
                node.getAttribute('title'),
                node.getAttribute('data-testid'),
            ];
            return pieces.find((item) => item && item.trim()) || '';
        }"""
    )
    return " ".join(str(value or "").split()).strip().lower()


async def is_actionable_interactive_handle(handle: Any) -> bool:
    state = await handle.evaluate(
        """(node) => {
            if (!(node instanceof HTMLElement) || !node.isConnected) {
                return { actionable: false };
            }
            const style = window.getComputedStyle(node);
            const rect = node.getBoundingClientRect();
            const disabled = Boolean(
                node.hasAttribute('disabled') ||
                node.getAttribute('aria-disabled') === 'true' ||
                node.inert
            );
            const hidden = Boolean(
                node.hidden ||
                node.getAttribute('aria-hidden') === 'true' ||
                style.display === 'none' ||
                style.visibility === 'hidden' ||
                style.pointerEvents === 'none'
            );
            const collapsed = rect.width <= 0 || rect.height <= 0;
            return { actionable: !(disabled || hidden || collapsed) };
        }"""
    )
    if not isinstance(state, dict):
        return False
    return bool(state.get("actionable"))


async def _interactive_handle_attr(handle: Any, attr_name: str) -> str:
    getter = getattr(handle, "get_attribute", None)
    if getter is None:
        return ""
    try:
        value = await getter(attr_name)
    except Exception:
        return ""
    return " ".join(str(value or "").split()).strip().lower()


async def _interactive_handle_tag_name(handle: Any) -> str:
    try:
        value = await handle.evaluate(
            "(node) => node instanceof Element ? node.tagName.toLowerCase() : ''"
        )
    except Exception:
        return ""
    return " ".join(str(value or "").split()).strip().lower()


async def _interactive_handle_is_visible(handle: Any) -> bool:
    checker = getattr(handle, "is_visible", None)
    if checker is None:
        return True
    try:
        return bool(await checker())
    except Exception:
        return False


async def interactive_candidate_snapshot(handle: Any) -> dict[str, object]:
    label = await interactive_label(handle)
    visible = await _interactive_handle_is_visible(handle)
    aria_label = await _interactive_handle_attr(handle, "aria-label")
    title = await _interactive_handle_attr(handle, "title")
    href = await _interactive_handle_attr(handle, "href")
    aria_controls = await _interactive_handle_attr(handle, "aria-controls")
    aria_expanded = await _interactive_handle_attr(handle, "aria-expanded")
    data_qa_action = await _interactive_handle_attr(handle, "data-qa-action")
    data_testid = await _interactive_handle_attr(handle, "data-testid")
    class_name = await _interactive_handle_attr(handle, "class")
    tag_name = await _interactive_handle_tag_name(handle)
    probe = " ".join(
        part
        for part in (label, aria_label, title, data_qa_action, data_testid)
        if str(part or "").strip()
    ).strip().lower()
    return {
        "label": label,
        "probe": probe,
        "aria_label": aria_label,
        "title": title,
        "href": href,
        "aria_controls": aria_controls,
        "aria_expanded": aria_expanded,
        "data_qa_action": data_qa_action,
        "data_testid": data_testid,
        "class_name": class_name,
        "tag_name": tag_name,
        "visible": visible,
        "actionable": await is_actionable_interactive_handle(handle),
    }


def _elapsed_ms(started_at: float) -> int:
    return max(0, int((time.perf_counter() - started_at) * 1000))


async def expand_all_interactive_elements(
    page: Any,
    *,
    surface: str = "",
    requested_fields: list[str] | None = None,
    checkpoint: Any = None,
    max_elapsed_ms: int | None = None,
) -> dict[str, object]:
    del checkpoint
    return await expand_all_interactive_elements_impl(
        page,
        surface=surface,
        requested_fields=requested_fields,
        detail_expand_selectors=DETAIL_EXPAND_SELECTORS,
        detail_expansion_keywords=detail_expansion_keywords,
        interactive_candidate_snapshot=interactive_candidate_snapshot,
        elapsed_ms=_elapsed_ms,
        max_elapsed_ms=max_elapsed_ms,
    )


async def expand_interactive_elements_via_accessibility(
    page: Any,
    *,
    surface: str = "",
    requested_fields: list[str] | None = None,
    max_elapsed_ms: int | None = None,
) -> dict[str, object]:
    return await expand_interactive_elements_via_accessibility_impl(
        page,
        surface=surface,
        requested_fields=requested_fields,
        accessibility_expand_candidates=accessibility_expand_candidates,
        detail_expansion_keywords=detail_expansion_keywords,
        elapsed_ms=_elapsed_ms,
        max_elapsed_ms=max_elapsed_ms,
    )
