# Gemini Prompt: Backend Triage And Upload Plan

Use this prompt first when a service area has too many files and you need Gemini to tell you where to zoom in next.

The output should not be a shallow “these files are large” summary.
It should produce a ranked investigation plan and tell us which follow-up upload bundles will generate the most useful codemaps.

## Best upload pattern

Upload one broad but coherent backend area:
- `backend/app/services/acquisition/*`
- or `backend/app/services/extract/*`
- or `backend/app/services/pipeline/*`
- or `backend/app/services/normalizers/*`
- or `backend/app/services/config/*`

Also include:
- the 3-6 most relevant tests for that area
- optionally the tracker doc

## Paste this into Gemini AI Studio

```text
I uploaded a large but bounded backend area. Triage it and tell me where deeper investigation should focus.

I do not want implementation and I do not want generic code review comments.
I want an investigation plan that another coding agent can use to drive simplification work.

Your job:
- identify the files that are creating the most confusion and complexity
- classify the kind of problem each hotspot has
- tell me which small follow-up upload bundles would give the best next codemap

Context:
- the backend is being simplified toward clear stage boundaries: acquire -> discover -> extract -> normalize -> publish
- the goal is not just file splitting; the goal is lower complexity, clearer ownership, less duplicated policy, and fewer stale seams

Rules:
- Use only the uploaded files.
- Cite exact files and functions when possible.
- Do not give generic advice.
- Do not recommend a repo-wide rewrite.
- Do not tell me to inspect everything manually.
- If evidence is insufficient, say exactly: INSUFFICIENT EVIDENCE.

Return exactly this shape:

# Triage Map
## 1. Area Summary
- What area was uploaded:
- Main architectural concern:
- Main simplification concern:

## 2. Ranked Hotspots
List up to 12 hotspots.
For each hotspot:
- Rank:
- File:
- Severity: critical / high / medium / low
- Main issue type: ownership drift / mixed concern / duplicated policy / stale seam / branch explosion / config-as-behavior / test risk / helper indirection
- Why this file is a real hotspot:
- Evidence from uploaded files:
- What type of follow-up investigation it needs: codemap / boundary review / duplication map / stale-test map

## 3. Follow-Up Upload Bundles
For the top 5 hotspots, define the best next upload bundle.
For each bundle:
- Target hotspot:
- Files to upload next:
- Tests to upload next:
- Why this bundle is enough:
- What question that next prompt should answer:

## 4. Low-Priority Areas
- File or area:
- Why it should not be investigated yet:

## 5. Best Next Investigation Order
- 1:
- 2:
- 3:
- 4:
- 5:

If the uploaded files are insufficient, say exactly:
INSUFFICIENT EVIDENCE
and then list what is missing.
```
