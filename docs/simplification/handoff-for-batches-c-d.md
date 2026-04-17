# Handoff — Batches C & D, New Chat

> **Purpose:** Start a fresh Claude chat to draft Batches C and D of the Gemini audit pack. Current chat is token-heavy; new chat starts clean but needs enough context to resume without re-deriving.

## What to paste as the first message in the new chat

Paste the block between the rulers below, verbatim.

---

```
I'm continuing the Simplification & Consolidation Program for CrawlerAI. I already finished Batches A and B of the Gemini audit, updated two invariants, and have three Codex-ready slices authored. I need you to (1) draft Batch C and Batch D of the Gemini audit pack, and (2) be ready to ingest Batch C/D findings when they come back.

You are acting as senior system architect. Codex executes code. Gemini (Google AI Studio) runs targeted audits. I decide direction. Keep reads surgical. No one-shot work.

Read these files first, in order, surgically (don't dump full contents back at me):

1. docs/simplification/01-gemini-audit-prompt-pack.md — full prompt pack so far, including Batch A and B prompts. Batches C and D are placeholder-only at the bottom; your job is to fill them in using the same structure.
2. docs/simplification/02-batch-a-findings.md — Batch A results (extract-dir duplication, invariant clearances).
3. docs/simplification/03-batch-b-findings.md — Batch B results (policy fragmentation, circular import, dead inventory, cross-reference to EXTRACTION_ENHANCEMENT_SPEC.md).
4. docs/INVARIANTS.md — especially Invariants 6 (new backfill semantics) and 12 (new page-native identity semantics). Both were rewritten this week.
5. docs/simplification/slices/slice-0-dead-code-kill.md, slice-1-break-circular-policy-import.md, slice-2-consolidate-noise-rules.md — so you know what Codex is already chewing on and do not collide.
6. C:\Users\abhij\.claude\plans\i-need-your-help-dynamic-wreath.md — the original approved plan.
7. CLAUDE.md — project rules.

Then draft Batch C and Batch D in docs/simplification/01-gemini-audit-prompt-pack.md, appended to the existing file, using the SAME structure as Batch A/B (files to upload → system instruction → closed-template prompt → paste-back protocol).

Batch C — Page-type × surface branching, codebase-wide sweep.
- Scope: not just extract/ (Batch A already covered that). This batch hunts for page_type/surface/is_listing/is_detail branches anywhere in backend/app/services/**.
- Before drafting the prompt: run a grep to produce the exact file list Gemini should upload. Do NOT upload the full services tree — narrow to files with actual branches, or logical groups of them, to respect Gemini's skim-depth constraint.
- Deliverables Gemini must produce: branch inventory (file:line, function, variable, branch values, essential/accidental/unclear), cross-reference to Batch A's 15 extract/ branches (dedupe), ranked removability list.

Batch D — Unify leakage.
- Scope: pipeline/core.py, pipeline/stages.py, pipeline/runner.py, pipeline/field_normalization.py, pipeline/utils.py, publish/metadata.py, publish/verdict.py.
- Deliverables: every place pipeline/publish re-parses, re-cleans, or re-derives a field that extract should have emitted canonical. Produce leak inventory: file:line, function, field touched, kind of leak (re-parse / re-clean / re-derive / re-arbitrate), recommended extract-side owner.
- Add a short probe: per new Invariant 12, flag anywhere pipeline/publish force-fits a page-native field name into a canonical slot or vice versa.

Once Batch C and D prompts are drafted, save, and tell me to run them. Do NOT run them for me. I run Gemini, paste results back. You then produce 04-batch-c-findings.md and 05-batch-d-findings.md, and extend the slice backlog with Slices 3 and 4.

Current slice status: Slices 0/1/2 are in Codex's queue. Do not author Slice 3/4 until Batch C/D findings land.

Report structure for your first response: one sentence confirming what you read, one paragraph on Batch C/D scoping choices, then write the prompts.
```

---

## What NOT to paste in the new chat

- Raw Gemini Batch A or B deliverable output. That's already captured in the findings docs — re-pasting burns tokens.
- The full EXTRACTION_ENHANCEMENT_SPEC.md. New chat can read it surgically if needed.
- The full 27-file list from extract/. Already in the Batch A prompt.

## Memory note

Auto-memory entry `project_simplification_program.md` already records the program's working model, so the new chat will have that context without needing to re-derive it.

## If the new chat drifts

If it tries to do reads beyond the seven files listed, or starts drafting slices before Batch C/D findings exist, stop it and re-paste the rules block. The program's pace is the point.
