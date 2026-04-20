from __future__ import annotations

import time
from typing import Any

from app.services.config.runtime_settings import crawler_runtime_settings


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
    expand_all_interactive_elements,
    probe_browser_readiness,
    expand_interactive_elements_via_accessibility,
) -> dict[str, object]:
    current_probe = dict(readiness_probe or {})
    if "detail" not in str(surface or "").lower():
        return detail_expansion_skip("non_detail_surface")
    if current_probe.get("is_ready"):
        return detail_expansion_skip("already_ready")
    if readiness_probe and not current_probe.get("detail_like"):
        return detail_expansion_skip("not_detail_like")
    dom = await expand_all_interactive_elements(
        page,
        surface=surface,
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
    detail_expand_selectors: str,
    detail_expansion_keywords,
    interactive_label,
    is_actionable_interactive_handle,
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
    try:
        candidates = await page.locator(detail_expand_selectors).element_handles()
    except Exception as exc:
        diagnostics["interaction_failures"] = [f"locator_failed:{exc}"]
        return diagnostics

    keywords = detail_expansion_keywords(surface)
    expanded_elements: list[str] = []
    interaction_failures: list[str] = []
    diagnostics["buttons_found"] = len(candidates)
    max_interactions = max(
        0,
        min(
            int(crawler_runtime_settings.detail_expand_max_interactions),
            int(crawler_runtime_settings.accordion_expand_max),
        ),
    )
    clicked_count = 0
    for handle in candidates:
        if clicked_count >= max_interactions:
            diagnostics["status"] = "interaction_limit_reached"
            break
        if max_elapsed_ms is not None and elapsed_ms(started_at) >= int(max_elapsed_ms):
            diagnostics["status"] = "time_budget_reached"
            break
        try:
            label = await interactive_label(handle)
            label_lower = (label or "").lower()
            if keywords and label and not any(keyword in label_lower for keyword in keywords):
                continue
            if not await is_actionable_interactive_handle(handle):
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
            if label:
                expanded_elements.append(label)
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
    candidates = accessibility_expand_candidates(snapshot, surface=surface)
    diagnostics["buttons_found"] = len(candidates)
    max_interactions = max(0, int(crawler_runtime_settings.detail_aom_expand_max_interactions))
    if len(candidates) > max_interactions:
        keywords = detail_expansion_keywords(surface)
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
    aom_expand_roles: set[str],
    detail_expansion_keywords,
) -> list[tuple[str, str]]:
    keywords = detail_expansion_keywords(surface)
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
