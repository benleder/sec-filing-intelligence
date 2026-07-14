# SEC Filing Intelligence — P0 demo

Grounded Q&A over six 10-K/10-Q PDFs (TSLA, AAPL). Thesis: **LLM proposes,
code disposes** — every LLM output is either checked by deterministic code or
explicitly disclosed as unchecked (see `DESIGN.md`, `DEVIATIONS.md`,
`MEASUREMENTS.md`).

## Setup

```sh
uv sync                          # Python 3.12, pinned deps
# .env with ANTHROPIC_API_KEY=...          (gitignored)
# data/raw/ with the 6 corpus PDFs          (gitignored)
```

## Build the store (one-time, ~5 min, ~$1.60)

```sh
uv run sfi manifest              # stage 0: 2 EDGAR calls + 1 bulk file -> join table
uv run sfi ingest --dry-run      # stage 1: 18/18 statement page ranges, no LLM
uv run sfi ingest                # stage 2/3: LLM parse -> checks 0-3 -> facts.sqlite
                                 # stops loudly at the first quarantine
```

Skip this if `data/store/facts.sqlite` already exists.

## Ask (the demo)

```sh
uv run sfi ask "What was Tesla's Q1 revenue change year-over-year?"
uv run sfi ask "What is Tesla's net income growth between 2025 and 2026?"   # honest refusal
uv run sfi ask "What was Microsoft's net income in the latest annual filing?" # out of corpus
uv run sfi ask "What was Apple's total revenue in 2025?" --json             # raw evidence object
```

Every answer prints: the planner's echo, the printed labels + pages + exact
fiscal dates for each fact, the Decimal calculation trace, and typed caveats.
Refusals carry the echo too.

## Prove it (benchmark)

```sh
uv run sfi bench validate        # 25 entries, schema + enum sanity
uv run sfi bench run             # ~$0.25: 25 questions -> pass/fail + failure class
uv run sfi bench spotcheck       # 10 expected values vs EDGAR XBRL (cached; 0 new calls)
uv run pytest -q                 # 150 tests incl. one rejection test per guard
uv run sfi measure llm-arithmetic  # ~$0.15: re-measure the M1 headline (MEASUREMENTS.md)
```

Latest committed run: `benchmark/reports/run-20260714T025948Z.json` — 25/25
(and `...025625Z.json`, 24/25, the run that caught the "last quarter" refusal
gap before it was fixed).

## Where the receipts live

- `data/edgar_log.jsonl` — every SEC call ever made (12 lifetime; 0 on the query path)
- `data/llm_usage.jsonl` — every LLM call + tokens (~$2.72 total build)
- `checks` table in `data/store/facts.sqlite` — per-fact accept/quarantine audit trail
- `DEVIATIONS.md` — every ratified deviation from the frozen design, with pinning tests
