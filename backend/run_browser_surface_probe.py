from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from ipaddress import ip_address
from pathlib import Path

import pytz

from app.core.database import SessionLocal
from app.services.acquisition.browser_runtime import (
    SharedBrowserRuntime,
    _display_proxy,
    get_browser_runtime,
    shutdown_browser_runtime,
)
from app.services.config.browser_surface_probe import (
    BROWSER_SURFACE_PROBE_CREEPJS_LABELS,
    BROWSER_SURFACE_PROBE_HIGH_ENTROPY_HINTS,
    BROWSER_SURFACE_PROBE_KEYWORD_GROUPS,
    BROWSER_SURFACE_PROBE_NEIGHBOR_LINE_WINDOW,
    BROWSER_SURFACE_PROBE_PIXELSCAN_LABELS,
    BROWSER_SURFACE_PROBE_POST_NAVIGATION_WAIT_MS,
    BROWSER_SURFACE_PROBE_REQUEST_DELAY_MS,
    BROWSER_SURFACE_PROBE_RETRY_BACKOFF_MS,
    BROWSER_SURFACE_PROBE_SITE_MAX_RETRIES,
    BROWSER_SURFACE_PROBE_RISK_TOKENS,
    BROWSER_SURFACE_PROBE_SAFE_TOKENS,
    BROWSER_SURFACE_PROBE_SANNYSOFT_LABELS,
    BROWSER_SURFACE_PROBE_TABLE_ROW_LIMIT,
    BROWSER_SURFACE_PROBE_TARGETS,
    BROWSER_SURFACE_PROBE_TIMEZONE_ALIASES,
    BROWSER_SURFACE_PROBE_VISIBLE_TEXT_LIMIT,
    BROWSER_SURFACE_PROBE_WEBRTC_GATHER_TIMEOUT_MS,
)
from app.services.crawl_crud import get_run

_BROWSER_VERSION_RE = re.compile(
    r"\b(?:Chrome|Chromium|Edg|Firefox|HeadlessChrome)/(\d+)", re.IGNORECASE
)
_IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_WHITESPACE_RE = re.compile(r"\s+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_COUNTRY_CODE_BY_NAME = {
    _NON_ALNUM_RE.sub(" ", name.lower()).strip(): code
    for code, name in pytz.country_names.items()
}
_COUNTRY_CODE_BY_NAME.update(
    {
        "uk": "GB",
        "united kingdom": "GB",
        "usa": "US",
        "u s a": "US",
        "united states": "US",
        "united states of america": "US",
    }
)
_BUNDLE_DIRNAME = "browser_surface_probe"
logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RuntimeSource:
    source_kind: str
    run_id: int | None
    identity_run_id: int
    proxy_list: list[str]
    proxy_profile: dict[str, object]
    selected_proxy: str | None
    selected_proxy_index: int | None
    browser_engine: str


def _normalize_space(value: object) -> str:
    return _WHITESPACE_RE.sub(" ", str(value or "")).strip()


def _normalize_key(value: object) -> str:
    return _NON_ALNUM_RE.sub(" ", _normalize_space(value).lower()).strip()


def _json_dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True, default=str)


