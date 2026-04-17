from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Callable
from urllib.parse import parse_qsl, urlparse

from app.services.acquisition.blocked_detector import detect_blocked_page
from app.services.config.acquisition_guards import (
    JOB_ERROR_PAGE_HEADINGS,
    JOB_ERROR_PAGE_TITLES,
    JOB_REDIRECT_SHELL_CANONICAL_URLS,
    JOB_REDIRECT_SHELL_HEADINGS,
    JOB_REDIRECT_SHELL_TITLES,
)
from app.services.config.crawl_runtime import (
    BROWSER_FALLBACK_VISIBLE_TEXT_MIN,
    JS_SHELL_MIN_CONTENT_LEN,
)
from app.services.platform_policy import (
    browser_first_domains,
    job_platform_families,
    resolve_platform_runtime_policy,
)
from app.services.config.selectors import CARD_SELECTORS
from bs4 import BeautifulSoup

HTML_PARSER = "html.parser"
JOB_PLATFORM_FAMILIES = frozenset({*job_platform_families(), "generic_jobs"})
CARD_SELECTORS_COMMERCE = tuple(CARD_SELECTORS.get("ecommerce", []))
CARD_SELECTORS_JOBS = tuple(CARD_SELECTORS.get("jobs", []))

_COMMERCE_REDIRECT_TITLE_FRAGMENTS: frozenset[str] = frozenset(
    {
        "sign in",
        "log in",
        "login",
        "access denied",
        "403 forbidden",
        "404 not found",
        "page not found",
        "session expired",
        "account required",
    }
)
_COMMERCE_SOFT_404_TITLES: frozenset[str] = frozenset(
    {
        "404 not found",
        "page not found",
        "sorry, this page isn't available.",
        "sorry, this page isn't available",
        "this page isn't available",
        "this page is not available",
    }
)
_COMMERCE_SOFT_404_HEADINGS: frozenset[str] = frozenset(
    {
        "404 not found",
        "page not found",
        "sorry, this page isn't available.",
        "sorry, this page isn't available",
        "this page isn't available",
        "this page is not available",
    }
)
_COMMERCE_TRANSACTIONAL_PATH_TOKENS: frozenset[str] = frozenset(
    {
        "cart",
        "cartupdate",
        "cartupdate.aspx",
        "checkout",
        "basket",
        "bag",
        "addtocart",
        "add-to-cart",
    }
)
_COMMERCE_TRANSACTIONAL_ACTION_VALUES: frozenset[str] = frozenset(
    {"add", "addtocart", "add-to-cart", "buy", "buy-now", "buynow", "checkout"}
)
_COMMERCE_TRANSACTIONAL_TITLE_FRAGMENTS: frozenset[str] = frozenset(
    {
        "shopping cart",
        "your cart",
        "my cart",
        "your bag",
        "my bag",
        "checkout",
    }
)


class AcquisitionOutcome(StrEnum):
    direct_html = "direct_html"
    browser_rendered = "browser_rendered"
    promoted_source = "promoted_source"
    promoted_source_browser = "promoted_source_browser"
    json_response = "json_response"
    blocked = "blocked"
    js_shell = "js_shell"
    empty = "empty"
    error = "error"


@dataclass(slots=True)
class BrowserEscalationDecision:
    needs_browser: bool
    reason: str
    structured_override: bool = False


@dataclass(frozen=True, slots=True)
class AcquisitionExecutionDecision:
    runtime: str
    reason: str
    fallback_allowed: bool
    expected_evidence: tuple[str, ...] = ()

    def to_diagnostics(self) -> dict[str, object]:
        return {
            "acquisition_runtime": str(self.runtime or "").strip() or None,
            "acquisition_runtime_reason": str(self.reason or "").strip() or None,
            "acquisition_runtime_fallback_allowed": bool(self.fallback_allowed),
            "expected_evidence": list(self.expected_evidence or ()) or None,
        }


@dataclass(frozen=True, slots=True)
class TraversalSurfacePolicy:
    surface: str | None
    normalized_surface: str
    is_listing_surface: bool
    is_detail_surface: bool
    card_selectors: tuple[str, ...]
    traversal_disabled_reason: str | None = None


