# Listing Pipeline Refactor Plan

## Goal
Reduce complexity in the listing pipeline and move effort back into acquisition robustness and extraction yield.

## What Was Wrong
- The previous refactor added a large diagnostic branch around `surface_validation` and `surface_mismatch`.
- That branch increased code size and run-state complexity but did not create any new data path.
- The main runtime issue on complex listings was still in browser acquisition:
  - duplicate listing readiness waits
  - weak browser-profile fallback
  - no early exit for tiny unavailable shells

## Current Findings
- `https://www.musiciansfriend.com/snare-drum-heads`
  - current repo now returns listing data quickly over HTTP
  - no browser needed in the tested path
- `https://www.backmarket.com/en-us/l/apple-macbook/a059fa0c-b88d-4095-b6a2-dcbeb9dd5b33`
  - current failure is acquisition-level
  - browser lands on a tiny unavailable shell instead of listing content
  - duplicate readiness waits were wasting time and have been reduced
- `https://reverb.com/marketplace?product_type=electric-guitars`
  - curl returns a generic marketplace shell with no extractable listings
  - browser still hits a challenge page
  - remaining problem is anti-bot/access, not extraction semantics

## Refactor Principles
- Keep discovery focused on source discovery only.
- Keep crawl verdicts focused on user-facing outcomes, not internal labels.
- Put complexity into browser acquisition only when it increases the chance of real data.
- Prefer smaller acquisition heuristics over new run-state categories.

## Implemented Slice
- Removed the `surface_validation` / `surface_mismatch` branch from the hot path.
- Restored smoke and crawl semantics to data-first outcomes.
- Changed browser launch order to prefer system Chrome before bundled Chromium.
- Added retry to the next browser launch profile when the first result is blocked or a low-value shell.
- Removed the duplicate listing readiness wait.
- Added early exit for tiny unavailable shells.

## Next Slice
1. Introduce a small `BrowserProvider` boundary in the current repo, modeled on the older repo, so browser launch policy and session reuse stop leaking through acquisition flow.
2. Add host-scoped browser memory only for concrete acquisition facts:
   - repeated browser challenge
   - repeated tiny unavailable shell
   - repeated successful browser recovery
3. Compare cookie persistence and browser context settings between this repo and `C:\Users\abhij\Downloads\pre_poc_ai_crawler` and port only the settings that improve Reverb and Back Market.
4. Add targeted live canaries for:
   - Musicians Friend listing record count and latency
   - Back Market acquisition shell type and time-to-fail
   - Reverb browser challenge rate and time-to-fail
5. Only after acquisition is stable, revisit extractor gaps if a site returns real listing HTML or network payloads but still yields poor records.

## Success Criteria
- No new run verdicts unless they change recovery behavior.
- Listing browser waits are single-pass, not stacked.
- Complex listing failures fail faster and more concretely.
- Any new code must improve either:
  - data yield
  - time to data
  - time to fail