def _utc_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _coerce_proxy_profile(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


async def _load_run_runtime_source(run_id: int, *, browser_engine: str) -> RuntimeSource:
    async with SessionLocal() as session:
        run = await get_run(session, run_id)
    if run is None:
        raise ValueError(f"Run {run_id} not found")
    settings_view = run.settings_view
    proxy_list = settings_view.proxy_list()
    proxy_profile = settings_view.proxy_profile()
    enabled = bool(proxy_profile.get("enabled"))
    selected_proxy = proxy_list[0] if enabled and proxy_list else None
    selected_proxy_index = 0 if selected_proxy is not None else None
    return RuntimeSource(
        source_kind="run",
        run_id=run.id,
        identity_run_id=run.id,
        proxy_list=proxy_list,
        proxy_profile=proxy_profile,
        selected_proxy=selected_proxy,
        selected_proxy_index=selected_proxy_index,
        browser_engine=browser_engine,
    )


def _load_explicit_runtime_source(
    *,
    proxies: list[str],
    proxy_profile_path: str | None,
    browser_engine: str,
) -> RuntimeSource:
    proxy_profile: dict[str, object] = {}
    if proxy_profile_path:
        raw = json.loads(Path(proxy_profile_path).read_text(encoding="utf-8"))
        proxy_profile = _coerce_proxy_profile(raw)
    proxy_list = [_normalize_space(value) for value in proxies if _normalize_space(value)]
    enabled = bool(proxy_list) or bool(proxy_profile.get("enabled"))
    if enabled:
        proxy_profile = dict(proxy_profile)
        proxy_profile["enabled"] = True
        proxy_profile["proxy_list"] = proxy_list
    selected_proxy = proxy_list[0] if proxy_list else None
    selected_proxy_index = 0 if selected_proxy is not None else None
    identity_run_id = time.time_ns()
    return RuntimeSource(
        source_kind="explicit_proxy" if proxy_list else "direct",
        run_id=None,
        identity_run_id=identity_run_id,
        proxy_list=proxy_list,
        proxy_profile=proxy_profile,
        selected_proxy=selected_proxy,
        selected_proxy_index=selected_proxy_index,
        browser_engine=browser_engine,
    )


async def _resolve_runtime_source(args: argparse.Namespace) -> RuntimeSource:
    explicit_proxies = list(args.proxy or [])
    if args.run_id is not None and (explicit_proxies or args.proxy_profile_json):
        raise ValueError("Provide either --run-id or explicit proxy flags, not both")
    if args.run_id is not None:
        return await _load_run_runtime_source(args.run_id, browser_engine=args.browser_engine)
    return _load_explicit_runtime_source(
        proxies=explicit_proxies,
        proxy_profile_path=args.proxy_profile_json,
        browser_engine=args.browser_engine,
    )


def _masked_proxy_inventory(proxy_list: list[str]) -> list[str]:
    return [_display_proxy(value) for value in proxy_list]


def _report_root(base_dir: str | None) -> Path:
    base = Path(base_dir) if base_dir else Path(__file__).resolve().parent / "artifacts" / _BUNDLE_DIRNAME
    return base


def _extract_versions(values: list[str]) -> list[int]:
    versions: list[int] = []
    for value in values:
        for match in _BROWSER_VERSION_RE.findall(str(value or "")):
            try:
                versions.append(int(match))
            except ValueError:
                continue
    return sorted(set(versions))


def _extract_ip_values(values: list[str]) -> list[str]:
    ips: list[str] = []
    for value in values:
        for match in _IP_RE.findall(str(value or "")):
            try:
                parsed = ip_address(match)
            except ValueError:
                continue
            if parsed.version == 4:
                ips.append(match)
    return sorted(set(ips))


def _clean_ip_values(values: list[str], *, known_versions: list[int] | None = None) -> list[str]:
    version_set = {int(value) for value in list(known_versions or [])}
    cleaned: list[str] = []
    for value in values:
        octets = str(value).split(".")
        if len(octets) == 4 and octets[1:] == ["0", "0", "0"]:
            try:
                if int(octets[0]) in version_set:
                    continue
            except ValueError:
                pass
        cleaned.append(value)
    return sorted(set(cleaned))


def _looks_like_truthy_risk(value: str) -> bool:
    lowered = _normalize_space(value).lower()
    if not lowered:
        return False
    if any(token in lowered for token in BROWSER_SURFACE_PROBE_SAFE_TOKENS):
        return False
    if any(token in lowered for token in BROWSER_SURFACE_PROBE_RISK_TOKENS):
        return True
    percent_matches = re.findall(r"(\d+(?:\.\d+)?)%", lowered)
    for match in percent_matches:
        try:
            if float(match) > 0:
                return True
        except ValueError:
            continue
    return False


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        normalized = _normalize_space(value)
        if not normalized:
            continue
        lowered = normalized.casefold()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(normalized)
    return deduped


def _flatten_signal_values(payload: object) -> list[str]:
    if isinstance(payload, str):
        normalized = _normalize_space(payload)
        return [normalized] if normalized else []
    if isinstance(payload, dict):
        flattened: list[str] = []
        for value in payload.values():
            flattened.extend(_flatten_signal_values(value))
        return flattened
    if isinstance(payload, list):
        flattened = []
        for value in payload:
            flattened.extend(_flatten_signal_values(value))
        return flattened
    return []


def _label_alias_set(label_map: dict[str, tuple[str, ...]]) -> set[str]:
    aliases: set[str] = set()
    for values in label_map.values():
        aliases.update(_normalize_key(value) for value in values)
    return aliases


def _extract_labeled_values(
    lines: list[str],
    label_map: dict[str, tuple[str, ...]],
) -> dict[str, list[str]]:
    normalized_lines = [_normalize_space(value) for value in lines if _normalize_space(value)]
    aliases = _label_alias_set(label_map)
    extracted: dict[str, list[str]] = {}
    for key, raw_aliases in label_map.items():
        values: list[str] = []
        aliases_for_key = [_normalize_key(value) for value in raw_aliases]
        for index, line in enumerate(normalized_lines):
            normalized_line = _normalize_key(line)
            if not any(alias and alias in normalized_line for alias in aliases_for_key):
                continue
            if ":" in line:
                _, raw_value = line.split(":", 1)
                normalized_value = _normalize_space(raw_value)
                if normalized_value:
                    values.append(normalized_value)
                    continue
            upper_bound = min(
                len(normalized_lines),
                index + 1 + int(BROWSER_SURFACE_PROBE_NEIGHBOR_LINE_WINDOW),
            )
            for candidate in normalized_lines[index + 1 : upper_bound]:
                candidate_key = _normalize_key(candidate)
                if not candidate_key or candidate_key in aliases:
                    continue
                values.append(candidate)
                break
        if values:
            extracted[key] = _dedupe(values)
    return extracted


def _extract_keyword_hits(lines: list[str], keyword_group: str) -> list[str]:
    keywords = BROWSER_SURFACE_PROBE_KEYWORD_GROUPS.get(keyword_group, ())
    hits = [
        _normalize_space(line)
        for line in lines
        if any(keyword in _normalize_space(line).lower() for keyword in keywords)
    ]
    return _dedupe(hits)


async def _collect_page_snapshot(page) -> dict[str, object]:
    return await page.evaluate(
        """(limits) => {
            const normalize = (value) => (value || '').replace(/\\s+/g, ' ').trim();
            const rawBodyText = document.body ? (document.body.innerText || '') : '';
            const lines = rawBodyText
                .split(/\\n+/)
                .map((line) => normalize(line))
                .filter(Boolean)
                .slice(0, limits.textLineLimit);
            const rows = Array.from(document.querySelectorAll('tr'))
                .map((row) => {
                    const cells = Array.from(row.querySelectorAll('th, td'))
                        .map((cell) => normalize(cell.innerText || cell.textContent || ''))
                        .filter(Boolean);
                    if (!cells.length) {
                        return null;
                    }
                    return {
                        cells,
                        label: cells[0] || '',
                        value: cells.slice(1).join(' | '),
                    };
                })
                .filter(Boolean)
                .slice(0, limits.tableRowLimit);
            return {
                body_text: normalize(rawBodyText),
                lines,
                line_count: lines.length,
                rows,
                has_creep_object: typeof window.Creep !== 'undefined',
                has_fingerprint_object: typeof window.Fingerprint !== 'undefined',
            };
        }""",
        {
            "textLineLimit": int(BROWSER_SURFACE_PROBE_VISIBLE_TEXT_LIMIT),
            "tableRowLimit": int(BROWSER_SURFACE_PROBE_TABLE_ROW_LIMIT),
        },
    )


async def _collect_baseline(page) -> dict[str, object]:
    return await page.evaluate(
        """async (input) => {
            const normalize = (value) => (value == null ? '' : String(value)).replace(/\\s+/g, ' ').trim();
            const collectWebGL = () => {
                try {
                    const canvas = document.createElement('canvas');
                    const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
                    if (!gl) {
                        return { vendor: null, renderer: null };
                    }
                    const extension = gl.getExtension('WEBGL_debug_renderer_info');
                    return {
                        vendor: extension ? gl.getParameter(extension.UNMASKED_VENDOR_WEBGL) : gl.getParameter(gl.VENDOR),
                        renderer: extension ? gl.getParameter(extension.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER),
                    };
                } catch (_error) {
                    return { vendor: null, renderer: null };
                }
            };
            const collectWebRTCIps = async () => {
                const discovered = new Set();
                const AnyPeer = window.RTCPeerConnection || window.webkitRTCPeerConnection || window.mozRTCPeerConnection;
                if (!AnyPeer) {
                    return [];
                }
                let peer;
                try {
                    peer = new AnyPeer({ iceServers: [] });
                    peer.createDataChannel('probe');
                    peer.onicecandidate = (event) => {
                        const candidate = event && event.candidate && event.candidate.candidate;
                        if (!candidate) {
                            return;
                        }
                        const matches = candidate.match(/(\\d{1,3}(?:\\.\\d{1,3}){3})/g) || [];
                        for (const match of matches) {
                            discovered.add(match);
                        }
                    };
                    const offer = await peer.createOffer();
                    await peer.setLocalDescription(offer);
                    await new Promise((resolve) => setTimeout(resolve, input.webrtcTimeoutMs));
                } catch (_error) {
                    return Array.from(discovered);
                } finally {
                    if (peer) {
                        try {
                            peer.close();
                        } catch (_error) {}
                    }
                }
                return Array.from(discovered);
            };
            const uaData = navigator.userAgentData
                ? await navigator.userAgentData
                    .getHighEntropyValues(input.highEntropyHints)
                    .catch(() => null)
                : null;
            const webgl = collectWebGL();
            return {
                user_agent: normalize(navigator.userAgent),
                user_agent_data: uaData,
                webdriver: navigator.webdriver === true,
                locale: normalize(navigator.language),
                languages: Array.isArray(navigator.languages) ? navigator.languages.map((value) => normalize(value)).filter(Boolean) : [],
                timezone: normalize(Intl.DateTimeFormat().resolvedOptions().timeZone),
                platform: normalize(navigator.platform),
                vendor: normalize(navigator.vendor),
                plugins_count: navigator.plugins ? navigator.plugins.length : 0,
                plugin_names: navigator.plugins ? Array.from(navigator.plugins).map((plugin) => normalize(plugin && plugin.name)).filter(Boolean).slice(0, 10) : [],
                hardware_concurrency: navigator.hardwareConcurrency || null,
                device_memory: navigator.deviceMemory ?? null,
                screen: {
                    width: window.screen.width,
                    height: window.screen.height,
                    avail_width: window.screen.availWidth,
                    avail_height: window.screen.availHeight,
                    color_depth: window.screen.colorDepth,
                    pixel_depth: window.screen.pixelDepth,
                    device_pixel_ratio: window.devicePixelRatio || 1,
                },
                viewport: {
                    width: window.innerWidth,
                    height: window.innerHeight,
                    outer_width: window.outerWidth,
                    outer_height: window.outerHeight,
                },
                webgl,
                webrtc_ips: await collectWebRTCIps(),
                timestamp: new Date().toISOString(),
            };
        }""",
        {
            "highEntropyHints": list(BROWSER_SURFACE_PROBE_HIGH_ENTROPY_HINTS),
            "webrtcTimeoutMs": int(BROWSER_SURFACE_PROBE_WEBRTC_GATHER_TIMEOUT_MS),
        },
    )


def _sannysoft_signal_rows(rows: list[dict[str, object]]) -> dict[str, object]:
    categorized: dict[str, list[dict[str, str]]] = {}
    failed_rows: list[dict[str, str]] = []
    for row in rows:
        label = _normalize_space(row.get("label"))
        value = _normalize_space(row.get("value"))
        row_payload = {"label": label, "value": value}
        normalized_label = _normalize_key(label)
        for key, aliases in BROWSER_SURFACE_PROBE_SANNYSOFT_LABELS.items():
            if any(_normalize_key(alias) in normalized_label for alias in aliases):
                categorized.setdefault(key, []).append(row_payload)
        if _looks_like_truthy_risk(value):
            failed_rows.append(row_payload)
    signal_values = _flatten_signal_values(categorized) + _flatten_signal_values(failed_rows)
    return {
        "matched_rows": categorized,
        "failed_rows": failed_rows,
        "signal_versions": _extract_versions(signal_values),
        "webdriver_hits": _flatten_signal_values(categorized.get("webdriver")),
        "headless_hits": [],
        "webrtc_hits": [],
        "screen_hits": _flatten_signal_values(categorized.get("screen")),
        "language_hits": _flatten_signal_values(categorized.get("languages")),
        "webgl_hits": _flatten_signal_values(categorized.get("webgl")),
    }


def _generic_line_signals(
    *,
    lines: list[str],
    label_map: dict[str, tuple[str, ...]],
) -> dict[str, object]:
    labeled = _extract_labeled_values(lines, label_map)
    all_values = _flatten_signal_values(labeled)
    return {
        "labeled_values": labeled,
        "keyword_hits": {
            key: _extract_keyword_hits(lines, key)
            for key in BROWSER_SURFACE_PROBE_KEYWORD_GROUPS
        },
        "signal_versions": _extract_versions(all_values),
        "ip_values": [],
    }


def _extract_pixelscan(snapshot: dict[str, object]) -> dict[str, object]:
    lines = [str(value) for value in list(snapshot.get("lines") or [])]
    payload = _generic_line_signals(lines=lines, label_map=BROWSER_SURFACE_PROBE_PIXELSCAN_LABELS)
    payload["country_values"] = _flatten_signal_values(payload["labeled_values"].get("country"))
    payload["ip_values"] = _clean_ip_values(
        _extract_ip_values(_flatten_signal_values(payload["labeled_values"].get("ip"))),
        known_versions=list(payload.get("signal_versions") or []),
    )
    payload["timezone_values"] = _flatten_signal_values(
        {
            "js_timezone": payload["labeled_values"].get("js_timezone"),
            "ip_time": payload["labeled_values"].get("ip_time"),
        }
    )
    payload["proxy_values"] = _flatten_signal_values(payload["labeled_values"].get("proxy_verdict"))
    payload["language_values"] = _flatten_signal_values(payload["labeled_values"].get("language_headers"))
    payload["screen_values"] = _flatten_signal_values(payload["labeled_values"].get("screen_size"))
    payload["webgl_values"] = _flatten_signal_values(payload["labeled_values"].get("webgl"))
    return payload


def _extract_creepjs(snapshot: dict[str, object]) -> dict[str, object]:
    lines = [str(value) for value in list(snapshot.get("lines") or [])]
    payload = _generic_line_signals(lines=lines, label_map=BROWSER_SURFACE_PROBE_CREEPJS_LABELS)
    payload["fp_id_values"] = _flatten_signal_values(payload["labeled_values"].get("fp_id"))
    payload["fuzzy_fp_id_values"] = _flatten_signal_values(
        payload["labeled_values"].get("fuzzy_fp_id")
    )
    payload["headless_hits"] = payload["keyword_hits"].get("headless", [])
    payload["webrtc_hits"] = payload["keyword_hits"].get("webrtc", [])
    payload["timezone_hits"] = payload["keyword_hits"].get("timezone", [])
    payload["screen_hits"] = payload["keyword_hits"].get("screen", [])
    payload["ip_values"] = _extract_ip_values(payload["webrtc_hits"])
    return payload


def _country_code_from_value(value: str | None) -> str | None:
    normalized = _normalize_key(value)
    if not normalized:
        return None
    if len(normalized) == 2 and normalized.isalpha():
        return normalized.upper()
    if normalized in _COUNTRY_CODE_BY_NAME:
        return _COUNTRY_CODE_BY_NAME[normalized]
    for country_name, country_code in _COUNTRY_CODE_BY_NAME.items():
        if country_name and country_name in normalized:
            return country_code
    return None


def _timezone_matches_country(timezone_name: str | None, country_code: str | None) -> bool | None:
    normalized_timezone = _normalize_space(timezone_name)
    normalized_timezone = str(
        BROWSER_SURFACE_PROBE_TIMEZONE_ALIASES.get(
            normalized_timezone,
            normalized_timezone,
        )
    )
    normalized_country = _normalize_space(country_code).upper()
    if not normalized_timezone or not normalized_country:
        return None
    timezone_list = tuple(pytz.country_timezones.get(normalized_country, ()))
    if not timezone_list:
        return None
    return normalized_timezone in timezone_list


def _locale_region(locale_value: str | None) -> str | None:
    normalized = _normalize_space(locale_value).replace("_", "-")
    if "-" not in normalized:
        return None
    _language, region = normalized.rsplit("-", 1)
    region = region.upper()
    return region if len(region) == 2 and region.isalpha() else None


def _coalesce(values: list[object]) -> object | None:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def _consensus_baseline(per_site: dict[str, dict[str, object]]) -> dict[str, object]:
    if not per_site:
        return {}
    keys = (
        "user_agent",
        "user_agent_data",
        "webdriver",
        "locale",
        "languages",
        "timezone",
        "platform",
        "vendor",
        "plugins_count",
        "plugin_names",
        "hardware_concurrency",
        "device_memory",
        "screen",
        "viewport",
        "webgl",
        "webrtc_ips",
    )
    consensus: dict[str, object] = {}
    drift: dict[str, list[object]] = {}
    for key in keys:
        values = [payload.get(key) for payload in per_site.values()]
        normalized_values = [value for value in values if value not in (None, "", [], {})]
        consensus[key] = _coalesce(normalized_values)
        unique_values = []
        seen_serialized: set[str] = set()
        for value in normalized_values:
            marker = json.dumps(value, sort_keys=True, default=str)
            if marker in seen_serialized:
                continue
            seen_serialized.add(marker)
            unique_values.append(value)
        if len(unique_values) > 1:
            drift[key] = unique_values
    return {
        "consensus": consensus,
        "per_site": per_site,
        "drift": drift,
    }


def build_findings(report: dict[str, object]) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    baseline = dict(report.get("baseline") or {})
    consensus = dict(baseline.get("consensus") or {})
    drift = dict(baseline.get("drift") or {})
    sites = dict(report.get("sites") or {})
    failed_probe_sites = [
        site_id
        for site_id, site_payload in sites.items()
        if dict(site_payload or {}).get("site_status") == "failed"
    ]
    degraded_probe_sites = [
        site_id
        for site_id, site_payload in sites.items()
        if dict(site_payload or {}).get("site_status") == "degraded"
    ]
    if failed_probe_sites:
        findings.append(
            {
                "severity": "warn",
                "category": "probe_site_failure",
                "message": "One or more browser surface probe sites failed; report is partial.",
                "evidence": failed_probe_sites,
            }
        )
    if degraded_probe_sites:
        findings.append(
            {
                "severity": "warn",
                "category": "probe_site_degraded",
                "message": "One or more browser surface probe extractors saw unexpected page structure.",
                "evidence": degraded_probe_sites,
            }
        )
    pixelscan = dict(sites.get("pixelscan") or {})
    sannysoft = dict(sites.get("sannysoft") or {})
    creepjs = dict(sites.get("creepjs") or {})

    pixelscan_country = _coalesce(
        list(dict(pixelscan.get("extracted") or {}).get("country_values") or [])
    )
    pixelscan_country_code = _country_code_from_value(str(pixelscan_country or ""))
    timezone_value = str(consensus.get("timezone") or "")
    timezone_country_match = _timezone_matches_country(timezone_value, pixelscan_country_code)
    if timezone_country_match is False:
        findings.append(
            {
                "severity": "fail",
                "category": "timezone_country_mismatch",
                "message": f"Timezone {timezone_value or 'unknown'} does not match Pixelscan country {pixelscan_country or 'unknown'}.",
                "evidence": {
                    "timezone": timezone_value,
                    "pixelscan_country": pixelscan_country,
                },
            }
        )

    locale_region = _locale_region(str(consensus.get("locale") or ""))
    if locale_region and pixelscan_country_code and locale_region != pixelscan_country_code:
        findings.append(
            {
                "severity": "warn",
                "category": "locale_region_drift",
                "message": f"Locale region {locale_region} drifts from Pixelscan country {pixelscan_country_code}.",
                "evidence": {
                    "locale": consensus.get("locale"),
                    "country": pixelscan_country,
                },
            }
        )

    baseline_versions = _extract_versions([str(consensus.get("user_agent") or "")])
    extracted_versions = []
    for site in sites.values():
        extracted_versions.extend(list(dict(site.get("extracted") or {}).get("signal_versions") or []))
    extracted_versions = sorted(set(int(value) for value in extracted_versions if isinstance(value, int)))
    if baseline_versions and extracted_versions and any(
        version not in baseline_versions for version in extracted_versions
    ):
        findings.append(
            {
                "severity": "fail",
                "category": "ua_version_drift",
                "message": "Reported browser versions drift across baseline and public checkers.",
                "evidence": {
                    "baseline_versions": baseline_versions,
                    "extracted_versions": extracted_versions,
                },
            }
        )

    webdriver_evidence: list[str] = []
    if bool(consensus.get("webdriver")):
        webdriver_evidence.append("baseline.navigator.webdriver=true")
    webdriver_evidence.extend(list(dict(sannysoft.get("extracted") or {}).get("webdriver_hits") or []))
    webdriver_evidence.extend(list(dict(creepjs.get("extracted") or {}).get("keyword_hits", {}).get("webdriver") or []))
    webdriver_evidence = [value for value in webdriver_evidence if _looks_like_truthy_risk(value)]
    if webdriver_evidence:
        findings.append(
            {
                "severity": "fail",
                "category": "webdriver_exposure",
                "message": "Public checks still see webdriver or automation signals.",
                "evidence": webdriver_evidence[:10],
            }
        )

    headless_evidence: list[str] = []
    headless_evidence.extend(list(dict(creepjs.get("extracted") or {}).get("headless_hits") or []))
    headless_evidence.extend(list(dict(creepjs.get("extracted") or {}).get("keyword_hits", {}).get("headless") or []))
    headless_evidence = [value for value in headless_evidence if _looks_like_truthy_risk(value)]
    if headless_evidence:
        findings.append(
            {
                "severity": "fail",
                "category": "headless_leakage",
                "message": "Headless or stealth leakage is visible in public checks.",
                "evidence": headless_evidence[:10],
            }
        )

    webrtc_ips = [str(value) for value in list(consensus.get("webrtc_ips") or []) if _normalize_space(value)]
    public_webrtc_ips: list[str] = []
    private_webrtc_ips: list[str] = []
    for value in webrtc_ips:
        try:
            parsed = ip_address(value)
        except ValueError:
            continue
        if parsed.is_loopback:
            continue
        if parsed.is_private:
            private_webrtc_ips.append(value)
        else:
            public_webrtc_ips.append(value)
    if public_webrtc_ips:
        findings.append(
            {
                "severity": "fail",
                "category": "webrtc_leakage",
                "message": "WebRTC exposed public IPs from the page context.",
                "evidence": public_webrtc_ips,
            }
        )
    elif private_webrtc_ips:
        findings.append(
            {
                "severity": "warn",
                "category": "webrtc_private_ip_visibility",
                "message": "WebRTC exposed private-network IPs from the page context.",
                "evidence": private_webrtc_ips,
            }
        )

    if "screen" in drift or "viewport" in drift:
        findings.append(
            {
                "severity": "fail",
                "category": "screen_viewport_drift",
                "message": "Screen or viewport values changed across the three checker sites.",
                "evidence": {
                    "screen": drift.get("screen"),
                    "viewport": drift.get("viewport"),
                },
            }
        )

    site_ips: list[str] = []
    site_countries: list[str] = []
    for site_payload in sites.values():
        extracted = dict(site_payload.get("extracted") or {})
        site_ips.extend(list(extracted.get("ip_values") or []))
        site_countries.extend(list(extracted.get("country_values") or []))
    public_site_ips: list[str] = []
    for value in site_ips:
        try:
            parsed = ip_address(value)
        except ValueError:
            continue
        if parsed.is_loopback or parsed.is_private or parsed.is_unspecified:
            continue
        public_site_ips.append(value)
    if len(set(public_site_ips)) > 1:
        findings.append(
            {
                "severity": "warn",
                "category": "cross_site_ip_drift",
                "message": "Different public IPs were reported inside the same fingerprint run.",
                "evidence": sorted(set(public_site_ips)),
            }
        )
    if len({_country_code_from_value(value) for value in site_countries if _country_code_from_value(value)}) > 1:
        findings.append(
            {
                "severity": "warn",
                "category": "cross_site_country_drift",
                "message": "Different countries were reported inside the same fingerprint run.",
                "evidence": _dedupe(site_countries),
            }
        )

    if not findings:
        findings.append(
            {
                "severity": "info",
                "category": "no_risky_drift_detected",
                "message": "No risky fingerprint drift was detected by current rules.",
                "evidence": [],
            }
        )
    return findings


def _site_artifacts(base_dir: Path, site_id: str) -> dict[str, Path]:
    return {
        "screenshot": base_dir / f"{site_id}.png",
        "html": base_dir / f"{site_id}.html",
    }


def _site_signal_payload(site_id: str, snapshot: dict[str, object]) -> dict[str, object]:
    if site_id == "sannysoft":
        return _sannysoft_signal_rows(list(snapshot.get("rows") or []))
    if site_id == "pixelscan":
        return _extract_pixelscan(snapshot)
    if site_id == "creepjs":
        return _extract_creepjs(snapshot)
    return {}


async def _navigate_probe_target(page, url: str) -> None:
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    for state, timeout_ms in (("load", 10000), ("networkidle", 8000)):
        try:
            await page.wait_for_load_state(state, timeout=timeout_ms)
        except Exception:
            continue
    await page.wait_for_timeout(int(BROWSER_SURFACE_PROBE_POST_NAVIGATION_WAIT_MS))


async def _capture_probe_artifacts(page, artifacts: dict[str, Path]) -> None:
    try:
        await page.screenshot(path=str(artifacts["screenshot"]), full_page=True)
    except Exception:
        pass
    try:
        artifacts["html"].write_text(await page.content(), encoding="utf-8")
    except Exception:
        pass


def _site_validation_warnings(site_id: str, snapshot: dict[str, object]) -> list[str]:
    lines = list(snapshot.get("lines") or [])
    rows = list(snapshot.get("rows") or [])
    warnings: list[str] = []
    if not lines and not rows:
        warnings.append("no_visible_text_or_rows")
    if site_id == "sannysoft" and not rows:
        warnings.append("missing_sannysoft_rows")
    if site_id == "creepjs" and not bool(snapshot.get("has_creep_object")):
        warnings.append("missing_creepjs_object")
    return warnings


def _failed_site_payload(
    *,
    site_id: str,
    site_label: str,
    url: str,
    artifacts: dict[str, Path],
    attempts: int,
    error: str,
) -> dict[str, object]:
    return {
        "site_id": site_id,
        "label": site_label,
        "url": url,
        "site_status": "failed",
        "attempts": attempts,
        "error": error,
        "error_message": error,
        "artifacts": {
            "screenshot": artifacts["screenshot"].name if artifacts["screenshot"].exists() else None,
            "html": artifacts["html"].name if artifacts["html"].exists() else None,
        },
        "baseline": {},
        "snapshot_summary": {},
        "extracted": {},
    }


async def _probe_site(
    runtime: SharedBrowserRuntime,
    *,
    site_id: str,
    site_label: str,
    url: str,
    run_id: int,
    artifacts_dir: Path,
) -> dict[str, object]:
    artifacts = _site_artifacts(artifacts_dir, site_id)
    max_attempts = max(1, int(BROWSER_SURFACE_PROBE_SITE_MAX_RETRIES) + 1)
    last_error = ""
    for attempt in range(1, max_attempts + 1):
        try:
            async with runtime.page(run_id=run_id, allow_storage_state=False) as page:
                try:
                    await _navigate_probe_target(page, url)
                    baseline = await _collect_baseline(page)
                    snapshot = await _collect_page_snapshot(page)
                    html = await page.content()
                    await page.screenshot(path=str(artifacts["screenshot"]), full_page=True)
                    artifacts["html"].write_text(html, encoding="utf-8")
                    extracted = _site_signal_payload(site_id, snapshot)
                    validation_warnings = _site_validation_warnings(site_id, snapshot)
                    return {
                        "site_id": site_id,
                        "label": site_label,
                        "url": url,
                        "site_status": "degraded" if validation_warnings else "ok",
                        "attempts": attempt,
                        "validation_warnings": validation_warnings,
                        "final_url": _normalize_space(page.url),
                        "title": _normalize_space(await page.title()),
                        "artifacts": {
                            "screenshot": artifacts["screenshot"].name,
                            "html": artifacts["html"].name,
                        },
                        "baseline": baseline,
                        "snapshot_summary": {
                            "line_count": snapshot.get("line_count", 0),
                            "lines": list(snapshot.get("lines") or []),
                            "rows": list(snapshot.get("rows") or []),
                            "has_creep_object": bool(snapshot.get("has_creep_object")),
                            "has_fingerprint_object": bool(snapshot.get("has_fingerprint_object")),
                        },
                        "extracted": extracted,
                    }
                except Exception:
                    await _capture_probe_artifacts(page, artifacts)
                    raise
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "Browser surface probe failed site=%s attempt=%s/%s: %s",
                site_id,
                attempt,
                max_attempts,
                last_error,
            )
            if attempt < max_attempts:
                backoff_ms = max(0, int(BROWSER_SURFACE_PROBE_RETRY_BACKOFF_MS))
                if backoff_ms:
                    await asyncio.sleep((backoff_ms * attempt) / 1000)
    return _failed_site_payload(
        site_id=site_id,
        site_label=site_label,
        url=url,
        artifacts=artifacts,
        attempts=max_attempts,
        error=last_error or "unknown probe failure",
    )