@dataclass(frozen=True, slots=True)
class AutoTraversalDecision:
    decision: str
    should_paginate_now: bool


def normalize_surface(surface: str | None) -> str:
    return str(surface or "").strip().lower()


def classify_acquisition_outcome(result) -> str:
    diag = result.diagnostics if isinstance(result.diagnostics, dict) else {}
    if result.content_type == "json":
        return AcquisitionOutcome.json_response
    if not result.html and result.json_data is None:
        return AcquisitionOutcome.empty
    if bool(diag.get("curl_blocked")) or bool(diag.get("browser_blocked")):
        return AcquisitionOutcome.blocked
    blocked = diag.get("blocked")
    if isinstance(blocked, dict) and blocked.get("is_blocked"):
        return AcquisitionOutcome.blocked
    if diag.get("promoted_browser_used"):
        return AcquisitionOutcome.promoted_source_browser
    if diag.get("promoted_source_used"):
        return AcquisitionOutcome.promoted_source
    if result.method == "playwright":
        return AcquisitionOutcome.browser_rendered
    return AcquisitionOutcome.direct_html


def matches_domain_policy(domain: str, candidates: list[str]) -> bool:
    normalized_domain = str(domain or "").strip().lower()
    for candidate in (
        str(candidate or "").strip().lower() for candidate in candidates if candidate
    ):
        if normalized_domain == candidate or normalized_domain.endswith(f".{candidate}"):
            return True
    return False


def requires_browser_first(url: str, platform_family: str | None) -> bool:
    domain = urlparse(url).netloc.lower().replace("www.", "")
    if matches_domain_policy(domain, browser_first_domains()):
        return True
    normalized_platform = normalize_surface(platform_family)
    if normalized_platform in JOB_PLATFORM_FAMILIES:
        return True
    policy = resolve_platform_runtime_policy(url)
    return bool(policy.get("requires_browser"))


