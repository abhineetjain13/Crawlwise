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
from typing import Any, Sequence
from urllib.parse import urlparse

import pytz  # type: ignore[import-untyped]

from app.core.database import SessionLocal
from app.services.acquisition.runtime import (
    classify_block_from_headers,
    classify_blocked_page,
    copy_headers,
    curl_fetch,
    http_fetch,
)
from app.services.acquisition.browser_runtime import (
    SharedBrowserRuntime,
    _display_proxy,
    get_browser_runtime,
    shutdown_browser_runtime,
)
from app.services.config.browser_surface_probe import (
    BROWSER_SURFACE_PROBE_CREEPJS_LABELS,
    BROWSER_SURFACE_PROBE_FONT_TEST_STRINGS,
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
    BROWSER_SURFACE_PROBE_TARGET_BODY_ARTIFACT_LIMIT,
    BROWSER_SURFACE_PROBE_TARGET_CHALLENGE_COOKIE_TOKENS,
    BROWSER_SURFACE_PROBE_TARGET_COOKIE_NAME_LIMIT,
    BROWSER_SURFACE_PROBE_TARGET_GEO_ENDPOINTS,
    BROWSER_SURFACE_PROBE_TARGET_HTTP_TIMEOUT_SECONDS,
    BROWSER_SURFACE_PROBE_TARGET_NAVIGATION_TIMEOUT_MS,
    BROWSER_SURFACE_PROBE_TARGET_RESPONSE_HEADER_ALLOWLIST,
    BROWSER_SURFACE_PROBE_TARGET_VISIBLE_TEXT_SNIPPET_LIMIT,
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
    locality_profile: dict[str, object]
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


def _object_dict(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def _object_list(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


def _string_list(value: object) -> list[str]:
    return [str(item) for item in _object_list(value)]


def _int_list(value: object) -> list[int]:
    return [item for item in _object_list(value) if isinstance(item, int)]


def _dict_rows(value: object) -> list[dict[str, object]]:
    return [_object_dict(item) for item in _object_list(value) if isinstance(item, dict)]


def _coerce_locality_profile(
    *,
    geo_country: object = None,
    language_hint: object = None,
    currency_hint: object = None,
) -> dict[str, object]:
    normalized_geo = _normalize_space(geo_country).upper() or "auto"
    if len(normalized_geo) != 2 or not normalized_geo.isalpha():
        normalized_geo = "auto"
    normalized_language = _normalize_space(language_hint) or None
    normalized_currency = _normalize_space(currency_hint) or None
    return {
        "geo_country": normalized_geo,
        "language_hint": normalized_language,
        "currency_hint": normalized_currency,
    }


async def _load_run_runtime_source(run_id: int, *, browser_engine: str) -> RuntimeSource:
    async with SessionLocal() as session:
        run = await get_run(session, run_id)
    if run is None:
        raise ValueError(f"Run {run_id} not found")
    settings_view = run.settings_view
    proxy_list = settings_view.proxy_list()
    proxy_profile = settings_view.proxy_profile()
    locality_profile = settings_view.locality_profile()
    enabled = bool(proxy_profile.get("enabled"))
    selected_proxy = proxy_list[0] if enabled and proxy_list else None
    selected_proxy_index = 0 if selected_proxy is not None else None
    return RuntimeSource(
        source_kind="run",
        run_id=run.id,
        identity_run_id=run.id,
        proxy_list=proxy_list,
        proxy_profile=proxy_profile,
        locality_profile=locality_profile,
        selected_proxy=selected_proxy,
        selected_proxy_index=selected_proxy_index,
        browser_engine=browser_engine,
    )


def _load_explicit_runtime_source(
    *,
    proxies: list[str],
    proxy_profile_path: str | None,
    locality_profile: dict[str, object],
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
        locality_profile=locality_profile,
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
        locality_profile=_coerce_locality_profile(
            geo_country=args.geo_country,
            language_hint=args.language_hint,
            currency_hint=args.currency_hint,
        ),
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


def _looks_like_networkish_ipv4(value: str) -> bool:
    octets = str(value or "").split(".")
    if len(octets) != 4:
        return False
    try:
        numbers = [int(item) for item in octets]
    except ValueError:
        return False
    if any(number < 0 or number > 255 for number in numbers):
        return True
    if numbers[1:] in ([0, 0, 0], [255, 255, 255]):
        return True
    if numbers[2:] in ([0, 0], [255, 255]):
        return True
    if numbers[3] in {0, 255}:
        return True
    return False


def _clean_ip_values(values: list[str], *, known_versions: list[int] | None = None) -> list[str]:
    version_set = {int(value) for value in list(known_versions or [])}
    cleaned: list[str] = []
    for value in values:
        if _looks_like_networkish_ipv4(value):
            continue
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


def _percent_value(value: object) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)%", str(value or ""))
    if match is None:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


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


def _normalize_snapshot_row(row: object) -> dict[str, object] | None:
    if not isinstance(row, dict):
        return None
    raw_cells = row.get("cells")
    cells = (
        [_normalize_space(value) for value in list(raw_cells) if _normalize_space(value)]
        if isinstance(raw_cells, list)
        else []
    )
    label = _normalize_space(row.get("label")) or (cells[0] if cells else "")
    value = _normalize_space(row.get("value")) or " | ".join(cells[1:])
    if not (label or value or cells):
        return None
    return {
        "cells": cells,
        "label": label,
        "value": value,
    }


def _dedupe_snapshot_rows(rows: list[object]) -> tuple[list[dict[str, object]], int]:
    normalized_rows = [
        normalized
        for row in rows
        if (normalized := _normalize_snapshot_row(row)) is not None
    ]
    seen: set[tuple[tuple[str, ...], str, str]] = set()
    deduped: list[dict[str, object]] = []
    for row in normalized_rows:
        marker = (
            tuple(str(value).casefold() for value in _object_list(row.get("cells"))),
            _normalize_space(row.get("label")).casefold(),
            _normalize_space(row.get("value")).casefold(),
        )
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(row)
    return deduped, len(normalized_rows)


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
    raw_snapshot = await page.evaluate(
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
    snapshot_payload = dict(raw_snapshot) if isinstance(raw_snapshot, dict) else {}
    raw_lines = [
        _normalize_space(value)
        for value in list(snapshot_payload.get("lines") or [])
        if _normalize_space(value)
    ]
    deduped_lines = _dedupe(raw_lines)
    deduped_rows, raw_row_count = _dedupe_snapshot_rows(
        list(snapshot_payload.get("rows") or [])
    )
    return {
        "body_text": _normalize_space(snapshot_payload.get("body_text")),
        "lines": deduped_lines,
        "line_count": len(deduped_lines),
        "line_count_raw": len(raw_lines),
        "rows": deduped_rows,
        "row_count": len(deduped_rows),
        "row_count_raw": raw_row_count,
        "has_creep_object": bool(snapshot_payload.get("has_creep_object")),
        "has_fingerprint_object": bool(snapshot_payload.get("has_fingerprint_object")),
    }


async def _collect_behavioral_smoke(page) -> dict[str, object]:
    try:
        setup = await page.evaluate(
            """() => {
                const body = document.body;
                if (!body) {
                    return { ready: false, mouse_isTrusted: null, click_isTrusted: null };
                }
                const state = globalThis.__crawlerProbeBehavioralSmoke = {
                    mouse_isTrusted: null,
                    click_isTrusted: null,
                };
                let target = document.getElementById('__crawler_probe_mouse_target__');
                if (!target) {
                    target = document.createElement('div');
                    target.id = '__crawler_probe_mouse_target__';
                    target.setAttribute('aria-hidden', 'true');
                    target.style.cssText = [
                        'position:fixed',
                        'left:8px',
                        'top:8px',
                        'width:32px',
                        'height:32px',
                        'opacity:0.001',
                        'background:#000',
                        'pointer-events:auto',
                        'z-index:2147483647',
                    ].join(';');
                    body.appendChild(target);
                }
                target.addEventListener('mousemove', (event) => {
                    state.mouse_isTrusted = event.isTrusted;
                }, { once: true });
                target.addEventListener('click', (event) => {
                    state.click_isTrusted = event.isTrusted;
                }, { once: true });
                return { ready: true, x: 24, y: 24 };
            }"""
        )
    except Exception:
        return {"mouse_isTrusted": None, "click_isTrusted": None}
    if not _object_dict(setup).get("ready"):
        return {
            "mouse_isTrusted": _object_dict(setup).get("mouse_isTrusted"),
            "click_isTrusted": _object_dict(setup).get("click_isTrusted"),
        }
    try:
        await page.mouse.move(24, 24, steps=6)
        await page.wait_for_timeout(50)
        await page.mouse.click(24, 24, delay=50)
        await page.wait_for_timeout(50)
    except Exception:
        pass
    try:
        return _object_dict(
            await page.evaluate(
                """() => {
                    const state = globalThis.__crawlerProbeBehavioralSmoke || {};
                    const target = document.getElementById('__crawler_probe_mouse_target__');
                    if (target && target.parentNode) {
                        target.parentNode.removeChild(target);
                    }
                    try {
                        delete globalThis.__crawlerProbeBehavioralSmoke;
                    } catch (_error) {}
                    return {
                        mouse_isTrusted: state.mouse_isTrusted ?? null,
                        click_isTrusted: state.click_isTrusted ?? null,
                    };
                }"""
            )
        )
    except Exception:
        return {"mouse_isTrusted": None, "click_isTrusted": None}


async def _collect_baseline(
    page,
    *,
    behavioral_smoke: dict[str, object] | None = None,
) -> dict[str, object]:
    return await page.evaluate(
        """async (input) => {
            const normalize = (value) => (value == null ? '' : String(value)).replace(/\\s+/g, ' ').trim();
            const hashBytes = (bytes) => {
                if (!bytes || typeof bytes.length !== 'number') {
                    return null;
                }
                let hash = 2166136261;
                for (let index = 0; index < bytes.length; index += 1) {
                    hash ^= Number(bytes[index]) & 255;
                    hash = Math.imul(hash, 16777619);
                }
                return `fnv1a:${(hash >>> 0).toString(16).padStart(8, '0')}`;
            };
            const collectWebGL = () => {
                try {
                    const canvas = document.createElement('canvas');
                    const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
                    if (!gl) {
                        return { vendor: null, renderer: null, version: null, shading_language_version: null, supported_extensions: [], read_pixels_hash: null };
                    }
                    const extension = gl.getExtension('WEBGL_debug_renderer_info');
                    const pixels = new Uint8Array(16);
                    try {
                        gl.clearColor(0.25, 0.5, 0.75, 1);
                        gl.clear(gl.COLOR_BUFFER_BIT);
                        gl.readPixels(0, 0, 2, 2, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
                    } catch (_pixelError) {}
                    return {
                        vendor: extension ? gl.getParameter(extension.UNMASKED_VENDOR_WEBGL) : gl.getParameter(gl.VENDOR),
                        renderer: extension ? gl.getParameter(extension.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER),
                        version: gl.getParameter(gl.VERSION),
                        shading_language_version: gl.getParameter(gl.SHADING_LANGUAGE_VERSION),
                        supported_extensions: gl.getSupportedExtensions() || [],
                        read_pixels_hash: hashBytes(pixels),
                    };
                } catch (_error) {
                    return { vendor: null, renderer: null, version: null, shading_language_version: null, supported_extensions: [], read_pixels_hash: null };
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
            const collectCanvas = () => {
                try {
                    const canvas = document.createElement('canvas');
                    canvas.width = 200;
                    canvas.height = 50;
                    const ctx = canvas.getContext('2d');
                    if (!ctx) return { fingerprint: null, text_measure: null };
                    ctx.textBaseline = 'top';
                    ctx.font = '14px Arial';
                    ctx.fillStyle = '#f60';
                    ctx.fillRect(0, 0, 200, 50);
                    ctx.fillStyle = '#069';
                    ctx.fillText('Browser fingerprint probe', 2, 15);
                    ctx.fillStyle = 'rgba(102, 204, 0, 0.7)';
                    ctx.fillText('Browser fingerprint probe', 4, 17);
                    const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
                    const dataUrl = canvas.toDataURL();
                    const textMeasure = ctx.measureText('Browser fingerprint probe').width;
                    return {
                        fingerprint: dataUrl.slice(0, 200),
                        image_data_hash: hashBytes(imageData && imageData.data),
                        data_url_prefix: dataUrl.slice(0, 64),
                        text_measure: textMeasure,
                    };
                } catch (_e) {
                    return { fingerprint: null, image_data_hash: null, data_url_prefix: null, text_measure: null, error: _e.message };
                }
            };
            const collectAudio = () => {
                try {
                    const ctx = new (window.AudioContext || window.webkitAudioContext)();
                    const osc = ctx.createOscillator();
                    const analyser = ctx.createAnalyser();
                    const gain = ctx.createGain();
                    gain.gain.value = 0;
                    osc.connect(analyser);
                    analyser.connect(gain);
                    gain.connect(ctx.destination);
                    osc.start(0);
                    const buffer = new Float32Array(analyser.frequencyBinCount);
                    analyser.getFloatFrequencyData(buffer);
                    osc.stop(0);
                    const sum = buffer.reduce((a, b) => a + b, 0);
                    return { fingerprint: sum.toFixed(2), sample_rate: ctx.sampleRate, channel_count: ctx.destination.channelCount };
                } catch (_e) {
                    return { fingerprint: null, sample_rate: null, channel_count: null, error: _e.message };
                }
            };
            const collectFonts = () => {
                const testStrings = input.fontTestStrings || [];
                const baseFonts = ['monospace', 'sans-serif', 'serif'];
                const detected = [];
                const canvas = document.createElement('canvas');
                const ctx = canvas.getContext('2d');
                if (!ctx) return [];
                const getWidth = (font) => {
                    ctx.font = `72px ${font}, monospace`;
                    return ctx.measureText('mmmmmmmmmmlli').width;
                };
                for (const testFont of testStrings) {
                    const baseWidths = baseFonts.map(getWidth);
                    const testWidth = getWidth(testFont);
                    if (!baseWidths.includes(testWidth)) {
                        detected.push(testFont);
                    }
                }
                return detected.slice(0, 50);
            };
            const collectConnection = () => {
                const conn = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
                if (!conn) return null;
                return {
                    effective_type: conn.effectiveType || null,
                    downlink: conn.downlink || null,
                    rtt: conn.rtt || null,
                    save_data: conn.saveData || false,
                };
            };
            const collectScreenOrientation = () => {
                const orient = window.screen.orientation;
                if (!orient) return null;
                return {
                    angle: orient.angle,
                    type: orient.type,
                };
            };
            const collectAutomationGlobals = () => {
                const markers = [];
                if (typeof window.playwright !== 'undefined') markers.push('window.playwright');
                if (typeof window.__pw_scripts !== 'undefined') markers.push('window.__pw_scripts');
                if (typeof window.__pw_init !== 'undefined') markers.push('window.__pw_init');
                if (typeof window.cdc_adoQpoasnfa76pfcZLmcfl_Array !== 'undefined') markers.push('cdc_array');
                if (typeof window.cdc_adoQpoasnfa76pfcZLmcfl_Promise !== 'undefined') markers.push('cdc_promise');
                if (document.documentElement && document.documentElement.getAttribute('__playwright_testid_attribute__')) markers.push('__playwright_testid_attribute__');
                const chromeRoot = typeof window.chrome !== 'undefined' ? window.chrome : undefined;
                const chromeRuntime = chromeRoot ? chromeRoot.runtime : undefined;
                if (typeof chromeRuntime !== 'object') {
                    markers.push(`chrome.runtime.typeof=${typeof chromeRuntime}`);
                }
                return markers;
            };
            const collectTimingJitter = () => {
                const deltas = [];
                let last = performance.now();
                for (let i = 0; i < 10; i++) {
                    const now = performance.now();
                    deltas.push(parseFloat((now - last).toFixed(4)));
                    last = now;
                }
                return deltas;
            };
            const collectIframeLeak = () => {
                try {
                    const iframe = document.createElement('iframe');
                    document.body.appendChild(iframe);
                    const cw = iframe.contentWindow;
                    const leak = cw[0] === null && cw.length === 0;
                    document.body.removeChild(iframe);
                    return { content_window_array_leak: leak };
                } catch (_e) {
                    return { content_window_array_leak: null, error: _e.message };
                }
            };
            const collectPermissions = async () => {
                const results = {};
                if (!navigator.permissions || !navigator.permissions.query) return results;
                const names = ['notifications', 'camera', 'microphone', 'geolocation'];
                for (const name of names) {
                    try {
                        const status = await navigator.permissions.query({ name });
                        results[name] = status.state;
                    } catch (_e) {
                        results[name] = `error:${_e.name}`;
                    }
                }
                return results;
            };
            const uaData = navigator.userAgentData
                ? await navigator.userAgentData
                    .getHighEntropyValues(input.highEntropyHints)
                    .catch(() => null)
                : null;
            const webgl = collectWebGL();
            const canvas = collectCanvas();
            const audio = collectAudio();
            const fonts = collectFonts();
            const connection = collectConnection();
            const screen_orientation = collectScreenOrientation();
            const automation_globals = collectAutomationGlobals();
            const timing_jitter = collectTimingJitter();
            const iframe_leak = collectIframeLeak();
            const permissions = await collectPermissions();
            const behavioral = input.behavioralSmoke && typeof input.behavioralSmoke === 'object'
                ? input.behavioralSmoke
                : null;
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
                canvas,
                audio,
                fonts,
                connection,
                screen_orientation,
                max_touch_points: navigator.maxTouchPoints ?? null,
                pdf_viewer_enabled: navigator.pdfViewerEnabled ?? null,
                cookie_enabled: navigator.cookieEnabled ?? null,
                do_not_track: navigator.doNotTrack ?? null,
                automation_globals,
                timing_jitter,
                iframe_leak,
                permissions,
                behavioral_smoke: behavioral,
                webrtc_ips: await collectWebRTCIps(),
                timestamp: new Date().toISOString(),
            };
        }""",
        {
            "behavioralSmoke": dict(behavioral_smoke or {}),
            "highEntropyHints": list(BROWSER_SURFACE_PROBE_HIGH_ENTROPY_HINTS),
            "webrtcTimeoutMs": int(BROWSER_SURFACE_PROBE_WEBRTC_GATHER_TIMEOUT_MS),
            "fontTestStrings": list(BROWSER_SURFACE_PROBE_FONT_TEST_STRINGS),
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
    lines = [str(value) for value in _object_list(snapshot.get("lines"))]
    payload = _generic_line_signals(lines=lines, label_map=BROWSER_SURFACE_PROBE_PIXELSCAN_LABELS)
    labeled_values = _object_dict(payload.get("labeled_values"))
    payload["country_values"] = _flatten_signal_values(labeled_values.get("country"))
    payload["ip_values"] = _clean_ip_values(
        _extract_ip_values(_flatten_signal_values(labeled_values.get("ip"))),
        known_versions=_int_list(payload.get("signal_versions")),
    )
    payload["timezone_values"] = _flatten_signal_values(
        {
            "js_timezone": labeled_values.get("js_timezone"),
            "ip_time": labeled_values.get("ip_time"),
        }
    )
    payload["proxy_values"] = _flatten_signal_values(labeled_values.get("proxy_verdict"))
    payload["language_values"] = _flatten_signal_values(labeled_values.get("language_headers"))
    payload["screen_values"] = _flatten_signal_values(labeled_values.get("screen_size"))
    payload["webgl_values"] = _flatten_signal_values(labeled_values.get("webgl"))
    return payload


def _extract_creepjs(snapshot: dict[str, object]) -> dict[str, object]:
    lines = [str(value) for value in _object_list(snapshot.get("lines"))]
    payload = _generic_line_signals(lines=lines, label_map=BROWSER_SURFACE_PROBE_CREEPJS_LABELS)
    labeled_values = _object_dict(payload.get("labeled_values"))
    payload["fp_id_values"] = _flatten_signal_values(labeled_values.get("fp_id"))
    payload["fuzzy_fp_id_values"] = _flatten_signal_values(
        labeled_values.get("fuzzy_fp_id")
    )
    keyword_hits = _object_dict(payload.get("keyword_hits"))
    payload["headless_hits"] = _object_list(keyword_hits.get("headless"))
    payload["webrtc_hits"] = _object_list(keyword_hits.get("webrtc"))
    payload["timezone_hits"] = _object_list(keyword_hits.get("timezone"))
    payload["screen_hits"] = _object_list(keyword_hits.get("screen"))
    payload["ip_values"] = _clean_ip_values(
        _extract_ip_values(_string_list(payload.get("webrtc_hits"))),
        known_versions=_int_list(payload.get("signal_versions")),
    )
    return payload


def _extract_generic_site(snapshot: dict[str, object]) -> dict[str, object]:
    lines = [str(value) for value in _object_list(snapshot.get("lines"))]
    payload = _generic_line_signals(lines=lines, label_map={})
    payload["ip_values"] = _clean_ip_values(
        _extract_ip_values(lines),
        known_versions=_int_list(payload.get("signal_versions")),
    )
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


def _coalesce(values: Sequence[object]) -> object | None:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def _consensus_baseline(per_site: dict[str, dict[str, object]]) -> dict[str, object]:
    if not per_site:
        return {"consensus": {}, "drift": {}}
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
        "canvas",
        "audio",
        "fonts",
        "connection",
        "screen_orientation",
        "max_touch_points",
        "pdf_viewer_enabled",
        "cookie_enabled",
        "do_not_track",
        "automation_globals",
        "timing_jitter",
        "iframe_leak",
        "permissions",
        "behavioral_smoke",
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
        "drift": drift,
    }


def _target_identity_mismatch(
    *,
    locale: str,
    timezone_name: str,
    geo_country_code: str | None,
) -> dict[str, object]:
    locale_region = _locale_region(locale)
    timezone_match = _timezone_matches_country(timezone_name, geo_country_code)
    return {
        "geo_country_code": geo_country_code,
        "locale_region": locale_region,
        "locale_country_match": (
            locale_region == geo_country_code
            if locale_region and geo_country_code
            else None
        ),
        "timezone_country_match": timezone_match,
    }


def _target_root_cause(
    *,
    consensus: dict[str, object],
    diagnostic: dict[str, object],
) -> dict[str, object]:
    geo = _object_dict(_object_dict(diagnostic.get("geo")).get("consensus"))
    geo_country = _country_code_from_value(str(geo.get("country") or ""))
    mismatch = _target_identity_mismatch(
        locale=str(consensus.get("locale") or ""),
        timezone_name=str(consensus.get("timezone") or ""),
        geo_country_code=geo_country,
    )
    transport_payloads = [
        _object_dict(diagnostic.get("httpx")),
        _object_dict(diagnostic.get("curl_cffi")),
    ]
    browser = _object_dict(diagnostic.get("browser"))
    transport_blocked = [
        payload
        for payload in transport_payloads
        if payload.get("status") == "ok" and bool(payload.get("blocked"))
    ]
    transport_ok = [
        payload
        for payload in transport_payloads
        if payload.get("status") == "ok" and not bool(payload.get("blocked"))
    ]
    browser_blocked = browser.get("status") == "ok" and bool(browser.get("blocked"))
    browser_ok = browser.get("status") == "ok" and not bool(browser.get("blocked"))
    browser_classification = _object_dict(browser.get("classification"))
    vendor = (
        browser_classification.get("header_vendor")
        or _coalesce(
            [
                _object_dict(payload.get("classification")).get("header_vendor")
                for payload in transport_payloads
            ]
        )
        or _coalesce(
            [
                _coalesce(
                    _object_list(_object_dict(payload.get("classification")).get("provider_hits"))
                )
                for payload in [browser, *transport_payloads]
            ]
        )
    )
    if transport_blocked and browser_blocked:
        return {
            "category": "target_precontent_block",
            "confidence": "high",
            "message": "HTTP and browser paths both blocked before usable content.",
            "evidence": {
                "vendor": vendor,
                "geo_identity": mismatch,
                "httpx": {
                    "status_code": transport_payloads[0].get("status_code"),
                    "outcome": _object_dict(transport_payloads[0].get("classification")).get("outcome"),
                },
                "curl_cffi": {
                    "status_code": transport_payloads[1].get("status_code"),
                    "outcome": _object_dict(transport_payloads[1].get("classification")).get("outcome"),
                },
                "browser": {
                    "status_code": browser.get("status_code"),
                    "outcome": browser_classification.get("outcome"),
                    "challenge_cookie_names": browser.get("challenge_cookie_names"),
                },
            },
        }
    if browser_blocked and transport_ok:
        if mismatch.get("timezone_country_match") is False or mismatch.get("locale_country_match") is False:
            return {
                "category": "browser_geo_identity_mismatch",
                "confidence": "high",
                "message": "Browser path blocked while transport passes and browser geo identity drifts from observed egress country.",
                "evidence": {
                    "geo_identity": mismatch,
                    "browser": {
                        "status_code": browser.get("status_code"),
                        "outcome": browser_classification.get("outcome"),
                    },
                },
            }
        return {
            "category": "browser_session_or_fingerprint_block",
            "confidence": "high",
            "message": "Browser path blocked while transport passes; failure is browser session or browser-only fingerprint flow.",
            "evidence": {
                "vendor": vendor,
                "browser": {
                    "status_code": browser.get("status_code"),
                    "outcome": browser_classification.get("outcome"),
                    "challenge_cookie_names": browser.get("challenge_cookie_names"),
                },
            },
        }
    if browser_ok and transport_blocked:
        return {
            "category": "transport_only_block",
            "confidence": "high",
            "message": "Transport paths blocked while browser path stays usable.",
            "evidence": {
                "vendor": vendor,
                "httpx_status_code": transport_payloads[0].get("status_code"),
                "curl_status_code": transport_payloads[1].get("status_code"),
            },
        }
    if browser_ok or transport_ok:
        return {
            "category": "no_target_block_detected",
            "confidence": "high",
            "message": "At least one acquisition path reached usable content.",
            "evidence": {
                "geo_identity": mismatch,
            },
        }
    return {
        "category": "target_diagnostic_inconclusive",
        "confidence": "low",
        "message": "Target diagnostics did not produce enough successful paths to classify the failure mechanically.",
        "evidence": {
            "geo_identity": mismatch,
            "browser_status": browser.get("status"),
            "httpx_status": transport_payloads[0].get("status"),
            "curl_status": transport_payloads[1].get("status"),
        },
    }


def build_findings(report: dict[str, object]) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    metadata = _object_dict(report.get("metadata"))
    baseline = _object_dict(report.get("baseline"))
    consensus = _object_dict(baseline.get("consensus"))
    drift = _object_dict(baseline.get("drift"))
    sites = _object_dict(report.get("sites"))
    target_diagnostics = _object_list(report.get("target_diagnostics"))
    failed_probe_sites = [
        site_id
        for site_id, site_payload in sites.items()
        if _object_dict(site_payload).get("site_status") == "failed"
    ]
    degraded_probe_sites = [
        site_id
        for site_id, site_payload in sites.items()
        if _object_dict(site_payload).get("site_status") == "degraded"
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
    pixelscan = _object_dict(sites.get("pixelscan"))
    sannysoft = _object_dict(sites.get("sannysoft"))
    creepjs = _object_dict(sites.get("creepjs"))

    pixelscan_country = _coalesce(
        _string_list(_object_dict(pixelscan.get("extracted")).get("country_values"))
    )
    pixelscan_country_code = _country_code_from_value(str(pixelscan_country or ""))
    observed_geo_country = None
    for diagnostic in target_diagnostics:
        diagnostic_geo = _object_dict(_object_dict(_object_dict(diagnostic).get("geo")).get("consensus"))
        observed_geo_country = _country_code_from_value(str(diagnostic_geo.get("country") or ""))
        if observed_geo_country:
            break
    geo_provider_drift = bool(
        pixelscan_country_code
        and observed_geo_country
        and pixelscan_country_code != observed_geo_country
    )
    if geo_provider_drift:
        findings.append(
            {
                "severity": "warn",
                "category": "proxy_geo_provider_drift",
                "message": (
                    f"Pixelscan geolocates the same exit IP as {pixelscan_country_code} "
                    f"while direct geo endpoints report {observed_geo_country}."
                ),
                "evidence": {
                    "pixelscan_country": pixelscan_country,
                    "observed_geo_country": observed_geo_country,
                },
            }
        )
    timezone_value = str(consensus.get("timezone") or "")
    timezone_country_match = _timezone_matches_country(timezone_value, pixelscan_country_code)
    if timezone_country_match is False and not geo_provider_drift:
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
    if (
        locale_region
        and pixelscan_country_code
        and locale_region != pixelscan_country_code
        and not geo_provider_drift
    ):
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
    extracted_versions: list[int] = []
    for site in sites.values():
        extracted_versions.extend(
            _int_list(_object_dict(_object_dict(site).get("extracted")).get("signal_versions"))
        )
    extracted_versions = sorted(set(extracted_versions))
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
    webdriver_evidence.extend(
        _string_list(_object_dict(sannysoft.get("extracted")).get("webdriver_hits"))
    )
    creepjs_keyword_hits = _object_dict(
        _object_dict(creepjs.get("extracted")).get("keyword_hits")
    )
    webdriver_evidence.extend(_string_list(creepjs_keyword_hits.get("webdriver")))
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
    creepjs_extracted = _object_dict(creepjs.get("extracted"))
    headless_evidence.extend(_string_list(creepjs_extracted.get("headless_hits")))
    headless_evidence.extend(
        _string_list(_object_dict(creepjs_extracted.get("keyword_hits")).get("headless"))
    )
    filtered_headless_evidence: list[str] = []
    for value in headless_evidence:
        normalized = _normalize_space(value).lower()
        if " like headless" in normalized:
            percent = _percent_value(value)
            if percent is None or percent < 10:
                continue
        if _looks_like_truthy_risk(value):
            filtered_headless_evidence.append(value)
    headless_evidence = filtered_headless_evidence
    if headless_evidence:
        findings.append(
            {
                "severity": "fail",
                "category": "headless_leakage",
                "message": "Headless or stealth leakage is visible in public checks.",
                "evidence": headless_evidence[:10],
            }
        )

    webrtc_ips = [
        str(value)
        for value in _object_list(consensus.get("webrtc_ips"))
        if _normalize_space(value)
    ]
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

    automation_globals = [
        value
        for value in _string_list(consensus.get("automation_globals"))
        if value != "chrome.runtime.typeof=object"
    ]
    if automation_globals:
        findings.append(
            {
                "severity": "fail",
                "category": "automation_globals_exposure",
                "message": "Automation framework globals are visible in the page context.",
                "evidence": automation_globals[:10],
            }
        )

    iframe_leak = _object_dict(consensus.get("iframe_leak"))
    if iframe_leak and iframe_leak.get("content_window_array_leak") is True:
        findings.append(
            {
                "severity": "fail",
                "category": "iframe_content_window_leak",
                "message": "Iframe contentWindow array leak detected (automation marker).",
                "evidence": iframe_leak,
            }
        )

    if "canvas" in drift:
        findings.append(
            {
                "severity": "warn",
                "category": "canvas_fingerprint_drift",
                "message": "Canvas fingerprint values differ across probe sites.",
                "evidence": drift.get("canvas"),
            }
        )

    if "audio" in drift:
        findings.append(
            {
                "severity": "warn",
                "category": "audio_fingerprint_drift",
                "message": "AudioContext fingerprint values differ across probe sites.",
                "evidence": drift.get("audio"),
            }
        )

    behavioral = _object_dict(consensus.get("behavioral_smoke"))
    if (
        behavioral
        and (
            behavioral.get("mouse_isTrusted") is False
            or behavioral.get("click_isTrusted") is False
        )
    ):
        findings.append(
            {
                "severity": "warn",
                "category": "synthetic_event_detection",
                "message": "Playwright input did not produce trusted DOM events.",
                "evidence": behavioral,
            }
        )

    if str(metadata.get("browser_engine") or "").strip().lower() == "chromium":
        findings.append(
            {
                "severity": "info",
                "category": "chromium_ja3_limitation",
                "message": "Chromium engine still uses a Playwright Chromium TLS fingerprint; use real_chrome for native Chrome JA3 parity.",
                "evidence": {
                    "browser_engine": metadata.get("browser_engine"),
                },
            }
        )

    site_ips: list[str] = []
    site_countries: list[str] = []
    for site_payload in sites.values():
        extracted = _object_dict(_object_dict(site_payload).get("extracted"))
        site_ips.extend(_string_list(extracted.get("ip_values")))
        site_countries.extend(_string_list(extracted.get("country_values")))
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

    for diagnostic in target_diagnostics:
        target_payload = _object_dict(diagnostic)
        target_url = str(target_payload.get("url") or "target")
        root_cause = _target_root_cause(
            consensus=consensus,
            diagnostic=target_payload,
        )
        category = str(root_cause.get("category") or "")
        severity = "info"
        if category in {
            "target_precontent_block",
            "browser_geo_identity_mismatch",
            "browser_session_or_fingerprint_block",
        }:
            severity = "fail"
        elif category in {"transport_only_block", "target_diagnostic_inconclusive"}:
            severity = "warn"
        findings.append(
            {
                "severity": severity,
                "category": category,
                "message": f"{target_url}: {root_cause.get('message')}",
                "evidence": root_cause.get("evidence"),
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
        return _sannysoft_signal_rows(_dict_rows(snapshot.get("rows")))
    if site_id == "pixelscan":
        return _extract_pixelscan(snapshot)
    if site_id == "creepjs":
        return _extract_creepjs(snapshot)
    return _extract_generic_site(snapshot)


def _slugify(value: object) -> str:
    normalized = _NON_ALNUM_RE.sub("-", _normalize_space(value).lower()).strip("-")
    return normalized or "target"


def _validated_target_url(value: object) -> str:
    url = _normalize_space(value)
    parsed = urlparse(url)
    scheme = str(parsed.scheme or "").strip().lower()
    if scheme not in {"http", "https"}:
        raise ValueError("target URL must use http or https")
    if not parsed.hostname:
        raise ValueError("target URL must include a hostname")
    host = str(parsed.hostname).strip().lower().rstrip(".")
    if host == "localhost" or host.endswith(".localhost"):
        raise ValueError("target URL host must not be local")
    try:
        address = ip_address(host)
    except ValueError:
        return url
    if (
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
    ):
        raise ValueError("target URL host must not be local or private")
    return url


def _truncate_text(value: object, *, limit: int) -> str:
    normalized = _normalize_space(value)
    return normalized[:limit] if limit > 0 else normalized


def _failed_target_diagnostic(*, url: str, error: str) -> dict[str, object]:
    parsed = urlparse(url)
    host = _normalize_space(parsed.netloc or parsed.path)
    return {
        "target_id": _slugify(host or url),
        "url": url,
        "host": host,
        "geo": {},
        "httpx": {"status": "failed", "error": error},
        "curl_cffi": {"status": "failed", "error": error},
        "browser": {"status": "failed", "error": error},
    }


def _text_snippet_from_html(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", str(html or ""))
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return _truncate_text(text, limit=int(BROWSER_SURFACE_PROBE_TARGET_VISIBLE_TEXT_SNIPPET_LIMIT))


def _target_artifacts(base_dir: Path, target_id: str, variant: str) -> dict[str, Path]:
    return {
        "body": base_dir / f"{target_id}_{variant}.txt",
        "html": base_dir / f"{target_id}_{variant}.html",
        "screenshot": base_dir / f"{target_id}_{variant}.png",
    }


def _write_target_body_artifact(path: Path, body: str) -> None:
    path.write_text(
        str(body or "")[: int(BROWSER_SURFACE_PROBE_TARGET_BODY_ARTIFACT_LIMIT)],
        encoding="utf-8",
    )


def _selected_headers(headers: Any) -> dict[str, str]:
    normalized = copy_headers(headers)
    allowlist = {str(value).strip().lower() for value in BROWSER_SURFACE_PROBE_TARGET_RESPONSE_HEADER_ALLOWLIST}
    selected: dict[str, str] = {}
    for key, value in normalized.multi_items():
        lowered = str(key or "").strip().lower()
        if lowered not in allowlist:
            continue
        if lowered == "set-cookie":
            selected.setdefault(lowered, value)
            continue
        selected[lowered] = value
    return selected


def _classification_payload(*, html: str, status_code: int, headers: Any) -> dict[str, object]:
    classification = classify_blocked_page(html, status_code)
    return {
        "blocked": bool(classification.blocked),
        "outcome": classification.outcome,
        "evidence": list(classification.evidence),
        "provider_hits": list(classification.provider_hits),
        "active_provider_hits": list(classification.active_provider_hits),
        "strong_hits": list(classification.strong_hits),
        "weak_hits": list(classification.weak_hits),
        "title_matches": list(classification.title_matches),
        "challenge_element_hits": list(classification.challenge_element_hits),
        "header_vendor": classify_block_from_headers(headers),
    }


def _geo_payload_from_text(text: str) -> dict[str, object]:
    try:
        payload = json.loads(text)
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    timezone = payload.get("timezone")
    if isinstance(timezone, dict):
        timezone = timezone.get("id") or timezone.get("name")
    connection = payload.get("connection")
    connection = dict(connection) if isinstance(connection, dict) else {}
    return {
        "ip": _normalize_space(payload.get("ip")),
        "city": _normalize_space(payload.get("city")),
        "region": _normalize_space(payload.get("region") or payload.get("regionName")),
        "country": _normalize_space(
            payload.get("country")
            or payload.get("country_code")
            or payload.get("country_name")
        ),
        "timezone": _normalize_space(timezone),
        "org": _normalize_space(
            payload.get("org")
            or payload.get("isp")
            or connection.get("org")
        ),
        "raw": payload,
    }


def _geo_consensus(results: list[dict[str, object]]) -> dict[str, object]:
    keys = ("ip", "city", "region", "country", "timezone", "org")
    consensus: dict[str, object] = {}
    for key in keys:
        consensus[key] = _coalesce([result.get(key) for result in results])
    return consensus


async def _run_geo_endpoint_checks(proxy: str | None) -> dict[str, object]:
    checks: list[dict[str, object]] = []
    for endpoint in BROWSER_SURFACE_PROBE_TARGET_GEO_ENDPOINTS:
        url = str(endpoint.get("url") or "").strip()
        label = str(endpoint.get("label") or endpoint.get("id") or url).strip()
        if not url:
            continue
        for method_name, fetcher in (("httpx", http_fetch), ("curl_cffi", curl_fetch)):
            try:
                result = await fetcher(
                    url,
                    float(BROWSER_SURFACE_PROBE_TARGET_HTTP_TIMEOUT_SECONDS),
                    proxy=proxy,
                )
                payload = _geo_payload_from_text(result.html)
                checks.append(
                    {
                        "label": label,
                        "method": method_name,
                        "url": url,
                        "status_code": result.status_code,
                        "final_url": result.final_url,
                        "geo": payload,
                    }
                )
            except Exception as exc:
                checks.append(
                    {
                        "label": label,
                        "method": method_name,
                        "url": url,
                        "error": f"{type(exc).__name__}: {exc}",
                        "geo": {},
                    }
                )
    return {
        "checks": checks,
        "consensus": _geo_consensus(
            [
                geo_payload
                for check in checks
                if (geo_payload := _object_dict(check.get("geo")))
            ]
        ),
    }


async def _target_transport_payload(
    *,
    method_label: str,
    fetcher,
    url: str,
    proxy: str | None,
    artifacts_dir: Path,
    target_id: str,
) -> dict[str, object]:
    artifacts = _target_artifacts(artifacts_dir, target_id, method_label)
    try:
        result = await fetcher(
            url,
            float(BROWSER_SURFACE_PROBE_TARGET_HTTP_TIMEOUT_SECONDS),
            proxy=proxy,
        )
    except Exception as exc:
        return {
            "method": method_label,
            "url": url,
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
            "artifacts": {"body": None, "html": None, "screenshot": None},
        }
    _write_target_body_artifact(artifacts["body"], result.html)
    if "html" in str(result.content_type or "").lower():
        artifacts["html"].write_text(result.html, encoding="utf-8")
        html_name = artifacts["html"].name
    else:
        html_name = None
    return {
        "method": method_label,
        "url": url,
        "status": "ok",
        "status_code": result.status_code,
        "final_url": result.final_url,
        "content_type": result.content_type,
        "blocked": bool(result.blocked),
        "classification": _classification_payload(
            html=result.html,
            status_code=result.status_code,
            headers=result.headers,
        ),
        "response_headers": _selected_headers(result.headers),
        "visible_text_snippet": _text_snippet_from_html(result.html),
        "artifacts": {
            "body": artifacts["body"].name,
            "html": html_name,
            "screenshot": None,
        },
    }


async def _response_headers_dict(response: object | None) -> dict[str, str]:
    if response is None:
        return {}
    for attr in ("all_headers", "headers"):
        candidate = getattr(response, attr, None)
        if candidate is None:
            continue
        try:
            resolved = await candidate() if callable(candidate) else candidate
        except TypeError:
            try:
                resolved = candidate()
            except Exception:
                continue
        except Exception:
            continue
        if isinstance(resolved, dict):
            return {str(key): str(value) for key, value in resolved.items()}
    return {}


async def _browser_cookie_names(page: Any, final_url: str) -> list[str]:
    context = getattr(page, "context", None)
    if context is None:
        return []
    cookies_method = getattr(context, "cookies", None)
    if cookies_method is None:
        return []
    try:
        cookies = await cookies_method([final_url]) if callable(cookies_method) else []
    except Exception:
        return []
    names = [
        _normalize_space(cookie.get("name"))
        for cookie in cookies
        if isinstance(cookie, dict) and _normalize_space(cookie.get("name"))
    ]
    return _dedupe(names)[: int(BROWSER_SURFACE_PROBE_TARGET_COOKIE_NAME_LIMIT)]


def _challenge_cookie_names(cookie_names: list[str]) -> list[str]:
    tokens = tuple(str(token).strip().lower() for token in BROWSER_SURFACE_PROBE_TARGET_CHALLENGE_COOKIE_TOKENS)
    return [
        name
        for name in cookie_names
        if any(token and token in name.lower() for token in tokens)
    ]


async def _target_browser_payload(
    runtime: SharedBrowserRuntime,
    *,
    url: str,
    run_id: int,
    locality_profile: dict[str, object],
    artifacts_dir: Path,
    target_id: str,
) -> dict[str, object]:
    artifacts = _target_artifacts(artifacts_dir, target_id, "browser")
    async with runtime.page(
        run_id=run_id,
        locality_profile=locality_profile,
        allow_storage_state=False,
        inject_init_script=True,
    ) as page:
        response = await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=int(BROWSER_SURFACE_PROBE_TARGET_NAVIGATION_TIMEOUT_MS),
        )
        for state, timeout_ms in (("load", 10000), ("networkidle", 8000)):
            try:
                await page.wait_for_load_state(state, timeout=timeout_ms)
            except Exception:
                continue
        await page.wait_for_timeout(int(BROWSER_SURFACE_PROBE_POST_NAVIGATION_WAIT_MS))
        html = await page.content()
        snapshot = await _collect_page_snapshot(page)
        behavioral_smoke = await _collect_behavioral_smoke(page)
        baseline = await _collect_baseline(page, behavioral_smoke=behavioral_smoke)
        await page.screenshot(path=str(artifacts["screenshot"]), full_page=True)
        artifacts["html"].write_text(html, encoding="utf-8")
        _write_target_body_artifact(artifacts["body"], html)
        final_url = _normalize_space(page.url)
        response_headers = await _response_headers_dict(response)
        status_code = 0
        if response is not None:
            status_attr = getattr(response, "status", None)
            try:
                status_code = int(status_attr() if callable(status_attr) else status_attr or 0)
            except Exception:
                status_code = 0
        cookie_names = await _browser_cookie_names(page, final_url or url)
        return {
            "method": "browser",
            "url": url,
            "status": "ok",
            "status_code": status_code,
            "final_url": final_url,
            "title": _normalize_space(await page.title()),
            "blocked": bool(classify_blocked_page(html, status_code).blocked),
            "classification": _classification_payload(
                html=html,
                status_code=status_code,
                headers=response_headers,
            ),
            "response_headers": _selected_headers(response_headers),
            "baseline": baseline,
            "snapshot_summary": {
                "line_count": snapshot.get("line_count", 0),
                "line_count_raw": snapshot.get("line_count_raw", snapshot.get("line_count", 0)),
                "lines": _object_list(snapshot.get("lines")),
            },
            "visible_text_snippet": _truncate_text(
                " ".join(str(line) for line in _object_list(snapshot.get("lines"))[:12]),
                limit=int(BROWSER_SURFACE_PROBE_TARGET_VISIBLE_TEXT_SNIPPET_LIMIT),
            ),
            "cookie_names": cookie_names,
            "challenge_cookie_names": _challenge_cookie_names(cookie_names),
            "artifacts": {
                "body": artifacts["body"].name,
                "html": artifacts["html"].name,
                "screenshot": artifacts["screenshot"].name,
            },
        }


async def _run_target_diagnostic(
    runtime: SharedBrowserRuntime,
    *,
    url: str,
    runtime_source: RuntimeSource,
    artifacts_dir: Path,
) -> dict[str, object]:
    url = _validated_target_url(url)
    parsed = urlparse(url)
    host = _normalize_space(parsed.netloc or parsed.path)
    target_id = _slugify(host)
    geo = await _run_geo_endpoint_checks(runtime_source.selected_proxy)
    transport_http = await _target_transport_payload(
        method_label="httpx",
        fetcher=http_fetch,
        url=url,
        proxy=runtime_source.selected_proxy,
        artifacts_dir=artifacts_dir,
        target_id=target_id,
    )
    transport_curl = await _target_transport_payload(
        method_label="curl_cffi",
        fetcher=curl_fetch,
        url=url,
        proxy=runtime_source.selected_proxy,
        artifacts_dir=artifacts_dir,
        target_id=target_id,
    )
    try:
        browser_payload = await _target_browser_payload(
            runtime,
            url=url,
            run_id=runtime_source.identity_run_id,
            locality_profile=runtime_source.locality_profile,
            artifacts_dir=artifacts_dir,
            target_id=target_id,
        )
    except Exception as exc:
        browser_payload = {
            "method": "browser",
            "url": url,
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
            "artifacts": {"body": None, "html": None, "screenshot": None},
        }
    return {
        "target_id": target_id,
        "url": url,
        "host": host,
        "geo": geo,
        "httpx": transport_http,
        "curl_cffi": transport_curl,
        "browser": browser_payload,
    }


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
    lines = _object_list(snapshot.get("lines"))
    rows = _object_list(snapshot.get("rows"))
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
    locality_profile: dict[str, object],
    artifacts_dir: Path,
) -> dict[str, object]:
    artifacts = _site_artifacts(artifacts_dir, site_id)
    max_attempts = max(1, int(BROWSER_SURFACE_PROBE_SITE_MAX_RETRIES) + 1)
    last_error = ""
    for attempt in range(1, max_attempts + 1):
        try:
            async with runtime.page(
                run_id=run_id,
                locality_profile=locality_profile,
                allow_storage_state=False,
                inject_init_script=True,
            ) as page:
                try:
                    await _navigate_probe_target(page, url)
                    behavioral_smoke = await _collect_behavioral_smoke(page)
                    baseline = await _collect_baseline(page, behavioral_smoke=behavioral_smoke)
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
                            "line_count_raw": snapshot.get("line_count_raw", snapshot.get("line_count", 0)),
                            "lines": _object_list(snapshot.get("lines")),
                            "row_count": snapshot.get("row_count", 0),
                            "row_count_raw": snapshot.get("row_count_raw", snapshot.get("row_count", 0)),
                            "rows": _object_list(snapshot.get("rows")),
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


def _ua_major(user_agent: object) -> int | None:
    match = _BROWSER_VERSION_RE.search(str(user_agent or ""))
    if match is None:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _build_agent_summary(report: dict[str, object]) -> dict[str, object]:
    metadata = _object_dict(report.get("metadata"))
    baseline = _object_dict(report.get("baseline"))
    consensus = _object_dict(baseline.get("consensus"))
    findings = _object_list(report.get("findings"))
    sites = _object_dict(report.get("sites"))
    target_diagnostics = _object_list(report.get("target_diagnostics"))
    severity_counts: dict[str, int] = {"fail": 0, "warn": 0, "info": 0}
    normalized_findings = [_object_dict(finding) for finding in findings if isinstance(finding, dict)]
    for finding in normalized_findings:
        severity = str(finding.get("severity") or "").strip().lower()
        if severity not in severity_counts:
            continue
        severity_counts[severity] += 1
    site_rows: list[dict[str, object]] = []
    for site_id, raw_site_payload in sorted(sites.items()):
        site_payload = _object_dict(raw_site_payload)
        snapshot_summary = _object_dict(site_payload.get("snapshot_summary"))
        site_rows.append(
            {
                "site_id": site_id,
                "label": site_payload.get("label"),
                "status": site_payload.get("site_status"),
                "attempts": site_payload.get("attempts"),
                "line_count": snapshot_summary.get("line_count"),
                "line_count_raw": snapshot_summary.get("line_count_raw"),
                "row_count": snapshot_summary.get("row_count"),
                "row_count_raw": snapshot_summary.get("row_count_raw"),
                "validation_warnings": _object_list(site_payload.get("validation_warnings")),
                "final_url": site_payload.get("final_url") or site_payload.get("url"),
                "error": site_payload.get("error"),
            }
        )
    target_rows: list[dict[str, object]] = []
    for raw_payload in target_diagnostics:
        if not isinstance(raw_payload, dict):
            continue
        payload = _object_dict(raw_payload)
        root_cause = _object_dict(payload.get("root_cause"))
        browser = _object_dict(payload.get("browser"))
        httpx_payload = _object_dict(payload.get("httpx"))
        curl_payload = _object_dict(payload.get("curl_cffi"))
        target_rows.append(
            {
                "url": payload.get("url"),
                "host": payload.get("host"),
                "root_cause_category": root_cause.get("category"),
                "root_cause_confidence": root_cause.get("confidence"),
                "browser_status": browser.get("status"),
                "browser_blocked": browser.get("blocked"),
                "httpx_status": httpx_payload.get("status"),
                "httpx_blocked": httpx_payload.get("blocked"),
                "curl_status": curl_payload.get("status"),
                "curl_blocked": curl_payload.get("blocked"),
            }
        )
    return {
        "generated_at": metadata.get("generated_at"),
        "engine": metadata.get("browser_engine"),
        "source_kind": metadata.get("source_kind"),
        "degraded": bool(metadata.get("degraded")),
        "selected_proxy_mask": metadata.get("selected_proxy_mask"),
        "severity_counts": severity_counts,
        "findings": [
            {
                "severity": str(finding.get("severity") or ""),
                "category": str(finding.get("category") or ""),
                "message": str(finding.get("message") or ""),
                "evidence": (
                    _object_list(finding.get("evidence"))[:5]
                    if isinstance(finding.get("evidence"), list)
                    else finding.get("evidence")
                ),
            }
            for finding in normalized_findings
        ],
        "baseline": {
            "user_agent_major": _ua_major(consensus.get("user_agent")),
            "locale": consensus.get("locale"),
            "timezone": consensus.get("timezone"),
            "webdriver": consensus.get("webdriver"),
            "webrtc_ip_count": len(_object_list(consensus.get("webrtc_ips"))),
            "automation_globals_count": len(_object_list(consensus.get("automation_globals"))),
            "iframe_leak": _object_dict(consensus.get("iframe_leak")).get("content_window_array_leak"),
            "canvas_text_measure": _object_dict(consensus.get("canvas")).get("text_measure"),
            "canvas_image_data_hash": _object_dict(consensus.get("canvas")).get("image_data_hash"),
            "canvas_data_url_prefix": _object_dict(consensus.get("canvas")).get("data_url_prefix"),
            "audio_fingerprint": _object_dict(consensus.get("audio")).get("fingerprint"),
            "webgl_vendor": _object_dict(consensus.get("webgl")).get("vendor"),
            "webgl_renderer": _object_dict(consensus.get("webgl")).get("renderer"),
            "fonts_count": len(_object_list(consensus.get("fonts"))),
            "max_touch_points": consensus.get("max_touch_points"),
            "pdf_viewer_enabled": consensus.get("pdf_viewer_enabled"),
            "cookie_enabled": consensus.get("cookie_enabled"),
            "drift_keys": sorted(list(_object_dict(baseline.get("drift")).keys())),
        },
        "sites": site_rows,
        "target_diagnostics": target_rows,
    }


def _render_markdown(report: dict[str, object]) -> str:
    summary = _build_agent_summary(report)
    findings = _object_list(summary.get("findings"))
    sites = _object_list(summary.get("sites"))
    target_diagnostics = _object_list(summary.get("target_diagnostics"))
    baseline = _object_dict(summary.get("baseline"))
    severity_counts = _object_dict(summary.get("severity_counts"))
    lines = [
        "# Browser Fingerprint Report",
        "",
        f"- Generated: {summary.get('generated_at')}",
        f"- Engine: {summary.get('engine')}",
        f"- Source: {summary.get('source_kind')}",
        f"- Degraded: {summary.get('degraded')}",
        f"- Proxy: {summary.get('selected_proxy_mask')}",
        f"- Findings: fail={severity_counts.get('fail', 0)}, warn={severity_counts.get('warn', 0)}, info={severity_counts.get('info', 0)}",
        "",
        "## Baseline",
        f"- UA major: {baseline.get('user_agent_major')}",
        f"- Locale: {baseline.get('locale')}",
        f"- Timezone: {baseline.get('timezone')}",
        f"- Webdriver: {baseline.get('webdriver')}",
        f"- WebRTC IP count: {baseline.get('webrtc_ip_count')}",
        f"- Automation globals count: {baseline.get('automation_globals_count')}",
        f"- Iframe leak: {baseline.get('iframe_leak')}",
        f"- Canvas text measure: {baseline.get('canvas_text_measure')}",
        f"- Canvas image-data hash: {baseline.get('canvas_image_data_hash')}",
        f"- Canvas data-url prefix: {baseline.get('canvas_data_url_prefix')}",
        f"- Audio fingerprint: {baseline.get('audio_fingerprint')}",
        f"- WebGL vendor: {baseline.get('webgl_vendor')}",
        f"- WebGL renderer: {baseline.get('webgl_renderer')}",
        f"- Fonts count: {baseline.get('fonts_count')}",
        f"- Max touch points: {baseline.get('max_touch_points')}",
        f"- PDF viewer enabled: {baseline.get('pdf_viewer_enabled')}",
        f"- Cookie enabled: {baseline.get('cookie_enabled')}",
        f"- Drift keys: {', '.join(_string_list(baseline.get('drift_keys'))) or 'none'}",
        "",
        "## Findings",
    ]
    if findings:
        for raw_finding in findings:
            finding = _object_dict(raw_finding)
            lines.append(
                f"- {str(finding.get('severity') or '').upper()} [{finding.get('category')}]: {finding.get('message')}"
            )
    else:
        lines.append("- INFO: no findings")
    lines.extend(["", "## Sites"])
    for raw_site in sites:
        site = _object_dict(raw_site)
        warnings = _string_list(site.get("validation_warnings"))
        warning_text = ",".join(warnings) if warnings else "none"
        lines.append(
            f"- {site.get('site_id')}: status={site.get('status')} attempts={site.get('attempts')} lines={site.get('line_count')}/{site.get('line_count_raw')} rows={site.get('row_count')}/{site.get('row_count_raw')} warnings={warning_text}"
        )
    if target_diagnostics:
        lines.extend(["", "## Target Diagnostics"])
        for raw_payload in target_diagnostics:
            payload = _object_dict(raw_payload)
            lines.append(
                f"- {payload.get('host') or payload.get('url')}: {payload.get('root_cause_category')} ({payload.get('root_cause_confidence')}) browser={payload.get('browser_status')}/{payload.get('browser_blocked')} httpx={payload.get('httpx_status')}/{payload.get('httpx_blocked')} curl={payload.get('curl_status')}/{payload.get('curl_blocked')}"
            )
    return "\n".join(lines).strip() + "\n"


async def build_report(
    *,
    runtime_source: RuntimeSource,
    report_dir: Path,
    target_urls: list[str] | None = None,
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
            locality_profile=runtime_source.locality_profile,
            artifacts_dir=report_dir,
        )
        sites[str(target["id"])] = site_payload
        delay_ms = max(0, int(BROWSER_SURFACE_PROBE_REQUEST_DELAY_MS))
        if delay_ms and index < len(BROWSER_SURFACE_PROBE_TARGETS) - 1:
            await asyncio.sleep(delay_ms / 1000)
    baseline = _consensus_baseline(
        {
            site_id: _object_dict(site_payload.get("baseline"))
            for site_id, site_payload in sites.items()
            if isinstance(site_payload, dict)
        }
    )
    consensus = _object_dict(baseline.get("consensus"))
    target_diagnostics: list[dict[str, object]] = []
    for raw_url in list(target_urls or []):
        raw = _normalize_space(raw_url)
        if not raw:
            continue
        try:
            url = _validated_target_url(raw)
        except ValueError as exc:
            target_diagnostics.append(
                _failed_target_diagnostic(url=raw, error=f"{type(exc).__name__}: {exc}")
            )
            continue
        try:
            diagnostic = await _run_target_diagnostic(
                runtime,
                url=url,
                runtime_source=runtime_source,
                artifacts_dir=report_dir,
            )
        except Exception as exc:
            diagnostic = _failed_target_diagnostic(
                url=url,
                error=f"{type(exc).__name__}: {exc}",
            )
        diagnostic["root_cause"] = _target_root_cause(
            consensus=consensus,
            diagnostic=diagnostic,
        )
        target_diagnostics.append(diagnostic)
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
        "locality_profile": runtime_source.locality_profile,
        "runtime_snapshot": runtime.snapshot(),
        "site_statuses": site_statuses,
        "degraded": any(status != "ok" for status in site_statuses.values()),
    }
    report: dict[str, object] = {
        "metadata": metadata,
        "connection_source": {
            "source_kind": runtime_source.source_kind,
            "run_id": runtime_source.run_id,
            "selected_proxy_mask": _display_proxy(runtime_source.selected_proxy),
            "proxy_inventory_masked": _masked_proxy_inventory(runtime_source.proxy_list),
            "proxy_profile": runtime_source.proxy_profile,
            "locality_profile": runtime_source.locality_profile,
        },
        "baseline": baseline,
        "sites": sites,
        "target_diagnostics": target_diagnostics,
    }
    report["findings"] = build_findings(report)
    report["agent_summary"] = _build_agent_summary(report)
    (report_dir / "report.json").write_text(_json_dump(report), encoding="utf-8")
    (report_dir / "report.md").write_text(_render_markdown(report), encoding="utf-8")
    return report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", type=int, default=None)
    parser.add_argument("--proxy", action="append", default=[])
    parser.add_argument("--proxy-profile-json", default=None)
    parser.add_argument("--target-url", action="append", default=[])
    parser.add_argument("--geo-country", default=None)
    parser.add_argument("--language-hint", default=None)
    parser.add_argument("--currency-hint", default=None)
    parser.add_argument(
        "--browser-engine",
        choices=("chromium", "real_chrome", "patchright"),
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
        target_urls=list(args.target_url or []),
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