def _render_markdown(report: dict[str, object]) -> str:
    metadata = dict(report.get("metadata") or {})
    baseline = dict(report.get("baseline") or {})
    consensus = dict(baseline.get("consensus") or {})
    findings = list(report.get("findings") or [])
    sites = dict(report.get("sites") or {})

    lines = [
        "# Browser Fingerprint Report",
        "",
        f"- Generated: {metadata.get('generated_at')}",
        f"- Engine: {metadata.get('browser_engine')}",
        f"- Source: {metadata.get('source_kind')}",
        f"- Selected proxy: {metadata.get('selected_proxy_mask')}",
        f"- Proxy inventory: {', '.join(list(metadata.get('proxy_inventory_masked') or [])) or 'direct'}",
        "",
        "## Findings",
    ]
    for finding in findings:
        lines.append(
            f"- {str(finding.get('severity') or '').upper()}: {finding.get('message')}"
        )
    lines.extend(
        [
            "",
            "## Baseline",
            f"- User-Agent: {consensus.get('user_agent')}",
            f"- Locale: {consensus.get('locale')}",
            f"- Languages: {', '.join(list(consensus.get('languages') or []))}",
            f"- Timezone: {consensus.get('timezone')}",
            f"- Webdriver: {consensus.get('webdriver')}",
            f"- Screen: {json.dumps(consensus.get('screen'), sort_keys=True)}",
            f"- Viewport: {json.dumps(consensus.get('viewport'), sort_keys=True)}",
            f"- WebGL: {json.dumps(consensus.get('webgl'), sort_keys=True)}",
            f"- WebRTC IPs: {', '.join(list(consensus.get('webrtc_ips') or [])) or 'none'}",
            "",
            "## Sites",
        ]
    )
    for site_id, site_payload in sites.items():
        lines.extend(
            [
                f"### {site_payload.get('label')}",
                f"- URL: {site_payload.get('final_url') or site_payload.get('url')}",
                f"- Status: {site_payload.get('site_status') or 'unknown'}",
                f"- Attempts: {site_payload.get('attempts') or 0}",
                f"- Title: {site_payload.get('title') or site_payload.get('error') or ''}",
                f"- Screenshot: {dict(site_payload.get('artifacts') or {}).get('screenshot')}",
                f"- HTML: {dict(site_payload.get('artifacts') or {}).get('html')}",
            ]
        )
        extracted = dict(site_payload.get("extracted") or {})
        interesting_keys = (
            "matched_rows",
            "failed_rows",
            "labeled_values",
            "keyword_hits",
            "fp_id_values",
            "fuzzy_fp_id_values",
            "country_values",
            "ip_values",
            "proxy_values",
        )
        for key in interesting_keys:
            value = extracted.get(key)
            if value in (None, "", [], {}):
                continue
            lines.append(f"- {key}: {json.dumps(value, sort_keys=True)}")
        if site_id != list(sites.keys())[-1]:
            lines.append("")
    return "\n".join(lines).strip() + "\n"