def browser_escalation_decision(
    http_result,
    *,
    surface: str | None,
    requested_fields: list[str] | None,
) -> BrowserEscalationDecision:
    if http_result is None:
        return BrowserEscalationDecision(True, "http_failed")
    analysis = http_result.acquirer_analysis or {}
    if http_result.content_type == "json":
        return BrowserEscalationDecision(False, "json_response")
    blocked = analysis.get("blocked")
    visible_text = str(analysis.get("visible_text") or "")
    content_len = int(analysis.get("content_len") or 0)
    gate_phrases = bool(analysis.get("gate_phrases"))
    listing_signals = analysis.get("listing_signals")
    extractability = (
        analysis.get("extractability")
        if isinstance(analysis.get("extractability"), dict)
        else {}
    )
    invalid_surface_page = bool(analysis.get("invalid_surface_page"))
    js_shell_detected = bool(analysis.get("js_shell_detected"))
    normalized_surface = str(surface or "").strip().lower()
    supported_surface = normalized_surface in {
        "ecommerce_listing",
        "job_listing",
        "ecommerce_detail",
        "job_detail",
    }
    requested_field_names = [
        str(field or "").strip()
        for field in (requested_fields or [])
        if str(field or "").strip()
    ]
    missing_data_requires_browser = (
        supported_surface
        and not extractability.get("has_extractable_data")
        and str(extractability.get("reason") or "")
        in {
            "listing_search_shell_without_records",
            "iframe_shell",
            "frameset_shell",
            "insufficient_detail_signals",
            "no_listing_signals",
            "empty_html",
        }
    )
    if (
        missing_data_requires_browser
        and normalized_surface.endswith("listing")
        and getattr(listing_signals, "strong", False)
    ):
        missing_data_requires_browser = False
    needs_browser, reason = False, "extractable_data_found"
    if getattr(blocked, "is_blocked", False):
        needs_browser, reason = True, "blocked_page"
    elif http_result.status_code in {403, 429, 503}:
        needs_browser, reason = True, f"http_status_{http_result.status_code}"
    elif missing_data_requires_browser:
        needs_browser, reason = (
            True,
            str(extractability.get("reason") or "missing_extractable_data"),
        )
    elif (
        normalized_surface.endswith("detail")
        and requested_field_names
        and js_shell_detected
        and len(visible_text) < BROWSER_FALLBACK_VISIBLE_TEXT_MIN
    ):
        needs_browser, reason = True, "requested_fields_require_browser"
    elif (
        len(visible_text) < BROWSER_FALLBACK_VISIBLE_TEXT_MIN
        and content_len < JS_SHELL_MIN_CONTENT_LEN
    ):
        needs_browser, reason = True, "low_visible_text"
    elif gate_phrases:
        needs_browser, reason = True, "js_gate_phrases"
    elif js_shell_detected and len(visible_text) < 1000:
        needs_browser, reason = True, "js_shell"
    elif http_result.error:
        needs_browser, reason = True, "http_error"
    extractability_reason = str(extractability.get("reason") or "")
    structured_override = (
        needs_browser
        and reason != "js_shell"
        and not getattr(blocked, "is_blocked", False)
        and not normalized_surface.endswith("detail")
        and bool(extractability.get("has_extractable_data"))
        and extractability_reason not in {"surface_unspecified", "adapter_hint"}
    )
    if structured_override:
        needs_browser, reason = False, "structured_data_found"
    if invalid_surface_page:
        needs_browser, reason = True, "invalid_surface_page"
    diagnostics = (
        analysis.get("curl_diagnostics")
        if isinstance(analysis.get("curl_diagnostics"), dict)
        else {}
    )
    diagnostics["curl_needs_browser"] = needs_browser
    diagnostics["browser_retry_reason"] = (
        str(extractability.get("reason") or reason) if needs_browser else None
    )
    diagnostics["escalation_reason"] = reason if needs_browser else None
    if structured_override:
        override_reason = str(extractability.get("reason") or "extractable_data_found")
        diagnostics["js_shell_overridden"] = (
            "structured_data_found"
            if override_reason in {"structured_listing_markup", "next_data_signals"}
            else override_reason
        )
    return BrowserEscalationDecision(needs_browser, reason, structured_override)


def needs_browser(
    http_result,
    *,
    surface: str | None,
    requested_fields: list[str] | None,
) -> tuple[bool, str]:
    decision = browser_escalation_decision(
        http_result,
        surface=surface,
        requested_fields=requested_fields,
    )
    return decision.needs_browser, decision.reason


def decide_acquisition_execution(
    http_result,
    *,
    surface: str | None,
    traversal_mode: str | None,
    requested_fields: list[str] | None,
) -> AcquisitionExecutionDecision:
    normalized_surface = normalize_surface(surface)
    if should_force_browser_for_traversal(traversal_mode):
        return AcquisitionExecutionDecision(
            runtime="playwright_attempt_required",
            reason="traversal_requested",
            fallback_allowed=True,
            expected_evidence=("traversal_summary",),
        )

    escalation = browser_escalation_decision(
        http_result,
        surface=surface,
        requested_fields=requested_fields,
    )
    if escalation.needs_browser:
        expected_evidence: tuple[str, ...] = ()
        if normalized_surface == "ecommerce_listing":
            expected_evidence = ("listing_completeness",)
        elif normalized_surface == "ecommerce_detail":
            expected_evidence = ("variant_completeness",)
        return AcquisitionExecutionDecision(
            runtime="playwright_attempt_required",
            reason=escalation.reason,
            fallback_allowed=True,
            expected_evidence=expected_evidence,
        )

    return AcquisitionExecutionDecision(
        runtime="curl",
        reason="http_sufficient",
        fallback_allowed=False,
        expected_evidence=(),
    )


def has_requested_traversal_mode(traversal_mode: str | None) -> bool:
    normalized_mode = normalize_surface(traversal_mode)
    return normalized_mode in {"auto", "scroll", "load_more", "paginate"}


def should_force_browser_for_traversal(traversal_mode: str | None) -> bool:
    normalized_mode = normalize_surface(traversal_mode)
    return normalized_mode in {"scroll", "load_more", "paginate"}


