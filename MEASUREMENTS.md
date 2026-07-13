# MEASUREMENTS.md — numbers measured in this repo (rule 14)

Headline results live here (committed); full tables in notes/ (scratch).

## M1 — LLM arithmetic error rate (measured 2026-07-13)

- Model: `claude-opus-4-8`, no tools, structured output, one call per problem.
- Operands: SEC-scale (5-7 significant digits × 1e6), 50 problems (growth `(B-A)/|A|` incl. negative bases, and margin `A/B`), seed 42.
- **Correct (rel. err < 1e-5): 21/50 — error rate 58.0%.**
- Gross errors (rel. err > 1e-3, would survive display rounding): 1/50.
- Max relative error: 1.97e-1.
- Full per-problem table: notes/measurements.md (local scratch).

Why it matters: this is the measured error rate the thesis rests on — all arithmetic on the answer path runs in `decimal.Decimal` with an emitted step trace, never in the model (CLAUDE.md rule 2).
