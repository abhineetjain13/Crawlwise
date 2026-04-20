---
date: 2026-04-21
topic: extraction-enhancements
---

# Extraction Enhancements

## What We're Building
Three extraction improvements in the existing owners: broader browser network payload capture for React Server Components and TRPC-style payloads, a visual listing fallback for flattened browser-rendered grids, and declarative JMESPath-backed JS state mappings for ecommerce detail extraction.

## Why This Approach
The repo already has clear seams for these concerns. Acquisition owns browser payload capture and browser-only artifacts. Extraction owns listing clustering and JS-state normalization. Platform config already owns declarative extraction metadata. Reusing those seams keeps the change grep-friendly and avoids a second registry or plugin-style layer.

## Key Decisions
- `acquisition/browser_capture.py`: broaden payload eligibility with explicit RSC/TRPC hints and URL heuristics.
- `acquisition/browser_page_flow.py`: capture lightweight listing geometry as an internal artifact only for listing surfaces.
- `listing_extractor.py`: use visual artifacts only as a fallback after structured and DOM listing extraction fail.
- `platforms.json` + `js_state_mapper.py`: add optional JMESPath field mappings per JS-state extractor and merge them with existing normalization.

## Open Questions
- None for this slice. Geometry fallback is intentionally bounded and internal-only.

## Next Steps
→ Implement the extraction slice with focused backend tests.