def resolve_traversal_surface_policy(
    surface: str | None,
) -> TraversalSurfacePolicy:
    normalized_surface = normalize_surface(surface)
    is_detail_surface = normalized_surface.endswith("_detail")
    return TraversalSurfacePolicy(
        surface=surface,
        normalized_surface=normalized_surface,
        is_listing_surface=normalized_surface.endswith("_listing"),
        is_detail_surface=is_detail_surface,
        card_selectors=(
            CARD_SELECTORS_JOBS
            if "job" in normalized_surface
            else CARD_SELECTORS_COMMERCE
        ),
        traversal_disabled_reason="detail_surface" if is_detail_surface else None,
    )


def decide_initial_auto_traversal(
    next_page_signal: dict[str, object] | None,
    infinite_scroll_signals: dict[str, object] | None,
) -> AutoTraversalDecision:
    if not next_page_signal:
        return AutoTraversalDecision(
            decision="progress_first",
            should_paginate_now=False,
        )
    if bool((infinite_scroll_signals or {}).get("is_likely_infinite_scroll")):
        return AutoTraversalDecision(
            decision="hybrid_progress_first",
            should_paginate_now=False,
        )
    return AutoTraversalDecision(
        decision="paginate_first",
        should_paginate_now=True,
    )


def decide_post_progress_auto_traversal(
    next_page_signal: dict[str, object] | None,
) -> str:
    if next_page_signal:
        return "progress_then_paginate"
    return "progress_without_pagination"


def normalize_traversal_summary(
    summary: dict[str, object],
    *,
    traversal_mode: str | None,
    combined_html: str | None,
) -> dict[str, object]:
    normalized = dict(summary or {})
    mode_used = (
        str(
            normalized.get("mode_used")
            or normalized.get("mode")
            or traversal_mode
            or ""
        ).strip()
        or None
    )
    pages_collected = int(
        normalized.get("pages_collected", 0)
        or (
            str(combined_html or "").count("<!-- PAGE BREAK:")
            if combined_html
            else 0
        )
    )
    stop_reason = str(normalized.get("stop_reason") or "").strip() or None
    fallback_used = bool(normalized.get("fallback_used"))
    scroll_iterations = int(
        normalized.get("scroll_iterations") or normalized.get("attempt_count") or 0
    )
    normalized["mode_used"] = mode_used
    normalized["pages_collected"] = pages_collected
    normalized["scroll_iterations"] = scroll_iterations
    normalized["stop_reason"] = stop_reason
    normalized["fallback_used"] = fallback_used
    return {key: value for key, value in normalized.items() if value is not None}


def browser_failure_log_message(
    traversal_mode: str | None,
    exc: Exception,
    *,
    failure_class: str,
    failure_origin: str,
) -> str:
    prefix = (
        "[traversal] Browser acquisition failed, falling back to curl"
        if has_requested_traversal_mode(traversal_mode)
        else "Browser acquisition failed"
    )
    return (
        f"{prefix} [{failure_class}/{failure_origin}]: "
        f"{type(exc).__name__}: {exc}"
    )


def should_retry_browser_launch_profile(
    result,
    *,
    surface: str | None,
    html_looks_low_value: Callable[[str], bool],
) -> bool:
    result_html = str(getattr(result, "html", "") or "")
    diagnostics = (
        result.diagnostics
        if isinstance(getattr(result, "diagnostics", None), dict)
        else {}
    )
    if detect_blocked_page(result_html).is_blocked:
        return True
    normalized_surface = normalize_surface(surface)
    if not normalized_surface.endswith("_listing"):
        return False
    readiness = diagnostics.get("listing_readiness")
    return bool(
        isinstance(readiness, dict)
        and (not bool(readiness.get("ready")) or bool(readiness.get("shell_like")))
        and html_looks_low_value(result_html)
    )


