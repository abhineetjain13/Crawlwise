from __future__ import annotations

import re
import time
from typing import Any

from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.field_policy import normalize_requested_field

_DETAIL_BLOCKED_TOKENS = (
    "add to cart",
    "add to bag",
    "bag",
    "buy now",
    "cart",
    "checkout",
    "login",
    "log in",
    "shopping bag",
    "sign in",
    "sign up",
    "subscribe",
    "wishlist",
)


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
        "clicked_count": int(dom.get("clicked_count", 0) or 0)
        + int(aom.get("clicked_count", 0) or 0),
        "expanded_elements": [
            *list(dom.get("expanded_elements") or []),
            *list(aom.get("expanded_elements") or []),
        ],
        "interaction_failures": [
            *list(dom.get("interaction_failures") or []),
            *list(aom.get("interaction_failures") or []),
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
        diagnostics["buttons_found"] = int(diagnostics["buttons_found"]) + len(candidates)
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
                aria_controls = str(snapshot.get("aria_controls") or "").strip()
                tag_name = str(snapshot.get("tag_name") or "").strip().lower()
                candidate_key = (label or probe, aria_controls, tag_name)
                if candidate_key in seen_candidates:
                    continue
                seen_candidates.add(candidate_key)
                if probe and any(token in probe for token in _DETAIL_BLOCKED_TOKENS):
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
                    or any(keyword in probe for keyword in keywords)
                )
                if not looks_expandable:
                    continue
                if not bool(snapshot.get("visible")) or not bool(snapshot.get("actionable")):
                    continue
                await handle.scroll_into_view_if_needed()
                try:
                    await handle.click(timeout=1_000)
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
                diagnostics["interaction_failures"].append("get_by_role_unavailable")
                diagnostics["status"] = "locator_unavailable"
                break
            locator = locator_factory(role, name=name, exact=True)
            locator = getattr(locator, "first", locator)
            if hasattr(locator, "count") and await locator.count() == 0:
                continue
            if hasattr(locator, "is_visible") and not await locator.is_visible(timeout=250):
                continue
            if hasattr(locator, "is_disabled") and await locator.is_disabled():
                continue
            await locator.click(timeout=1_000)
            if int(crawler_runtime_settings.accordion_expand_wait_ms) > 0:
                await page.wait_for_timeout(
                    int(crawler_runtime_settings.accordion_expand_wait_ms)
                )
            diagnostics["clicked_count"] += 1
            diagnostics["expanded_elements"].append(name)
        except Exception as exc:
            diagnostics["interaction_failures"].append(str(exc))
    if diagnostics["status"] == "attempted":
        diagnostics["status"] = (
            "expanded" if diagnostics["clicked_count"] > 0 else "no_matches"
        )
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
            and not any(token in name for token in _DETAIL_BLOCKED_TOKENS)
            and (not keywords or any(keyword in name for keyword in keywords))
            and candidate not in seen
        ):
            seen.add(candidate)
            results.append(candidate)
        for child in list(node.get("children") or []):
            if isinstance(child, dict):
                _walk(child)

    _walk(snapshot)
    return results


def requested_field_tokens(requested_fields: list[str] | None) -> tuple[str, ...]:
    tokens: list[str] = []
    seen: set[str] = set()
    for field_name in list(requested_fields or []):
        normalized = normalize_requested_field(str(field_name or ""))
        if not normalized:
            continue
        for token in re.split(r"[_\W]+", normalized):
            cleaned = str(token or "").strip().lower()
            if len(cleaned) < 3 or cleaned in seen:
                continue
            seen.add(cleaned)
            tokens.append(cleaned)
    return tuple(tokens)
