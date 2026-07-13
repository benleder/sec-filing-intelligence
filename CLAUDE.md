# CLAUDE.md — SEC Filing Intelligence take-home

## What this is
Interview take-home: a prototype that answers financial questions from SEC
filing PDFs with full traceability. The deliverable is graded on depth of
fundamentals, trust mechanisms, and honest self-assessment — NOT on polish,
feature count, or buzzwords. I (the candidate) must be able to explain and
defend every decision live in a walkthrough.

## Canonical documents (read in this order when context is needed)
- EXERCISE.md — the assignment. Source of truth for requirements and grading.
- ARCHITECTURE.md — frozen design decisions. Do not re-litigate them silently;
  if implementation reveals a decision is wrong, STOP and flag it to me.
- DESIGN.md — component-level implementation contract (same frozen rule once
  approved).
- ARCHITECTURE_full.md — reference appendix (long version). Read-only;
  never edit or extend it.

## The one-sentence thesis (never violate)
Every LLM output is either checked by deterministic code or explicitly
disclosed as unchecked. LLM proposes; code disposes.

## Hard rules
- ALL arithmetic in deterministic code with an emitted trace. The LLM never
  computes, rounds, or restates a number.
- No embeddings anywhere on the numeric answer path. Embeddings are for
  MD&A/risk-factor prose retrieval only.
- Numeric facts come only from the three primary financial statements.
- EDGAR API calls are rationed: 2 `submissions` calls (manifest) + ≤20
  one-time XBRL spot-checks for benchmark ground truth. Before ANY call:
  check and update the budget ledger; log every call (endpoint, count,
  purpose). Zero API calls on the query path, ever. Never hand-type manifest
  data — it must come from the API.
- Scope is governed by the P0/P1/P2 tiers in ARCHITECTURE.md §5.5. Never
  build P1 before P0 is demo-able end-to-end; never build P2 at all.
- Refusal with a stated reason is a valid, first-class output — never
  fabricate or stretch to answer.

## Data rules
- Corpus: 6 PDFs in `data/raw/`, named exactly:
  TSLA_10-K_FY2025.pdf, TSLA_10-Q_Q1-2026.pdf, TSLA_10-Q_Q1-2025.pdf,
  AAPL_10-K_FY2025.pdf, AAPL_10-Q_FQ2-2026.pdf, AAPL_10-Q_FQ2-2025.pdf
- Opaque-PDF rule: these PDFs are the only reality for parsing and answering.
  Never fetch or consult the filings' HTML/XBRL versions on those paths —
  the simulated-archive premise is part of the design.
- Native text layer only; no OCR (stated scope cut).
- Tesla filed a FY2025 10-K/A (routine Part III amendment). Record it in the
  manifest; it does not affect the primary financial statements.
- The benchmark's expected answers are populated by ME, by hand, from the
  PDFs. Never generate or "fix" expected values — if one looks wrong, flag it
  for me to re-check against the PDF.

## Working style
- Priority order: (1) correctness/trustworthiness of every number,
  (2) explainability — plain code and plain reasoning over clever
  abstractions, (3) simplicity/changeability, (4) scale (documented
  path only, never built).
- Co-ownership: for every non-obvious choice, one sentence of "why" in a
  comment or the doc — enough that I can defend it, not an essay.
- Phase discipline: each phase produces its artifact and STOPS for my
  review (DESIGN.md → implementation milestones). Do not run ahead.
- When real data contradicts an assumption (PDF layout, anchor phrase,
  text-layer quality), surface it immediately rather than working around
  it silently. Surprises are walkthrough material, not embarrassments.
- When acceptance tests quarantine a parsed statement, stop and show me the
  page and the failure — I am the human review queue.
- If a claim needs a number (embedding cosine on the net-income label pair;
  LLM arithmetic error rate on SEC-scale operands), measure it in this repo
  and record it in notes/measurements.md — measured beats borrowed.
- Prefer the standard library and already-chosen dependencies. Adding a
  dependency requires a one-line justification in DESIGN.md.
- ANTHROPIC_API_KEY from environment/.env; `data/`, `notes/` scratch, and
  `.env` are gitignored; docs and code are committed with clear messages.

## Testing discipline
- The hand-verified benchmark is the only accepted measure of correctness.
  Never report retrieval metrics as a proxy for answer correctness.
- Every guard (grounding check, typed periods, footing, numeral audit)
  gets at least one unit test proving it REJECTS bad input — a guard that
  only passes good input is untested.
- Run the benchmark before declaring any milestone done; report failures
  by which guard leaked, not just a score.