def is_invalid_surface_page(
    *,
    requested_url: str,
    final_url: str,
    html: str,
    surface: str | None,
    soup: BeautifulSoup | None = None,
) -> bool:
    commerce_warning = diagnose_commerce_surface_page(
        requested_url=requested_url,
        final_url=final_url,
        surface=surface,
        html=html,
        soup=soup,
    )
    if commerce_warning is not None and bool(
        set((commerce_warning or {}).get("signals") or [])
        & {
            "redirected_to_root",
            "redirect_shell_title",
            "transactional_url",
            "transactional_page_title",
            "noindex_transactional_page",
        }
    ):
        return True
    job_warning = diagnose_job_surface_page(
        requested_url=requested_url,
        final_url=final_url,
        html=html,
        surface=surface,
        soup=soup,
    )
    if job_warning is not None:
        signals = set(job_warning.get("signals") or [])
        if signals & {
            "redirect_shell_title",
            "redirect_shell_canonical",
            "auth_wall_heading",
            "redirected_to_root",
        }:
            return True
    return False


def surface_selection_warnings(
    *,
    requested_url: str,
    final_url: str,
    html: str,
    surface: str | None,
    soup: BeautifulSoup | None = None,
) -> list[dict[str, object]]:
    warnings: list[dict[str, object]] = []
    commerce_warning = diagnose_commerce_surface_page(
        requested_url=requested_url,
        final_url=final_url,
        html=html,
        surface=surface,
        soup=soup,
    )
    if commerce_warning is not None:
        warnings.append(commerce_warning)
    job_warning = diagnose_job_surface_page(
        requested_url=requested_url,
        final_url=final_url,
        html=html,
        surface=surface,
        soup=soup,
    )
    if job_warning is not None:
        warnings.append(job_warning)
    return warnings


def _is_redirect_to_root(requested_url: str, final_url: str) -> bool:
    requested = urlparse(requested_url)
    final = urlparse(final_url or requested_url)
    return (
        bool(final_url)
        and requested.netloc.lower() == final.netloc.lower()
        and requested.path.rstrip("/") != final.path.rstrip("/")
        and final.path.rstrip("/") == ""
    )


def surface_warning_summary(
    warnings: list[dict[str, object]] | None,
) -> dict[str, bool | None]:
    signals = {
        str(signal).strip()
        for warning in (warnings or [])
        if isinstance(warning, dict)
        for signal in (warning.get("signals") or [])
        if str(signal).strip()
    }
    return {
        "soft_404_page": True
        if signals & {"soft_404_title", "soft_404_heading"}
        else None,
        "transactional_page": True
        if signals
        & {
            "transactional_url",
            "transactional_page_title",
            "noindex_transactional_page",
        }
        else None,
    }


def diagnose_commerce_surface_page(
    *,
    requested_url: str,
    final_url: str,
    html: str,
    surface: str | None,
    soup: BeautifulSoup | None = None,
) -> dict[str, object] | None:
    normalized_surface = normalize_surface(surface)
    if normalized_surface not in {"ecommerce_listing", "ecommerce_detail"}:
        return None
    redirected_to_root = _is_redirect_to_root(requested_url, final_url)
    if not html and not redirected_to_root:
        return None
    warning_signals: list[str] = []
    if redirected_to_root:
        warning_signals.append("redirected_to_root")
    if _looks_like_commerce_transaction_url(final_url or requested_url):
        warning_signals.append("transactional_url")
    if not html:
        return {
            "surface_requested": normalized_surface,
            "warning": "surface_selection_may_be_low_confidence",
            "signals": warning_signals,
            "requested_url": requested_url,
            "final_url": final_url or requested_url,
        } if warning_signals else None

    soup = soup or BeautifulSoup(html, HTML_PARSER)
    title_text = " ".join(
        (soup.title.get_text(" ", strip=True) if soup.title else "").lower().split()
    )
    canonical_url = str(
        (soup.select_one("link[rel='canonical']") or {}).get("href", "")
    ).strip()
    headings = {
        " ".join(node.get_text(" ", strip=True).lower().split())
        for node in soup.select("h1, [role='heading']")
        if node.get_text(" ", strip=True)
    }
    robots_values = {
        " ".join(str(node.get("content") or "").lower().split())
        for node in soup.select("meta[name='robots'], meta[name='googlebot']")
        if str(node.get("content") or "").strip()
    }
    if any(fragment in title_text for fragment in _COMMERCE_REDIRECT_TITLE_FRAGMENTS):
        warning_signals.append("redirect_shell_title")
    if title_text in _COMMERCE_SOFT_404_TITLES:
        warning_signals.append("soft_404_title")
    if any(heading in _COMMERCE_SOFT_404_HEADINGS for heading in headings):
        warning_signals.append("soft_404_heading")
    if any(fragment in title_text for fragment in _COMMERCE_TRANSACTIONAL_TITLE_FRAGMENTS):
        warning_signals.append("transactional_page_title")
    if (
        "transactional_url" in warning_signals
        and any("noindex" in value and "nofollow" in value for value in robots_values)
    ):
        warning_signals.append("noindex_transactional_page")
    if not warning_signals:
        return None
    return {
        "surface_requested": normalized_surface,
        "warning": "surface_selection_may_be_low_confidence",
        "signals": warning_signals,
        "requested_url": requested_url,
        "final_url": final_url or requested_url,
        "title": title_text or None,
        "canonical_url": canonical_url or None,
    }


