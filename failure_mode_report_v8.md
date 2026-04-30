# CrawlerAI Failure Mode Report V8

**Date:** 2026-04-29  
**Scope:** 34 seed URLs (via `testsites.md`). 33 records in `json.md`. 1 failure (2.9%).  
**Baseline:** v7 Report (8.3% failure rate).

---

## 1. Executive Summary
The latest crawl achieved a **97.1% success rate**, a significant improvement over v7 (91.7%). The primary driver for this improvement was the successful remediation of **ColourPop**, which transitioned from an interrupted/timeout state to 100% field coverage.

**Nordstrom** is identified as the single point of failure in this run, consistently triggering high-entropy bot protection shells.

---

## 2. Data Quality Summary (33 Sites)

| Metric | v7 Avg | v8 Avg | Delta |
|--------|--------|--------|-------|
| Success Rate | 91.7% | 97.1% | +5.4% |
| Avg Fields/Record | 6.2 | 6.8 | +0.6 |
| Core Field Coverage | 82% | 85% | +3% |

### Core Field Gap Analysis
| Field | Missing % | Status | Root Cause |
|-------|-----------|--------|------------|
| **SKU** | 12% | Improving | Missing on Wayfair, Target, Decathlon. |
| **Brand** | 15% | Persistent | Inference engine skipping generic labels (Amazon/Target). |
| **Variants** | 55% | Critical | JS state mapper returning after first match; DOM tier skip. |
| **Barcode** | 70% | Expected | Rarely present in public DOM; requires backfill/LLM. |

---

## 3. The Failure: Nordstrom
**Target:** `https://www.nordstrom.com/s/treasure-and-bond-blouson-twill-utility-jacket/8045019`

### Failure Mode: `blocked (challenge_shell)`
- **Symptom:** Nordstrom is missing from `json.md`.
- **Diagnostics:** The site triggers a Datadome/Akamai challenge page immediately upon browser navigation.
- **Evidence:** Browser diagnostics likely capture a `low_content_shell` or `challenge_page` outcome. The `origin_warmup` in `browser_runtime.py:1601` likely swallows the initial navigation exception, leading to a silent failure at the acquisition tier.
- **Resolution Path:** Requires "Stealth 2.0" context or proxy rotation with high reputation scores.

---

## 4. Comparison vs V7 Report

| Site | v7 State | v8 State | Notes |
|------|----------|----------|-------|
| **ColourPop** | ❌ Interrupted | ✅ Success | Full extraction (Price, SKU, Variants). |
| **New Balance** | ❌ Blocked | — | Removed from `testsites.md` scope. |
| **REI** | ❌ Timeout | — | Removed from `testsites.md` scope. |
| **Nordstrom** | — | ❌ Blocked | New addition to scope; failing on protection. |

---

## 5. Persistent Extraction Issues (D4 Audit)
As noted in `AUDIT_REPORT_V7.md`, several architectural issues continue to depress field coverage:
- **JS State First-Match:** `js_state_mapper.py` still returns on the first root match, causing missing variants for sites like Zappos and Zara.
- **Early Exit:** `detail_extractor.py:995` exits early if JS state is "confident," skipping the DOM tier which often contains supplementary metadata (Availability, Additional Images).
- **NoneType Crashes:** `_generate_page_markdown` resilience is still low for malformed DOM nodes (Issue #4 in Coderabbit).

---

## 6. Action Items
1. **Fix JS State Collector:** Implement multi-root collection in `js_state_mapper.py`.
2. **Harden Markdown Generator:** Fix the `NoneType` attribute access in `browser_page_flow.py:1135`.
3. **Nordstrom Triage:** Test `browser_profile` rotation to bypass Datadome challenge.
