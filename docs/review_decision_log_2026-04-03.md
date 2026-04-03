# Review Decision Log — 2026-04-03

## Scope

- Reviewed current uncommitted implementation for crawl pipeline, records/export APIs, review payload generation, and run-detail frontend.
- Focused on failures reported in run detail: blank JSON/CSV views, incomplete detail capture, and degraded site behavior after adapter installation.

## Selected Options

- None yet.

## Deferred Items

- None yet.

## Unresolved Decisions

- Architecture Issue 1: Records API/frontend contract mismatch for run detail data loading.
- Architecture Issue 2: JSON-first extraction discards source payloads and cannot satisfy full-link capture.
- Architecture Issue 3: Detail success verdict is too weak and promotes partial extraction to completed.
