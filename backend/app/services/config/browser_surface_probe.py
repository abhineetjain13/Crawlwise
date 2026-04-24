from __future__ import annotations

BROWSER_SURFACE_PROBE_TARGETS = (
    {
        "id": "sannysoft",
        "label": "Sannysoft",
        "url": "https://bot.sannysoft.com/",
    },
    {
        "id": "pixelscan",
        "label": "Pixelscan",
        "url": "https://pixelscan.net/fingerprint-check",
    },
    {
        "id": "creepjs",
        "label": "CreepJS",
        "url": "https://abrahamjuliot.github.io/creepjs/",
    },
)

BROWSER_SURFACE_PROBE_POST_NAVIGATION_WAIT_MS = 4000
BROWSER_SURFACE_PROBE_SITE_MAX_RETRIES = 1
BROWSER_SURFACE_PROBE_RETRY_BACKOFF_MS = 1000
BROWSER_SURFACE_PROBE_REQUEST_DELAY_MS = 500
BROWSER_SURFACE_PROBE_WEBRTC_GATHER_TIMEOUT_MS = 2500
BROWSER_SURFACE_PROBE_VISIBLE_TEXT_LIMIT = 800
BROWSER_SURFACE_PROBE_TABLE_ROW_LIMIT = 400
BROWSER_SURFACE_PROBE_NEIGHBOR_LINE_WINDOW = 2
BROWSER_SURFACE_PROBE_TARGET_HTTP_TIMEOUT_SECONDS = 30
BROWSER_SURFACE_PROBE_TARGET_NAVIGATION_TIMEOUT_MS = 30000
BROWSER_SURFACE_PROBE_TARGET_VISIBLE_TEXT_SNIPPET_LIMIT = 240
BROWSER_SURFACE_PROBE_TARGET_COOKIE_NAME_LIMIT = 20
BROWSER_SURFACE_PROBE_TARGET_BODY_ARTIFACT_LIMIT = 200000
BROWSER_SURFACE_PROBE_TARGET_GEO_ENDPOINTS = (
    {
        "id": "ipinfo",
        "label": "IPInfo",
        "url": "https://ipinfo.io/json",
    },
    {
        "id": "ipapi",
        "label": "IPAPI",
        "url": "https://ipapi.co/json/",
    },
    {
        "id": "ipwhois",
        "label": "IPWhois",
        "url": "https://ipwho.is/",
    },
)
BROWSER_SURFACE_PROBE_TARGET_CHALLENGE_COOKIE_TOKENS = (
    "_abck",
    "ak_bmsc",
    "bm_sz",
    "datadome",
    "dd_session",
    "px",
    "_px",
)
BROWSER_SURFACE_PROBE_TARGET_RESPONSE_HEADER_ALLOWLIST = (
    "akamai-grn",
    "cf-mitigated",
    "content-type",
    "location",
    "retry-after",
    "server",
    "set-cookie",
    "x-akamai-transformed",
    "x-datadome",
    "x-datadome-cid",
    "x-kpsdk-ct",
    "x-kpsdk-r",
    "x-px-block",
)
BROWSER_SURFACE_PROBE_HIGH_ENTROPY_HINTS = (
    "architecture",
    "bitness",
    "fullVersionList",
    "model",
    "platform",
    "platformVersion",
    "uaFullVersion",
    "wow64",
)

BROWSER_SURFACE_PROBE_TIMEZONE_ALIASES = {
    "Asia/Calcutta": "Asia/Kolkata",
}

BROWSER_SURFACE_PROBE_SANNYSOFT_LABELS = {
    "webdriver": ("webdriver",),
    "user_agent": ("user agent",),
    "plugins": ("plugins",),
    "languages": ("language", "languages"),
    "webgl": ("webgl",),
    "screen": ("screen", "viewport", "window"),
    "permissions": ("permissions",),
}

BROWSER_SURFACE_PROBE_PIXELSCAN_LABELS = {
    "browser": ("browser", "browser version"),
    "os": ("os", "platform"),
    "ip": ("ip", "public ip"),
    "city": ("city",),
    "country": ("country",),
    "proxy_verdict": ("proxy", "proxy status", "vpn", "vpn or proxy"),
    "js_timezone": ("js timezone", "timezone"),
    "js_time": ("js time", "local time"),
    "ip_time": ("ip time",),
    "language_headers": ("language headers", "accept-language", "language"),
    "screen_size": ("screen", "resolution"),
    "webgl": ("webgl",),
    "canvas_hash": ("canvas",),
    "audio_hash": ("audio",),
}

BROWSER_SURFACE_PROBE_CREEPJS_LABELS = {
    "fp_id": ("fp id", "fingerprint id"),
    "fuzzy_fp_id": ("fuzzy fp id", "fuzzy id"),
    "webrtc": ("webrtc",),
    "timezone": ("timezone", "device of timezone", "intl"),
    "headless": ("headless",),
    "stealth": ("stealth",),
    "user_agent": ("user agent", "useragent"),
    "user_agent_data": ("useragentdata", "user agent data"),
    "screen": ("screen",),
    "navigator": ("navigator",),
}

BROWSER_SURFACE_PROBE_KEYWORD_GROUPS = {
    "webdriver": ("webdriver", "automation"),
    "headless": ("headless", "stealth"),
    "webrtc": ("webrtc", "rtc", "ice", "leak"),
    "timezone": ("timezone", "intl", "local time", "ip time"),
    "language": ("language", "locale", "accept-language"),
    "screen": ("screen", "viewport", "resolution", "window"),
    "webgl": ("webgl", "gpu", "renderer", "canvas", "audio"),
    "proxy": ("proxy", "vpn", "datacenter", "residential"),
}

BROWSER_SURFACE_PROBE_RISK_TOKENS = (
    "detected",
    "failed",
    "fail",
    "leak",
    "mismatch",
    "present",
    "risk",
    "suspicious",
    "true",
    "warning",
)

BROWSER_SURFACE_PROBE_SAFE_TOKENS = (
    "clean",
    "false",
    "no leak",
    "not detected",
    "pass",
    "passed",
    "safe",
    "success",
    "undetected",
    "0%",
    "0.0%",
)