async def build_report(
    *,
    runtime_source: RuntimeSource,
    report_dir: Path,
    runtime_provider=get_browser_runtime,
) -> dict[str, object]:
    report_dir.mkdir(parents=True, exist_ok=True)
    runtime = await runtime_provider(
        proxy=runtime_source.selected_proxy,
        browser_engine=runtime_source.browser_engine,
    )
    sites: dict[str, dict[str, object]] = {}
    for index, target in enumerate(BROWSER_SURFACE_PROBE_TARGETS):
        site_payload = await _probe_site(
            runtime,
            site_id=str(target["id"]),
            site_label=str(target["label"]),
            url=str(target["url"]),
            run_id=runtime_source.identity_run_id,
            artifacts_dir=report_dir,
        )
        sites[str(target["id"])] = site_payload
        delay_ms = max(0, int(BROWSER_SURFACE_PROBE_REQUEST_DELAY_MS))
        if delay_ms and index < len(BROWSER_SURFACE_PROBE_TARGETS) - 1:
            await asyncio.sleep(delay_ms / 1000)
    baseline = _consensus_baseline(
        {
            site_id: dict(site_payload.get("baseline") or {})
            for site_id, site_payload in sites.items()
            if isinstance(site_payload, dict)
        }
    )
    site_statuses = {
        site_id: str(site_payload.get("site_status") or "unknown")
        for site_id, site_payload in sites.items()
    }
    metadata = {
        "generated_at": datetime.now(UTC).isoformat(),
        "source_kind": runtime_source.source_kind,
        "source_run_id": runtime_source.run_id,
        "identity_run_id": runtime_source.identity_run_id,
        "browser_engine": runtime_source.browser_engine,
        "selected_proxy_mask": _display_proxy(runtime_source.selected_proxy),
        "selected_proxy_index": runtime_source.selected_proxy_index,
        "proxy_inventory_masked": _masked_proxy_inventory(runtime_source.proxy_list),
        "proxy_profile": runtime_source.proxy_profile,
        "runtime_snapshot": runtime.snapshot(),
        "site_statuses": site_statuses,
        "degraded": any(status != "ok" for status in site_statuses.values()),
    }
    report = {
        "metadata": metadata,
        "connection_source": {
            "source_kind": runtime_source.source_kind,
            "run_id": runtime_source.run_id,
            "selected_proxy_mask": _display_proxy(runtime_source.selected_proxy),
            "proxy_inventory_masked": _masked_proxy_inventory(runtime_source.proxy_list),
            "proxy_profile": runtime_source.proxy_profile,
        },
        "baseline": baseline,
        "sites": sites,
    }
    report["findings"] = build_findings(report)
    (report_dir / "report.json").write_text(_json_dump(report), encoding="utf-8")
    (report_dir / "report.md").write_text(_render_markdown(report), encoding="utf-8")
    return report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", type=int, default=None)
    parser.add_argument("--proxy", action="append", default=[])
    parser.add_argument("--proxy-profile-json", default=None)
    parser.add_argument(
        "--browser-engine",
        choices=("chromium", "real_chrome"),
        default="chromium",
    )
    parser.add_argument("--report-dir", default=None)
    return parser


async def async_main(args: argparse.Namespace) -> Path:
    runtime_source = await _resolve_runtime_source(args)
    bundle_dir = _report_root(args.report_dir) / _utc_stamp()
    await build_report(
        runtime_source=runtime_source,
        report_dir=bundle_dir,
    )
    return bundle_dir


async def _run(args: argparse.Namespace) -> int:
    bundle_dir: Path | None = None
    try:
        bundle_dir = await async_main(args)
    finally:
        await shutdown_browser_runtime()
    if bundle_dir is None:
        raise RuntimeError("Fingerprint report bundle was not created")
    print(_json_dump({"report_dir": str(bundle_dir)}))
    return 0


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
