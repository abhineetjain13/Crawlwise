# Product Features

This document summarizes advanced technologies used in CrawlerAI for acquisition, fingerprinting, and extraction.

## 1. Acquisition Stack

### 1.1 Hybrid fetch orchestration
- HTTP-first fetch path with browser escalation when blocked or low-content.
- Shared async HTTP runtime with retry logic and IPv4 fallback.
- Timeout and concurrency controls through runtime config.

### 1.2 Browser runtime hardening
- Playwright runtime pool with context lifecycle limits and recycle policy.
- Real Chrome support path (headful/native context controls).
- Browser challenge recovery loop for anti-bot interstitials.
- Human-like interaction emission (mouse jitter, scroll physics, typing delays).

### 1.3 Proxy and pacing controls
- Proxy profile normalization and rotation behavior.
- Sticky/rotating proxy token handling and session rewrite switches.
- Host pacing memory with per-host interval controls.
- Browser proxy bridge timeout controls for authenticated upstream proxies.

### 1.4 Network intelligence capture
- Response listener workers for network payload harvesting.
- Endpoint classification (`graphql`, `product_api`, `job_api`, `generic_json`).
- Byte-budget controls per payload and total capture envelope.
- Noise suppression for telemetry/analytics/challenge routes.
- RSC/streaming payload decode support (`text/x-component` parsing).

### 1.5 Block and challenge detection
- Signature-based detection for Cloudflare, DataDome, PerimeterX, Kasada, Akamai patterns.
- Phrase/title/provider marker fusion for blocked-page classification.
- Challenge-cookie and storage marker awareness.

## 2. Fingerprinting Stack

### 2.1 Browser identity generation
- BrowserForge fingerprint generation with host-OS-locked profile.
- UA/platform/client-hint coherence correction.
- Run-scoped identity cache with TTL for deterministic behavior per run.

### 2.2 Surface coherence patching (init scripts)
- Navigator coherence: language/platform/touch/network info alignment.
- Intl/timezone coherence and locale-aware patching.
- Permissions/media devices coherence patching.
- Chrome runtime object shims (`window.chrome.runtime` behaviors).
- Performance timing normalization for realistic monotonic navigation entries.

### 2.3 Anti-fingerprint signal shaping
- Canvas read/write perturbation script.
- WebGL vendor/renderer/capability profile alignment by platform.
- Audio fingerprint perturbation at analyser/buffer level.
- Font surface allowlist and style rewriting by platform family.
- WebRTC local IP masking path with safe `RTCPeerConnection` replacement.
- Playwright global masking and optional worker disabling.

### 2.4 Fingerprint research probes
- Built-in browser surface probe targets:
  - Sannysoft, Pixelscan, CreepJS, BrowserLeaks, EFF Cover Your Tracks, Incolumitas, FingerprintJS demo.
- Probe scoring signals for webdriver/headless/webrtc/timezone/language/proxy risk.

## 3. Extraction Stack

### 3.1 Deterministic extraction order
- Primary order: adapter -> structured source -> DOM.
- LLM is fallback only (explicitly gated by run config and active LLM config).

### 3.2 Adapter layer
- Domain/platform adapters for major ecommerce and job systems.
- Adapter result scoring and selection in pipeline orchestration.
- Adapter recovery hooks for blocked/detail scenarios.

### 3.3 Structured + network extraction
- JSON-LD, microdata, embedded JSON, JS state harvest.
- Network payload mapping via declarative specs (`network_payload_specs.py`).
- Endpoint-family-aware field mapping for commerce/job detail payloads.
- Listing backfill from captured network payloads (price/currency/brand/id/title joins).

### 3.4 Detail extraction tiers
- Tiered detail resolver:
  - Authoritative tier (adapter/network)
  - Structured-data tier
  - JS-state tier
  - DOM tier
- Confidence scoring + early exit rules.
- Variant-aware extraction and variant axis normalization.
- Price/currency/original-price backfill from DOM + schema.

### 3.5 Listing extraction and quality controls
- Listing candidate ranking and dedupe.
- Structural/noise filtering on URLs and titles.
- Selector-rule fallbacks and domain selector memory integration.
- Raw JSON and XML sitemap record ingestion for listing surfaces.

### 3.6 Self-heal and LLM fallback controls
- Selector self-heal gating (threshold + runtime switch).
- Missing-field LLM fallback with confidence threshold checks.
- Direct-record LLM extraction mode with minimum quality gates.
- Field-type validation on LLM output before merge.

## 4. Runtime and Observability

- Config-driven runtime via `backend/app/services/config/*`.
- Metrics for browser pool, LLM outcomes, and crawl health.
- Artifact capture support (HTML/screenshots/network payload bundles).
- Run-level quality summary accumulation across processed URLs.