def diagnose_job_surface_page(
    *,
    requested_url: str,
    final_url: str,
    html: str,
    surface: str | None,
    soup: BeautifulSoup | None = None,
) -> dict[str, object] | None:
    normalized_surface = normalize_surface(surface)
    if normalized_surface not in {"job_listing", "job_detail"}:
        return None
    redirected_to_root = _is_redirect_to_root(requested_url, final_url)
    if not html and not redirected_to_root:
        return None
    warning_signals: list[str] = []
    if redirected_to_root:
        warning_signals.append("redirected_to_root")
    if not html:
        return {
            "surface_requested": normalized_surface,
            "warning": "surface_selection_may_be_low_confidence",
            "signals": warning_signals,
            "requested_url": requested_url,
            "final_url": final_url or requested_url,
        } if warning_signals else None

    soup = soup or BeautifulSoup(html, HTML_PARSER)
    title_text = " ".join(
        (soup.title.get_text(" ", strip=True) if soup.title else "").lower().split()
    )
    canonical_url = str(
        (soup.select_one("link[rel='canonical']") or {}).get("href", "")
    ).strip()
    headings = {
        " ".join(node.get_text(" ", strip=True).lower().split())
        for node in soup.select("h1, [role='heading']")
        if node.get_text(" ", strip=True)
    }
    if title_text in JOB_REDIRECT_SHELL_TITLES:
        warning_signals.append("redirect_shell_title")
    if canonical_url in JOB_REDIRECT_SHELL_CANONICAL_URLS:
        warning_signals.append("redirect_shell_canonical")
    if title_text in JOB_ERROR_PAGE_TITLES:
        warning_signals.append("error_page_title")
    if headings & JOB_REDIRECT_SHELL_HEADINGS:
        warning_signals.append("redirect_shell_heading")
    if headings & JOB_ERROR_PAGE_HEADINGS:
        warning_signals.append("auth_wall_heading")
    if not warning_signals:
        return None
    return {
        "surface_requested": normalized_surface,
        "warning": "surface_selection_may_be_low_confidence",
        "signals": warning_signals,
        "requested_url": requested_url,
        "final_url": final_url or requested_url,
        "title": title_text or None,
        "canonical_url": canonical_url or None,
    }


def _looks_like_commerce_transaction_url(url: str) -> bool:
    parsed = urlparse(url or "")
    path_tokens = {
        token
        for token in parsed.path.lower().split("/")
        if token
    }
    if path_tokens & _COMMERCE_TRANSACTIONAL_PATH_TOKENS:
        return True
    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    for key, value in query_pairs:
        key_norm = key.strip().lower()
        value_norm = value.strip().lower()
        if key_norm == "action" and value_norm in _COMMERCE_TRANSACTIONAL_ACTION_VALUES:
            return True
        if key_norm in {"cartaction", "checkoutaction"} and value_norm:
            return True
    return False
