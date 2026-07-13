# CLAUDE.md — SEC Filing Intelligence take-home

## Thesis (never violate)
Every LLM output is either checked by deterministic code or explicitly
disclosed as unchecked. LLM proposes; code disposes.

## Rules
1. EXERCISE.md is the requirements ground truth. ARCHITECTURE.md and DESIGN.md are frozen: if implementation proves a decision wrong,
   STOP and flag it — never silently deviate. ARCHITECTURE_full.md is
   read-only reference.
2. All arithmetic in deterministic code with an emitted step trace. The LLM
   never computes, rounds, or restates a number.
3. No embeddings on the numeric answer path. Embeddings serve MD&A/risk
   prose retrieval only.
4. Numeric facts come only from the three primary financial statements.
5. EDGAR budget: 2 `submissions` calls + ≤20 one-time XBRL benchmark
   spot-checks. Zero calls on the query path. Log every call. Never
   hand-type manifest data — it comes from the API or not at all.
6. Build strictly by ARCHITECTURE.md §5.5 tiers: P0 demo-able end-to-end
   before any P1; P2 is never built. Features outside the tiers get flagged,
   not added.
7. Corpus = exactly these 6 PDFs in data/raw/, treated as opaque — never
   consult their HTML/XBRL versions for parsing or answering; no OCR:
   TSLA_10-K_FY2025, TSLA_10-Q_Q1-2026, TSLA_10-Q_Q1-2025,
   AAPL_10-K_FY2025, AAPL_10-Q_FQ2-2026, AAPL_10-Q_FQ2-2025 (.pdf).
   (Tesla's FY2025 10-K/A is a Part III amendment: manifest-recorded,
   statements unaffected.)
8. Refusal with a stated reason is a correct, first-class output. Never
   stretch to answer.
9. Benchmark expected values are entered by ME from the PDFs. Never generate
   or "fix" one — flag suspected errors for me to re-check.
10. The benchmark is the only accepted correctness measure; never report
    retrieval metrics as a proxy. A milestone is done only after a benchmark
    run reporting failures by which guard leaked.
11. Every guard gets at least one unit test proving it REJECTS bad input.
12. Stop for my review at every phase boundary and DESIGN.md milestone.
    When acceptance tests quarantine a statement, stop and show me the page —
    I am the review queue.
13. Surface data surprises (layouts, anchors, text-layer quality) immediately;
    never work around them silently. Every non-obvious choice gets one
    sentence of "why" where it lives.
14. Claims that need numbers (label-pair cosine, LLM arithmetic error rate)
    get measured in this repo → notes/measurements.md. Measured beats
    borrowed.
15. Stdlib and already-chosen deps first; a new dependency costs a one-line
    justification in DESIGN.md. API key from .env; data/, notes/, .env
    gitignored.