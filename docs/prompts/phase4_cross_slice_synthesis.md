# Gemini Prompt: Cross-Slice Synthesis

Use this after you already have 2 or more Gemini outputs from earlier slice investigations.

Upload:
- the Gemini outputs themselves as text files or pasted text
- optionally the tracker doc
- optionally a small set of anchor files if Gemini needs exact names resolved

This prompt makes Gemini turn separate slice investigations into one cross-slice codemap and simplification program.

## Paste this into Gemini AI Studio

```text
I uploaded prior investigation outputs from multiple backend slices.

Synthesize them into one coherent cross-slice codemap and simplification program.

I do not want implementation.
I want a planning artifact another coding agent can use to decide where to simplify code next.

Context:
- the backend is being simplified toward stage boundaries: acquire -> discover -> extract -> normalize -> publish
- we want fewer mixed-responsibility modules, less duplicated policy, fewer stale seams, and less test coupling to internals
- architecture improvements only matter if they produce simpler code

Rules:
- Use only the uploaded investigation outputs and any uploaded anchor files.
- Do not invent code that was not supplied.
- Do not give generic advice.
- Focus on contradictions, repeated patterns, and cross-slice ownership confusion.
- If evidence is insufficient, say exactly: INSUFFICIENT EVIDENCE.

Return exactly this shape:

# Cross-Slice Codemap
## 1. Stable Architecture Picture
- What stage ownership appears settled:
- What stage ownership still looks unstable:

## 2. Cross-Slice Problem Clusters
For each cluster:
- Cluster:
- Files or slices involved:
- Problem type:
- Why this is one connected problem instead of separate file issues:
- Best intervention point:

## 3. Canonical Ownership Matrix
For each important behavior family:
- Behavior family:
- Current owners observed:
- Recommended canonical owner:
- Files that should stop owning it:

## 4. Simplification Program
- Slice 1:
- Why first:
- Expected deletion/simplification payoff:

- Slice 2:
- Why second:
- Expected deletion/simplification payoff:

- Slice 3:
- Why third:
- Expected deletion/simplification payoff:

## 5. Test Strategy Implications
- Tests that are likely blocking simplification:
- Stable seams that need stronger coverage:
- Tests that should probably be deleted or rewritten:

## 6. Risks And Unknowns
- Risk 1:
- Risk 2:
- Unknown 1:
- Unknown 2:

If the uploaded files are insufficient, say exactly:
INSUFFICIENT EVIDENCE
and then list what is missing.
```
