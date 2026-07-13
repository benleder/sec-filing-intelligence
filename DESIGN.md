# SEC Filing Intelligence — DESIGN.md

**Status: implementation contract — frozen (CLAUDE.md rule 1).** Implementation
deviations stop and get flagged, never silently applied.

Scope of this document: component-level design detailed enough that implementation is
mechanical. P0 fully designed; P1 fully designed but cleanly separable (nothing in P0
imports, calls, or depends on P1 code); P2 schema-only. No implementation code beyond
schemas, signatures, and prompt skeletons.

## 0. Settled judgment calls

Calls this document makes that ARCHITECTURE.md does not fully determine. Each is
settled here with its rationale and referenced by J-number throughout.

| # | Decision | Rationale |
|---|---|---|
| J1 | **LLM = `claude-opus-4-8` for all three roles** (table parser, planner, composer). Estimated total project spend **< $15** (see §2). | The parser is the load-bearing extraction step (ARCHITECTURE weakness #1). The planner stays Opus-tier **permanently**: it is the one LLM step with no deterministic check behind it (weakness #4 — only the interpreted-question echo guards it), so it gets the most capable model, not the cheapest. The composer is the only future downgrade candidate, and only after the P1 numeral audit makes composer errors harmless (§8). At <$15 total, model-cost optimization is the wrong thing to optimize. |
| J2 | **Narrative/prose path is P1.5, built last** (after the four named P1 guards). P0 answers narrative questions with an explicit typed refusal. | Guards before features: a system that refuses narrative questions honestly beats one with fluent prose over an unhardened numeric path. Contingency, decided now: **if implementation time runs short, the narrative path is cut entirely and presented as a stated scope decision** — never rushed in unhardened. |
| J3 | **P0 composition is a deterministic template; the LLM composer ships only in P1, paired with the numeral audit.** | §5.5 puts the numeral audit in P1, and unchecked LLM composition in P0 would violate the thesis; a template is checked by construction. Where the architecture diagram (which shows LLM compose) and the §5.5 tiering conflict, the tiering governs. |
| J4 | **P1 embeddings via `sentence-transformers` (local, `all-MiniLM-L6-v2`)**, in a P1-only optional dependency group (torch ~2 GB) so P0 never installs it. | Local beats a second API key (Voyage) for demo-day reproducibility. Honesty bonus: the rule-14 cosine measurement runs on the *same model the prose path uses*, so the cited number describes this system, not a proxy. |
| J5 | **Parser retry policy: exactly one re-parse with check-failure feedback appended, then quarantine.** | One retry absorbs transient formatting slips; more would mask *systematic* parse problems that the human review queue needs to see. Cheap retries hide exactly the failures that are walkthrough material. |
| J6 | **The fact store keeps *every* accepted cell, including rows not in the dictionary** (`concept` nullable). | Two P1 features depend on stored raw labels: the fuzzy fallback searches them, and footing checks sum component rows that are mostly non-dictionary labels ("Automotive sales" etc.). Also the plain reading of "each accepted cell becomes a fact" (ARCHITECTURE §3 stage 3). |
| J7 | **CIK resolution via SEC's bulk `company_tickers.json`** — one cached download, logged in the ledger, accounted as a bulk-file fetch, not against the 2-call `submissions` budget. | Same precedent ARCHITECTURE §8 sets for the bulk Financial Statement Data Sets, and the bulk/API distinction is the SEC's own (bulk files exist to keep scripted lookups off the rate-limited API). The alternative — hand-typing CIKs — violates rule 5's spirit. Nothing is hidden: the fetch is in the ledger regardless. |

---

## 1. Repo layout and module map

```
sec-filing-intelligence/
├── CLAUDE.md  EXERCISE.md  ARCHITECTURE.md  ARCHITECTURE_full.md  DESIGN.md
├── pyproject.toml                # uv-managed; deps pinned; optional group "prose" (P1)
├── .env                          # ANTHROPIC_API_KEY (gitignored)
├── data/                         # gitignored
│   ├── raw/                      # the 6 corpus PDFs (opaque; never HTML/XBRL)
│   ├── manifest/                 # manifest.json + cached raw EDGAR responses
│   ├── store/facts.sqlite        # the fact store (+ prose chunks, P1)
│   └── edgar_log.jsonl           # append-only ledger of EVERY outbound SEC request
├── notes/measurements.md         # gitignored; rule-14 measured numbers live here
├── benchmark/
│   ├── benchmark.yaml            # hand-authored by Ben (template in §6)
│   └── reports/                  # scored runs, one JSON per run (committed)
├── src/sfi/
│   ├── common/                   #  L0 — imports stdlib only
│   │   ├── config.py             # paths, .env loading (tiny stdlib parser), constants
│   │   ├── models.py             # frozen dataclasses: Filing, Period, Fact, CheckResult…
│   │   ├── periods.py            # fiscal-calendar resolution; Period type & arithmetic
│   │   └── edgar.py              # the ONLY module allowed to touch sec.gov; logs every call
│   ├── concepts/                 #  L1 — imports common
│   │   ├── dictionary.py         # load + validate concepts.yaml; matching semantics (§3.2)
│   │   └── concepts.yaml         # the dictionary (checked in — it's code, not data)
│   ├── store/                    #  L1 — imports common
│   │   ├── schema.sql            # full DDL (§3.1), including P1/P2 tables & columns
│   │   └── db.py                 # FactWriter (used by ingest), FactReader (used by query)
│   ├── llm/                      #  L1 — imports common
│   │   └── client.py             # thin Anthropic wrapper: structured-output call, retries, usage log
│   ├── ingest/                   #  L2 — imports common, concepts, store(write), llm. NEVER query/.
│   │   ├── manifest.py           # stage 0: 2 submissions calls → manifest.json
│   │   ├── segment.py            # stage 1: anchor rules → statement page ranges
│   │   ├── extract.py            # stage 2: LLM parser call (prompt in §4.1)
│   │   ├── accept.py             # acceptance tests (§4.3): periods, grounding, scale, balance; P1 footing
│   │   ├── run.py                # per-filing orchestrator: segment→extract→accept→write
│   │   ├── tie_check.py          # P1: cross-filing agreement/conflict
│   │   └── prose.py              # P1: MD&A/Item-1A chunking + embedding
│   ├── query/                    #  L2 — imports common, concepts, store(read), llm. NEVER ingest/.
│   │   ├── types.py              # Plan, ResolvedQuery, Refusal, CandidateList, AnswerResult…
│   │   ├── plan.py               # LLM: question → structured query (§3.5)
│   │   ├── resolve.py            # code: aliases → typed periods; corpus/dictionary gate
│   │   ├── retrieve.py           # code: keyed lookup; P1 fuzzy fallback
│   │   ├── compute.py            # code: Decimal arithmetic with emitted trace
│   │   ├── evidence.py           # evidence-object assembly (§3.4) + allowed-renderings
│   │   ├── compose.py            # P0 deterministic template; P1 LLM composer
│   │   ├── audit.py              # P1: numeral audit (§5.6)
│   │   ├── narrative.py          # P1: prose retrieval (embeddings) + quote assembly
│   │   └── pipeline.py           # answer(question) orchestrator
│   ├── bench/                    #  L3 — imports query (public API only) + common
│   │   ├── runner.py             # runs benchmark.yaml through query.pipeline.answer
│   │   ├── score.py              # correctness rules + failure classification (§6)
│   │   └── xbrl_spotcheck.py     # ≤20 one-time XBRL calls validating Ben's expected values
│   ├── measure/                  #  L3 — rule-14 experiments → notes/measurements.md
│   │   ├── llm_arithmetic.py     # LLM arithmetic error rate on SEC-scale operands
│   │   └── label_cosine.py       # P1: cosine of the net-income label pair
│   └── cli.py                    #  L4 — argparse entry point; imports everything below
└── tests/                        # pytest; mirrors src layout; every guard has a rejection test
```

**Dependency direction (enforced by review; arrows point down only):**

```
cli  →  { ingest, query, bench, measure }
bench, measure  →  query (public answer() only), llm, common
ingest  →  { store.write, concepts, llm, common }      ingest NEVER imports query
query   →  { store.read,  concepts, llm, common }      query  NEVER imports ingest
store, concepts, llm  →  common
common  →  stdlib only
```

The only coupling between ingest and query is the SQLite file itself; its contract is
`schema.sql` (§3.1), not Python imports. `common/edgar.py` is the single chokepoint for
network access: every function in it appends one line to `data/edgar_log.jsonl` before
the request is sent (rule 5 — log every call). No other module may import `urllib`.

---

## 2. Tech choices

**Python 3.12 (via uv).** System python is 3.9 (near EOL, no modern typing); 3.12 is the
boring current stable and is already installed (`~/.local/bin/python3.12`); uv (installed)
pins everything in `pyproject.toml`/`uv.lock` so the demo is reproducible on interview day.

**PDF text extraction: `pdfplumber`.** Pure-Python on pdfminer.six, extremely
well-documented, and gives exactly the two things the pipeline needs: per-page text with
`layout=True` (preserves visual column alignment — the LLM parser's input) and per-word
bounding boxes (`extract_words()`) held in reserve as richer layout hints if plain layout
text proves insufficient (§8-open). PyMuPDF is faster but speed is irrelevant at 6 PDFs
and pdfplumber's word-geometry API is a better fit. *Dep justification (rule 15): the one
library whose job is exactly "text layer + layout from born-digital PDFs."*

**LLM: Anthropic API, `claude-opus-4-8` for all three roles** (J1). Rationale:
the table parser is the single load-bearing LLM step (ARCHITECTURE weakness #1) — use the
most capable generally-available tier; using the same model for planner and composer keeps
one code path and one behavioral surface to reason about. All calls use **structured
outputs** (`output_config.format` with a JSON schema) so parsing the LLM's reply is never
string-munging — the API guarantees schema-valid JSON. No temperature knob exists on Opus
4.8 (removed); determinism is not assumed anywhere — acceptance tests, not sampling
settings, carry correctness. **Cost estimate:** ingestion ≈ 18 statements × (~8K in +
~4K out) ≈ 150K in / 75K out ≈ **$2.60**; one full benchmark run ≈ 25 questions × 2 LLM
calls × (~2K in / 0.5K out) ≈ **$0.90/run**; with retries, re-ingests, and ~10 benchmark
runs during development: **comfortably under $15 total**. *Dep justification: `anthropic`
— official SDK, retries and structured outputs built in.*

**Embedding model (P1 only): `sentence-transformers` with `all-MiniLM-L6-v2`** (flagged
J4). Local, free, no second API key, ~80 MB model, runs instantly on this machine, and is
the classic boring baseline. It serves two purposes: the MD&A/risk prose index, and the
rule-14 measurement of the "Net income" vs "Net income attributable to common
stockholders" cosine — measuring on the *same* model the prose path uses makes the number
honest. Installed as an optional dependency group (`uv sync --group prose`) so P0 never
pays the torch install. *Dep justification: the standard local embedding harness; the
alternative (Voyage) adds an API key and a network dependency to the demo.*

**CLI: stdlib `argparse` with subcommands.** No rich/typer/click — rule 15 stdlib-first,
and the rubric discounts polish. Subcommands: `manifest`, `ingest`, `ask`, `bench`,
`measure` (§5.8). Plain-text rendering with a `--json` flag that dumps the evidence object.

**Storage: stdlib `sqlite3`, no ORM; `decimal.Decimal` for all values** (stored as exact
decimal strings — floats never touch a financial number, so traces are exact). **YAML
(`PyYAML`, `safe_load` only) for the two hand-authored files** — concept dictionary and
benchmark: both are nested, hand-edited documents where comments matter; TOML (stdlib)
was considered and rejected because nested lists-of-tables make hand-authoring 25
benchmark entries genuinely unpleasant. *Dep justification: `PyYAML` — hand-authored
nested config with comments.* `.env` is parsed by a five-line loader in `config.py`
(stdlib-first; it's one `KEY=value` line). *Dev dep: `pytest` — the guard rejection tests
(rule 11) need a runner.*

Full dependency list: `anthropic`, `pdfplumber`, `pyyaml`; dev: `pytest`; optional group
`prose` (P1): `sentence-transformers`. Everything else is stdlib.

---

## 3. Data contracts

This section is the heart of the document. Anything reading or writing these shapes
conforms to what's written here; changing a contract after approval is a flagged event.

### 3.1 Fact store — SQLite DDL (`src/sfi/store/schema.sql`)

P1/P2 tables and columns are created from day one (schema stability; empty tables are
free) but only written by their tier's code. Annotations mark tier ownership.

```sql
PRAGMA foreign_keys = ON;

-- Stage 0 output. One row per filing known to the manifest (including the 10-K/A
-- amendment record, which has no PDF of its own).
CREATE TABLE filings (
    accession_no      TEXT PRIMARY KEY,             -- from EDGAR, never hand-typed
    ticker            TEXT NOT NULL,                -- 'TSLA' | 'AAPL'
    cik               TEXT NOT NULL,                -- zero-padded, from company_tickers.json
    form_type         TEXT NOT NULL,                -- '10-K' | '10-Q' | '10-K/A'
    filing_date       TEXT NOT NULL,                -- ISO date, EDGAR filingDate
    period_end        TEXT NOT NULL,                -- ISO date, EDGAR reportDate (fiscal period end)
    fiscal_year       INTEGER NOT NULL,             -- resolved via fiscal calendar (§3.3)
    fiscal_period     TEXT NOT NULL,                -- 'FY' | 'Q1' | 'Q2' | 'Q3'
    amends_accession  TEXT REFERENCES filings(accession_no),  -- P2: restatement preference
    pdf_path          TEXT,                         -- relative path under data/raw/; NULL for 10-K/A
    ingested_at       TEXT                          -- NULL until ingest completes
);

-- Stage 1+2 bookkeeping. One row per located primary statement per filing.
CREATE TABLE statements (
    id                 INTEGER PRIMARY KEY,
    accession_no       TEXT NOT NULL REFERENCES filings,
    statement_type     TEXT NOT NULL CHECK (statement_type IN ('INCOME','BALANCE','CASHFLOW')),
    page_start         INTEGER NOT NULL,            -- 1-based PDF page numbers
    page_end           INTEGER NOT NULL,
    anchor_text        TEXT NOT NULL,               -- the anchor phrase actually matched
    parse_status       TEXT NOT NULL CHECK (parse_status IN ('PENDING','ACCEPTED','QUARANTINED')),
    quarantine_reason  TEXT,                        -- human-readable; P2 review tooling reads this
    parser_model       TEXT,                        -- e.g. 'claude-opus-4-8'
    prompt_version     TEXT,                        -- hash/tag of the parser prompt (reproducibility)
    parsed_at          TEXT,
    UNIQUE (accession_no, statement_type)
);

-- The facts. One row per accepted CELL per filing appearance: the same economic fact
-- (e.g. TSLA FY2024 net income) appears as multiple rows when multiple filings print it
-- (primary column in the FY2024 10-K, comparative column in the FY2025 10-K) — this is
-- the per-filing provenance record set that powers the P1 tie check.
CREATE TABLE facts (
    id                  INTEGER PRIMARY KEY,
    statement_id        INTEGER NOT NULL REFERENCES statements,
    accession_no        TEXT NOT NULL REFERENCES filings,
    ticker              TEXT NOT NULL,
    statement_type      TEXT NOT NULL,
    -- concept mapping (nullable: unmapped rows are stored too — J6)
    concept             TEXT,                       -- canonical id from concepts.yaml, or NULL
    match_method        TEXT CHECK (match_method IN ('dictionary_exact','dictionary_pattern')
                                    OR match_method IS NULL),
        -- how raw_label → concept was decided AT INGESTION. Query-time fuzzy matches are
        -- never persisted; they surface only in the evidence object as
        -- match_method='label_similarity' (§3.4). NULL concept ⇒ NULL match_method.
    raw_label           TEXT NOT NULL,              -- exactly as printed; always travels with the fact
    row_index           INTEGER NOT NULL,           -- 0-based within the parsed statement
    indent_level        INTEGER,
    is_subtotal         INTEGER NOT NULL DEFAULT 0,
    page                INTEGER NOT NULL,           -- page this cell's digits appear on
    -- typed period (never a string like "Q1"; resolution in §3.3)
    period_start        TEXT,                       -- ISO date; NULL iff duration_type='INSTANT'
    period_end          TEXT NOT NULL,              -- ISO date
    duration_type       TEXT NOT NULL CHECK (duration_type IN ('INSTANT','QUARTER','YTD','FISCAL_YEAR')),
    fiscal_year         INTEGER NOT NULL,
    fiscal_period       TEXT NOT NULL,              -- display label: 'FY' | 'Q1' | 'Q2' | 'Q3'
    -- values
    value_raw           TEXT NOT NULL,              -- as printed, e.g. '(1,204)' or '$96,773'
    value_normalized    TEXT NOT NULL,              -- exact decimal string, sign + scale applied: '-1204000000'
    unit                TEXT NOT NULL CHECK (unit IN ('USD','USD_PER_SHARE','SHARES')),
    scale               INTEGER NOT NULL,           -- multiplier applied: 1 | 1000 | 1000000
    verification_status TEXT NOT NULL DEFAULT 'UNVERIFIED'
                        CHECK (verification_status IN ('UNVERIFIED','VERIFIED','CONFLICTING')),
        -- P0 writes UNVERIFIED only; P1 tie check upgrades; the three-state DISPLAY is P2.
    superseded_by       INTEGER REFERENCES facts(id)   -- P2: restatement preference (never written P0/P1)
);
CREATE INDEX idx_facts_lookup ON facts (ticker, concept, duration_type, period_end);
CREATE INDEX idx_facts_labels ON facts (ticker, statement_type, raw_label);

-- Acceptance-test audit trail: every check that ran, per statement or per fact.
CREATE TABLE checks (
    id            INTEGER PRIMARY KEY,
    statement_id  INTEGER NOT NULL REFERENCES statements,
    fact_id       INTEGER REFERENCES facts,          -- NULL for statement-level checks
    check_name    TEXT NOT NULL,                     -- 'period'|'grounding'|'scale'|'balance'|'footing'(P1)
    status        TEXT NOT NULL CHECK (status IN ('PASS','FAIL','INCONCLUSIVE')),
    detail        TEXT                                -- e.g. "token '1,204' not found on page 23"
);

-- P1: cross-filing tie check results over overlapping facts.
CREATE TABLE fact_ties (
    id          INTEGER PRIMARY KEY,
    fact_id_a   INTEGER NOT NULL REFERENCES facts,
    fact_id_b   INTEGER NOT NULL REFERENCES facts,
    status      TEXT NOT NULL CHECK (status IN ('AGREE','CONFLICT')),
    checked_at  TEXT NOT NULL
);

-- P1: narrative sections, chunked and embedded. Prose NEVER yields computable facts.
CREATE TABLE prose_chunks (
    id            INTEGER PRIMARY KEY,
    accession_no  TEXT NOT NULL REFERENCES filings,
    section       TEXT NOT NULL CHECK (section IN ('MDA','RISK_FACTORS')),
    page_start    INTEGER NOT NULL,
    page_end      INTEGER NOT NULL,
    chunk_index   INTEGER NOT NULL,
    text          TEXT NOT NULL,
    embedding     BLOB                                -- float32[384]; brute-force cosine at query time
);
```

P2 presence in this schema (designed, not built): `filings.amends_accession`,
`facts.superseded_by`, the `CONFLICTING`/three-state display semantics of
`verification_status`, and `statements.quarantine_reason` as the hook for review tooling.
No P0/P1 code writes `superseded_by`; amendment preference is "record and flag" only.

**Re-ingest semantics (`db.py`):** re-running ingest for a filing calls
`FactWriter.replace_filing(accession_no)`, which — in a single transaction — deletes that
filing's rows from `checks`, `fact_ties` (any tie touching its facts), `facts`, and
`statements`, demotes to `UNVERIFIED` any surviving fact whose only `AGREE` tie was just
deleted, and resets `filings.ingested_at` to NULL before the rewrite. Ties are then
rebuilt by the next `sfi tie-check` run (P1). Ingest is thereby idempotent per filing:
the store's state is a function of the current parser output, never an accumulation of
runs — which is what makes "re-ingest after a prompt/dictionary change" (P1.1) a safe,
boring operation.

### 3.2 Concept dictionary — `src/sfi/concepts/concepts.yaml`

Checked into git (it's curated logic, not data). ~19 concepts; the exact label strings
are authored in P0.4 by reading the actual PDFs (this is curation, not manifest data —
rule 5 does not apply; rule 9 applies only to benchmark expected *values*).

```yaml
# Format version — dictionary.py validates on load and hard-fails on unknown keys.
version: 1

concepts:
  # ---- income statement ----------------------------------------------------
  revenue:
    statement: INCOME
    unit: USD
    description: "Total revenues / total net sales (GAAP top line)"
    labels:                       # exact-match strings per company, normalized per §matching
      TSLA: ["Total revenues"]
      AAPL: ["Total net sales"]
    label_patterns: []            # optional anchored regexes; used only when exact match fails
    typical_magnitude: [1.0e+9, 1.0e+12]   # scale-sanity band for value_normalized (USD)
  cost_of_revenue:      {statement: INCOME, unit: USD, labels: {...}, typical_magnitude: [...]}
  gross_profit:         {statement: INCOME, unit: USD, labels: {TSLA: ["Gross profit"], AAPL: ["Gross margin"]}, ...}
    # NB: Apple prints the DOLLAR line as "Gross margin" — exactly the near-miss the
    # dictionary exists to pin down.
  rd_expense:           {statement: INCOME, unit: USD, ...}
  sga_expense:          {statement: INCOME, unit: USD, ...}
  total_operating_expenses: {statement: INCOME, unit: USD, ...}
  operating_income:     {statement: INCOME, unit: USD, ...}
  net_income:
    statement: INCOME
    unit: USD
    labels: {TSLA: ["Net income"], AAPL: ["Net income"]}
    disambiguate_from: [net_income_attributable_common]
  net_income_attributable_common:
    statement: INCOME
    unit: USD
    labels: {TSLA: ["Net income attributable to common stockholders"], AAPL: []}
    disambiguate_from: [net_income]
  eps_basic:            {statement: INCOME, unit: USD_PER_SHARE, typical_magnitude: [0.01, 1000]}
  eps_diluted:          {statement: INCOME, unit: USD_PER_SHARE, typical_magnitude: [0.01, 1000]}
  # ---- balance sheet ---------------------------------------------------------
  cash_and_equivalents:          {statement: BALANCE, unit: USD, ...}
  total_assets:                  {statement: BALANCE, unit: USD, ...}
  total_liabilities:             {statement: BALANCE, unit: USD, ...}
  total_equity:                  {statement: BALANCE, unit: USD, ...}
  total_liabilities_and_equity:  {statement: BALANCE, unit: USD, ...}
  # ---- cash flow --------------------------------------------------------------
  operating_cash_flow:  {statement: CASHFLOW, unit: USD, ...}
  investing_cash_flow:  {statement: CASHFLOW, unit: USD, ...}
  financing_cash_flow:  {statement: CASHFLOW, unit: USD, ...}

# Explicit near-miss pairs, mirrored from per-concept disambiguate_from. dictionary.py
# validates symmetry. Purpose: (a) documentation of the trap, (b) the matching rule below,
# (c) the P1 fuzzy fallback refuses to auto-pick between members of a pair.
disambiguation_pairs:
  - [net_income, net_income_attributable_common]

# Per-company printed footing structure — consumed ONLY by the P1 footing check.
# Contents authored in P1.1 from the real statements; format fixed now.
footing:
  TSLA:
    INCOME:
      - total: "Total revenues"
        components: ["Automotive sales", "Automotive regulatory credits", "..."]
      - total: "Total operating expenses"
        components: ["Research and development", "Selling, general and administrative", "..."]
    BALANCE: []       # balance sheet already covered by the P0 equation check; add sub-foots if cheap
    CASHFLOW: []
  AAPL:
    INCOME: [...]
```

**Matching semantics (implemented in `dictionary.py`, used at ingestion):**

1. Normalize both sides: casefold, collapse internal whitespace, strip leading/trailing
   punctuation and footnote markers (`(1)`, `*`, trailing `:`).
2. A raw label maps to concept C iff it exactly equals one of C's `labels[company]`
   entries (or fully matches an anchored `label_patterns` regex when no exact entry hits).
3. If a raw label matches **two or more** concepts, it maps to **none** — a warning check
   row is written and the row is stored unmapped. Conservative by design: an ambiguous
   mapping must never silently pick a side (rule 11 test: a crafted label matching both
   members of a disambiguation pair is rejected).
4. Longest-label-wins is deliberately NOT implemented; explicit per-company label lists
   make precedence unnecessary, and implicit precedence is exactly how near-misses sneak in.

**Derived metrics** are not dictionary entries — they are compute-layer formulas over
concepts (§5.4): `gross_margin = gross_profit / revenue`, `operating_margin =
operating_income / revenue`, `net_margin = net_income / revenue`.

### 3.3 Filing manifest — `data/manifest/manifest.json`

Produced by `ingest/manifest.py` from exactly 2 `submissions` API calls (plus the one
bulk `company_tickers.json` fetch, J7). Raw API responses are cached beside it so the
manifest can be rebuilt with zero further calls. **No field in this file is ever
hand-typed** (rule 5); the only human input is the ticker list and the filename→accession
join *confirmation* (the join itself is computed, see below).

```json
{
  "generated_at": "2026-07-12T00:00:00Z",
  "edgar_requests": [
    {"url": "https://www.sec.gov/files/company_tickers.json", "purpose": "cik_resolution", "kind": "bulk_file"},
    {"url": "https://data.sec.gov/submissions/CIK0001318605.json", "purpose": "manifest", "kind": "api"},
    {"url": "https://data.sec.gov/submissions/CIK0000320193.json", "purpose": "manifest", "kind": "api"}
  ],
  "companies": {
    "TSLA": {"cik": "0001318605", "name": "...", "fiscal_year_end_mmdd": "--12-31"},
    "AAPL": {"cik": "0000320193", "name": "...", "fiscal_year_end_mmdd": "--09-27"}
  },
  "filings": [
    {
      "ticker": "TSLA",
      "accession_no": "<from API>",
      "form_type": "10-K",
      "filing_date": "<from API>",
      "period_end": "<from API reportDate>",
      "fiscal_year": 2025,
      "fiscal_period": "FY",
      "is_amendment": false,
      "amends_accession": null,
      "pdf_path": "data/raw/TSLA_10-K_FY2025.pdf"
    }
    // … 6 PDF-backed entries + the TSLA 10-K/A record (pdf_path: null, amends_accession set)
  ]
}
```

**Filename↔accession join:** computed by matching each `data/raw/*.pdf` filename's
`(ticker, form, fiscal label)` against the manifest's `(ticker, form_type, fiscal_year,
fiscal_period)`. If any PDF matches zero or ≥2 manifest entries, `sfi manifest` hard-fails
and shows the ambiguity — surfaced, never guessed (rule 13).

**Fiscal calendar resolution (`common/periods.py`):** a company's `fiscal_year_end_mmdd`
plus each filing's exact `period_end` define the calendar. Rules:
- `FY{y}` → `FISCAL_YEAR` duration ending at that fiscal year's filed `period_end`
  (dates from the manifest, never computed from a formula — Apple's 52/53-week calendar
  makes formulas wrong; we only ever *print* the exact dates, per ARCHITECTURE §7.6).
- `Q{n} FY{y}` → `QUARTER` duration; the quarter's `period_end` comes from the 10-Q's
  manifest entry when we hold that filing, else from a parsed comparative column header
  (validated in §4.3-check-0).
- Alias resolution ("2025", "last quarter", "Q1 2026") happens in `query/resolve.py`
  against this calendar; anything not resolvable to a period **we hold data for** becomes
  a typed refusal, including the FY2026 honesty case ("not filed as of 2026-07-12").

### 3.4 Evidence object — JSON schema (every numeric answer carries one)

The five parts of ARCHITECTURE §5.2, machine-readable. Rendered by `compose.py`; dumped
verbatim by `--json`; consumed by the benchmark scorer and (P1) the numeral audit.

```json
{
  "schema_version": 1,
  "question_verbatim": "What was Tesla's Q1 revenue change year-over-year?",

  "interpreted_question": {                      // part 1 — the planner's echo
    "restatement": "Growth of TSLA revenue, Q1 FY2026 vs Q1 FY2025 (three-month periods).",
    "structured_query": { /* the Plan object, §3.5, verbatim */ }
  },

  "facts_used": [                                // part 2 — one entry per fact
    {
      "fact_id": 123,
      "company": "TSLA",
      "concept": "revenue",
      "raw_label": "Total revenues",             // as printed — always shown
      "match_method": "dictionary_exact",        // or 'label_similarity' (P1 fuzzy, never stored)
      "filing": {"form_type": "10-Q", "accession_no": "…", "filing_date": "2026-04-…"},
      "statement": "INCOME",
      "page": 9,
      "period": {"start": "2026-01-01", "end": "2026-03-31",
                 "duration_type": "QUARTER", "fiscal_label": "Q1 FY2026"},
      "value_raw": "19,335",
      "value_normalized": "19335000000",
      "unit": "USD",
      "scale": 1000000,
      "verification_status": "UNVERIFIED"
    }
  ],

  "calculation": {                               // part 3 — emitted by compute.py, never the LLM
    "operation": "growth",
    "steps": [
      {"n": 1, "describe": "delta = 19335000000 - 21301000000", "value": "-1966000000"},
      {"n": 2, "describe": "growth = delta / |21301000000|",     "value": "-0.0922961..."}
    ],
    "result": {"value": "-0.0922961...", "unit": "ratio", "formatted": "-9.2%"},
    "allowed_renderings": ["-9.2%", "-9.23%", "-0.092", "$19,335 million", "$19.3 billion", "..."]
        // code-generated whitelist for every number in this object — the P1 numeral
        // audit accepts a value-class token iff it appears here (§5.6)
  },

  "verification_status": "UNVERIFIED",           // part 4 — min over facts_used

  "caveats": [                                   // part 5 — typed, enumerable
    {"code": "UNAUDITED_INTERIM", "text": "10-Q figures are unaudited."},
    {"code": "FISCAL_CALENDAR",   "text": "Periods are fiscal; exact dates shown above."}
    // other codes: FUZZY_SINGLE_MATCH (P1), NEAR_MISS_ALTERNATIVES (P1),
    //              CONFLICTING_SOURCES, UNVERIFIED_FACT, SIGN_CONVENTION
  ]
}
```

For refusals, candidates, and conflicts, a reduced object is emitted with
`interpreted_question`, the refusal payload, and `caveats` — traceability applies to
"no" answers too.

### 3.5 Planner structured-query schema (LLM output, forced via structured outputs)

The planner **extracts**; it never decides refusals. Every gate (corpus membership,
dictionary membership, period availability) is deterministic code in `resolve.py`, so a
planner hallucination can misread a question (visible in the echo) but cannot invent an
answerable one.

```json
{
  "type": "object", "additionalProperties": false,
  "required": ["intent", "company_text", "company", "concept_text", "concept",
               "operation", "periods_text", "periods", "notes"],
  "properties": {
    "intent":      {"enum": ["numeric", "rank_changes", "narrative", "other"]},
    "company_text":{"type": "string"},                    // phrase the user used
    "company":     {"enum": ["TSLA", "AAPL", "OTHER", "NONE"]},
    "concept_text":{"type": "string"},
    "concept":     {"enum": ["revenue", "...all dictionary ids...", "DERIVED_GROSS_MARGIN",
                             "DERIVED_OPERATING_MARGIN", "DERIVED_NET_MARGIN", "OTHER", "NONE"]},
                   // enum injected from concepts.yaml at call time so the planner can
                   // only name concepts that exist (or say OTHER)
    "operation":   {"enum": ["value", "growth", "delta", "margin", "rank_deltas"]},
    "periods_text":{"type": "string"},
    "periods":     {"type": "array", "maxItems": 2, "items": {
                      "type": "object", "additionalProperties": false,
                      "required": ["fiscal_year", "fiscal_period"],
                      "properties": {
                        "fiscal_year":   {"type": ["integer", "null"]},   // null = "latest"
                        "fiscal_period": {"enum": ["FY", "Q1", "Q2", "Q3", "LATEST"]}
                      }}},
    "narrative_topic": {"type": ["string", "null"]},
    "notes":       {"type": "string"}                      // planner's stated uncertainty, shown in echo
  }
}
```

**Planner prompt skeleton** (`plan.py`; full text finalized in implementation):

```
SYSTEM: You convert one natural-language question about SEC filings into a structured
query. You do not answer questions, compute, or judge answerability. Extract exactly
what was asked, using ONLY the enum values provided. If the company or metric is not
in the enums, use OTHER. If a year could be calendar or fiscal, treat it as fiscal and
say so in notes. Today's date is {today}. Known corpus: {ticker → filings summary}.
Concept glossary: {id: description, one per line}.

USER: {question}
```

---

## 4. LLM parser contract (ingest stage 2) and acceptance harness

### 4.1 Parser input and prompt skeleton

Input per statement: the located page range's text, one block per page, each extracted
with `pdfplumber.Page.extract_text(layout=True)` (whitespace-preserving so columns align
visually), wrapped in explicit page markers. Layout-hints v1 = this layout text alone;
richer hints (per-line word x-positions) are a designed fallback, format left open (§8).

```
SYSTEM: You transcribe the structure of one financial statement from PDF text. You are a
PARSER, not an analyst. Hard rules:
- TRANSCRIBE, never compute, never infer, never correct. If a value is missing or
  illegible, omit the cell — do not guess.
- Copy label and value characters EXACTLY as printed, including commas, parentheses,
  and '$'. Do not normalize numbers.
- Report the scale declaration verbatim (e.g. "(in millions, except per share data)")
  and your reading of it.
- Report each column header verbatim and your reading of its period (start/end dates,
  duration kind). Do not resolve fiscal aliases beyond what is printed.
- For each cell, report the page number whose text contains it.
Nothing you output is trusted; every cell will be verified against the source page.

USER:
statement_type: INCOME
company: TSLA        form: 10-Q        pages: 9-10
--- page 9 ---
{layout-preserved text}
--- page 10 ---
{layout-preserved text}
```

On a retry after check failure (J5): the same prompt plus one appended block
`PREVIOUS ATTEMPT FAILED CHECKS:\n{check_name}: {detail}\n...` — one retry, then quarantine.

### 4.2 Parser output schema (structured output, forced)

```json
{
  "type": "object", "additionalProperties": false,
  "required": ["statement_type", "scale", "columns", "rows"],
  "properties": {
    "statement_type": {"enum": ["INCOME", "BALANCE", "CASHFLOW"]},
    "scale": {
      "type": "object", "additionalProperties": false,
      "required": ["text_verbatim", "multiplier", "per_share_exception"],
      "properties": {
        "text_verbatim":       {"type": "string"},
        "multiplier":          {"enum": [1, 1000, 1000000]},
        "per_share_exception": {"type": "boolean"}   // "except per share data" present
      }},
    "columns": {"type": "array", "minItems": 1, "items": {
      "type": "object", "additionalProperties": false,
      "required": ["index", "header_verbatim", "period_start", "period_end", "duration"],
      "properties": {
        "index":           {"type": "integer"},
        "header_verbatim": {"type": "string"},
        "period_start":    {"type": ["string", "null"]},   // ISO date; null for INSTANT
        "period_end":      {"type": "string"},
        "duration":        {"enum": ["INSTANT", "QUARTER", "YTD", "FISCAL_YEAR"]}
      }}},
    "rows": {"type": "array", "items": {
      "type": "object", "additionalProperties": false,
      "required": ["row_index", "label_verbatim", "indent_level", "is_subtotal", "cells"],
      "properties": {
        "row_index":     {"type": "integer"},
        "label_verbatim":{"type": "string"},
        "indent_level":  {"type": "integer"},
        "is_subtotal":   {"type": "boolean"},
        "cells": {"type": "array", "items": {
          "type": "object", "additionalProperties": false,
          "required": ["column_index", "value_verbatim", "page"],
          "properties": {
            "column_index":  {"type": "integer"},
            "value_verbatim":{"type": "string"},     // exactly as printed: "(1,204)", "$96,773", "2.13"
            "page":          {"type": "integer"}
          }}}
      }}}
  }
}
```

Normalization from `value_verbatim` → `value_normalized` is **code** (`accept.py`):
strip `$`/commas, parentheses ⇒ negative, apply `scale.multiplier` unless the row is
per-share (dictionary `unit: USD_PER_SHARE` or label contains "per share", in which case
multiplier 1 — the benchmark's scale trap). Decimal end to end.

### 4.3 Acceptance harness (`ingest/accept.py`) — signatures and behavior specs

Common result type (in `common/models.py`):

```python
@dataclass(frozen=True)
class CheckResult:
    check_name: str                     # 'period' | 'grounding' | 'scale' | 'balance' | 'footing'
    status: Literal['PASS', 'FAIL', 'INCONCLUSIVE']
    fact_ref: tuple[int, int] | None    # (row_index, column_index) or None for statement-level
    detail: str                         # human-readable, stored in checks.detail
```

**Check 0 — period validation** *(part of the P0 "typed periods" guard)*

```python
def check_periods(columns: list[ParsedColumn], filing: Filing,
                  calendar: FiscalCalendar) -> list[CheckResult]
```
Spec — evaluated **per duration group** (columns bucketed by `duration`), because 10-Q
income and cash-flow statements legitimately print multiple groups: Apple's FQ2 10-Q
income statement has four columns — three months ended 3/28/26 and 3/29/25 *and* six
months ended the same dates — so any rule phrased over "all columns" false-fails there.
(a) within **each** duration group, exactly one column — that group's primary — has
`period_end` equal to the filing's manifest `period_end` (anchors the parse to trusted
data; note the QUARTER and YTD primaries share one end date by construction);
(b) duration kinds must be consistent with the statement type: BALANCE ⇒ all INSTANT;
INCOME ⇒ QUARTER/YTD/FISCAL_YEAR only; CASHFLOW ⇒ YTD/FISCAL_YEAR only (10-Q cash-flow
statements print YTD, not discrete quarters); (c) **within each duration group**,
comparative columns must be strictly earlier than that group's primary and end ~1 year
apart (window ±14 days — Apple's 52/53-week drift; exact tolerance §8-open); the
strictly-earlier rule is never applied across groups; (d) dates parse as real ISO dates.
Any FAIL ⇒ statement quarantined. Passing columns get fiscal labels assigned via the
calendar, per group.

**Check 1 — grounding (anti-hallucination, absolute)**

```python
def check_grounding(parsed: ParsedStatement,
                    page_tokens: dict[int, set[str]]) -> list[CheckResult]
```
Spec: for every cell, at least one of the candidate token forms
`{v, f"({v})", f"${v}", f"$({v})"}` (v = `value_verbatim` stripped of `$`/parens) must be
present **as a whole token** in the token set of the cell's claimed page, and that page
must lie within the statement's located range. Tokens are maximal non-whitespace runs of
`extract_text()` (layout=False — no padding artifacts) split on whitespace; whole-token
membership means `1,204` cannot be satisfied by `11,204`. Also applied to
`label_verbatim` as a *sequence* containment check on the page text (labels can wrap
lines, so label grounding is substring-after-whitespace-normalization, and its failure is
FAIL too — a fabricated label is as bad as a fabricated number). Any FAIL ⇒ quarantine.
Honest limit (stated in the check's docstring and the walkthrough): proves existence on
the page, not attachment to the right row/column.

**Check 2 — scale sanity**

```python
def check_scale(fact: CandidateFact, entry: ConceptEntry | None,
                default_bands: dict[str, tuple[Decimal, Decimal]]) -> CheckResult
```
Spec: dictionary-mapped facts must have `|value_normalized|` inside the concept's
`typical_magnitude` band (zero always passes); unmapped facts use per-unit default bands
(USD: [1e3, 1e13]; USD_PER_SHARE: [0.001, 1e4]; band values are §8-open, set after seeing
real data). Catches the silent ×1000 from a misread scale declaration and the per-share
row multiplied by millions. FAIL on any mapped fact ⇒ quarantine; FAIL on unmapped facts
⇒ the row is dropped with a check record (not quarantining, since unmapped rows carry no
answer path in P0).

**Check 3 — balance-sheet equation**

```python
def check_balance(facts: list[CandidateFact], dictionary: Dictionary) -> list[CheckResult]
```
Spec: for BALANCE statements only, per column, two sub-checks with different severities:
- **Hard (FAIL ⇒ quarantine):** `total_assets == total_liabilities_and_equity` exactly
  (Decimal equality on normalized values). This is the actual accounting identity and is
  layout-independent.
- **Informative (never FAIL on its own):** `total_liabilities + total_equity ==
  total_liabilities_and_equity`. PASS when it holds; otherwise **INCONCLUSIVE**, with
  `detail` reporting the residual and the printed labels of rows lying between the two
  totals. This sub-check is deliberately not fatal because real balance sheets print
  items outside both subtotals — Tesla carries **redeemable noncontrolling interests as
  a mezzanine line** (between total liabilities and the equity section, inside the grand
  total but in neither subtotal), and depending on mapping, non-redeemable NCI can sit
  outside `total_equity` too. A strict three-term identity would quarantine every
  correct Tesla parse. Exact additive verification of that span is per-company printed
  structure — i.e., a **P1 footing rule** (`BALANCE` block in `concepts.yaml`, authored
  at P1.1), where it gets FAIL severity with the mezzanine rows enumerated as components.
Missing mapped totals ⇒ INCONCLUSIVE (recorded; statement still acceptable — the
dictionary might legitimately miss a label variant, which then surfaces in review).

**Check 4 — footing (P1)**

```python
def check_footing(facts: list[CandidateFact],
                  rules: list[FootingRule]) -> list[CheckResult]     # P1 only
```
Spec: for each footing rule whose `total` label maps to a parsed row: sum of present
`components` (Decimal) must equal the total, per column. A missing component row ⇒
INCONCLUSIVE (logged, not fatal — layout variance shouldn't nuke a statement); a sum
mismatch with all components present ⇒ FAIL ⇒ quarantine (wrong row-association almost
always breaks a printed sum). P0 never calls this function; wiring it in is P1.1's whole
job — that is the P0/P1 seam.

**Statement accept/quarantine policy (`accept_statement`)**

```python
def accept_statement(parsed: ParsedStatement, filing: Filing, page_texts: dict[int, str],
                     dictionary: Dictionary) -> AcceptedStatement | Quarantine
```
Order: periods → normalize cells → grounding → concept mapping (§3.2) → scale → balance.
Any FAIL ⇒ the whole statement is rejected (never partially ingested). First rejection
triggers the single feedback retry (J5); second ⇒ `parse_status='QUARANTINED'` with
`quarantine_reason`, all check rows written, **and ingestion stops for Ben with the page
numbers printed** (rule 12: you are the review queue). INCONCLUSIVEs are written but
don't block.

Rule 11 coverage: `tests/ingest/test_accept.py` contains, per check, at least one crafted
bad input that must be REJECTED (a value absent from the page; `1,204` present only inside
`11,204`; a swapped scale; assets ≠ L+E; a duplicated period column; P1: a broken foot).

---

## 5. Query pipeline — function by function

All types in `query/types.py`. **Every refusal is a value, not an exception**; exceptions
are reserved for bugs (I/O, schema violations).

```python
class RefusalKind(Enum):
    OUT_OF_CORPUS          = auto()   # "Microsoft is not ingested"
    NOT_FILED_YET          = auto()   # FY2026 in July 2026 — carries nearest_alternative
    CONCEPT_NOT_SUPPORTED  = auto()   # not in dictionary (P0; P1 may downgrade to fuzzy/candidates)
    PERIOD_NOT_HELD        = auto()   # resolvable period, but no filing in corpus covers it
    AMBIGUOUS_CONCEPT      = auto()   # P1: ≥2 fuzzy survivors — carries the candidate list
    CROSS_DURATION         = auto()   # compute layer refuses FY-vs-Q arithmetic (type error)
    NARRATIVE_NOT_SUPPORTED= auto()   # P0 only; retired by P1.5
    UNPARSEABLE_QUESTION   = auto()   # planner returned intent=other / nothing extractable

@dataclass(frozen=True)
class Refusal:
    kind: RefusalKind
    reason: str                       # printed to the user, always with the "why"
    alternatives: tuple[str, ...] = ()  # e.g. ("Q1 FY2026 vs Q1 FY2025 is answerable — ask that?",)

@dataclass(frozen=True)
class Answered:      evidence: EvidenceObject; text: str
@dataclass(frozen=True)
class Refused:       evidence: EvidenceObject; refusal: Refusal            # reduced evidence (§3.4)
@dataclass(frozen=True)
class Candidates:    evidence: EvidenceObject; options: tuple[FuzzyMatch, ...]   # P1
@dataclass(frozen=True)
class Conflict:      evidence: EvidenceObject; facts: tuple[FactRecord, ...]     # both sources shown

AnswerResult = Answered | Refused | Candidates | Conflict
```

**5.1 `plan.py`**

```python
def plan(question: str, dictionary: Dictionary, manifest: Manifest) -> Plan
```
One LLM call, schema §3.5 forced. No gating logic. The Plan lands verbatim in the
evidence echo — the sole guard on the one LLM step with no deterministic test
(ARCHITECTURE weakness #4).

**5.2 `resolve.py`**

```python
def resolve(p: Plan, manifest: Manifest, dictionary: Dictionary,
            today: date) -> ResolvedQuery | Refusal
```
Deterministic gates, in order: intent=narrative ⇒ `NARRATIVE_NOT_SUPPORTED` (P0) /
narrative path (P1.5); intent=other ⇒ `UNPARSEABLE_QUESTION`; company OTHER/NONE ⇒
`OUT_OF_CORPUS`; concept OTHER/NONE ⇒ `CONCEPT_NOT_SUPPORTED` (P0 — P1.3 routes to fuzzy
via `concept_text`); period aliases → typed periods via the fiscal calendar (§3.3);
future/absent fiscal year ⇒ `NOT_FILED_YET` with computed `alternatives` (the nearest
held comparable pair); period valid but uncovered by corpus ⇒ `PERIOD_NOT_HELD`. Derived
metrics expand to their component concepts here (`DERIVED_OPERATING_MARGIN` ⇒
operating_income + revenue, operation=margin). `rank_deltas` resolves to a statement-wide
concept set for two periods. Output `ResolvedQuery` carries `(ticker, concepts,
typed_periods, operation)`.

**5.3 `retrieve.py`**

```python
def retrieve(rq: ResolvedQuery, store: FactReader) -> RetrievedFacts | Refusal | Conflict
def fuzzy_candidates(rq: ResolvedQuery, store: FactReader,          # P1.3 only
                     threshold: float) -> tuple[FuzzyMatch, ...]
```
Keyed lookup: `(ticker, concept, duration_type, period_end)` per concept/period. Multiple
provenance rows for the same key: if all `value_normalized` agree ⇒ pick the **preferred
provenance** (the filing whose own report period equals the requested period; else the
most recently filed) and note that corroborating rows exist; if they disagree ⇒ return
`Conflict` with all rows (both filings shown, no computation — §5.4 of ARCHITECTURE).
Miss ⇒ P0: `Refusal(PERIOD_NOT_HELD | CONCEPT_NOT_SUPPORTED)`; P1.3: call
`fuzzy_candidates` — `difflib.SequenceMatcher.ratio()` between the normalized query
phrase (`concept_text`) and every stored `raw_label` within the right ticker+statement.
Survivors ≥ threshold (value §8-open): **two or more ⇒ the candidate list IS the answer**
(`Candidates`); **exactly one ⇒ used**, evidence `match_method='label_similarity'` +
`FUZZY_SINGLE_MATCH` caveat ("matched by label similarity, not the curated dictionary —
verify the printed label"); if the survivor's label belongs to a disambiguation pair whose
other member also has stored rows for the period ⇒ never auto-pick, return `Candidates`.
Zero survivors ⇒ the original Refusal.

**5.4 `compute.py`**

```python
def compute(op: Operation, facts: Mapping[str, FactRecord]) -> Computation | Refusal
def allowed_renderings(value: Decimal, unit: str) -> frozenset[str]
```
Guards first (each is a typed Refusal, tested per rule 11): any two facts entering the
same formula must share `duration_type` (else `CROSS_DURATION` — annual/quarterly mixing
is a type error) and compatible units. Operations, all `Decimal`, each emitting numbered
steps into `calculation.steps` exactly as computed:
- `value`: identity (steps show normalization provenance).
- `delta`: `y - x`.
- `growth`: `(y - x) / abs(x)`, sign convention disclosed via `SIGN_CONVENTION` caveat
  when `x < 0`.
- `margin`: `a / b` (b = revenue), refusing on `b == 0`.
- `rank_deltas`: per concept present in *both* periods, compute delta and growth; sort by
  signed growth; emit the full sorted table into the trace (the LLM only ever narrates
  this table — it never ranks).
`allowed_renderings` generates the whitelist (§3.4): exact normalized string; thousands-
separated; $-millions/$-billions at 0–1 decimal; ratios as percent at 1–2 decimals and
raw at 2–4 decimals. This closed set is what the P1 audit checks membership against —
"declared rounding" is thereby mechanical, not judged.

**5.5 `evidence.py`**

```python
def build_evidence(question: str, p: Plan, rq: ResolvedQuery | None,
                   facts: Sequence[FactRecord], comp: Computation | None,
                   caveats: Sequence[Caveat]) -> EvidenceObject
```
Assembles §3.4. Auto-caveats: `UNAUDITED_INTERIM` whenever any fact's form_type is 10-Q;
`FISCAL_CALENDAR` always for AAPL and whenever an alias year was interpreted;
`UNVERIFIED_FACT` when status is UNVERIFIED (P1 makes this meaningful);
`NEAR_MISS_ALTERNATIVES` (P1) listing pair-partners that also held data.
`verification_status` = min over facts (VERIFIED > UNVERIFIED > CONFLICTING ordering:
CONFLICTING dominates).

**5.6 `compose.py` + `audit.py`**

```python
def render_template(ev: EvidenceObject) -> str                    # P0 — deterministic
def compose_llm(ev: EvidenceObject) -> str                        # P1.2 — fluent prose
def audit_numerals(text: str, ev: EvidenceObject) -> AuditResult  # P1.2 — code
```
P0 `render_template`: fixed-format answer built only from evidence fields — headline
sentence (values + result), then facts table (filing, page, printed label, period dates,
raw value), then the trace, then caveats. Checked by construction; no audit needed.

P1 `compose_llm` prompt skeleton:
```
SYSTEM: Write a short, plain answer for a skeptical financial analyst from the evidence
object below. Rules: every number you write must appear in allowed_renderings, the period
metadata, or the provenance fields — never introduce or re-round a number; state periods
with their exact dates; mention every caveat; do not editorialize beyond the evidence.
USER: {evidence object JSON}
```
P1 `audit_numerals` (ARCHITECTURE §5.3 token classes): extract numeral tokens with one
regex over the composed text (digits with optional `$ , . % ( ) -`, plus 4-digit years
and ISO dates); **classify before checking** — VALUE (matches an `allowed_renderings`
entry, else any exact `value_raw`/`value_normalized`) / PERIOD (matches the evidence's
period metadata **and appears in a date-shaped context**: inside an ISO date, adjacent
to a month name, or prefixed by FY/Q — bare membership in the date-component set is not
enough, so a stray `31` or `2026` used as a quantity classifies as VALUE and fails) /
PROVENANCE
(matches a page number or an accession-number fragment) / **UNCLASSIFIABLE ⇒ FAIL — the
default is rejection, not exemption**. On FAIL: regenerate once with the failure appended;
second FAIL ⇒ fall back to `render_template` (the answer degrades to less fluent, never
to unchecked). Rule 11 test: a composition with a fabricated total, a silently re-rounded
percent, a transposed digit, and a fabricated quantity that coincides with a date
component (a bare "2026" or "31" used as a value) must each be rejected.

**5.7 `pipeline.py`**

```python
def answer(question: str, deps: Deps) -> AnswerResult
```
plan → resolve → retrieve → compute → evidence → compose(→audit P1) → wrap. Any stage
returning a Refusal short-circuits into `Refused` with a reduced evidence object (the
echo is always present — a refusal to a misread question is visibly a refusal to the
wrong question). `Deps` bundles store/dictionary/manifest/llm for testability.

**5.8 `cli.py`** — subcommands and what they print

| Command | Does |
|---|---|
| `sfi manifest` | Stage 0; prints the filename↔accession join table for eyeball confirmation; hard-fails on ambiguity. |
| `sfi ingest [--filing ACCESSION] [--dry-run]` | Runs segment(→print page ranges only, if dry-run)→extract→accept→write; stops loudly at first quarantine with page refs. |
| `sfi ask "QUESTION" [--json]` | Full pipeline; renders answer/refusal + evidence; `--json` dumps the evidence object. |
| `sfi bench run` / `sfi bench spotcheck` | §6. |
| `sfi measure llm-arithmetic` / `label-cosine` | Rule-14 experiments; append results to `notes/measurements.md`. |
| `sfi tie-check` (P1) / `sfi prose-index` (P1) | Cross-filing ties; MD&A embedding build. |

---

## 6. Benchmark harness

### 6.1 Hand-authored file — `benchmark/benchmark.yaml` (template Ben fills in)

Expected values are typed by Ben from the PDFs only (rule 9). The scorer never generates
or repairs an expectation; suspected errors in expectations are *flagged* for re-check.

```yaml
# category ∈ direct_lookup | derived | quarterly_yoy | period_trap | label_trap
#            | scale_trap | should_refuse            (counts per ARCHITECTURE §6)
- id: B01
  category: direct_lookup
  question: "What was Apple's total revenue in fiscal 2025?"
  expect:
    behavior: answer            # answer | refuse | candidates | conflict
    value: "416161000000"       # exact normalized decimal string; null for non-answers
    unit: USD
    concept: revenue
    period: {fiscal_year: 2025, fiscal_period: FY}
    citation:                   # a right answer with a wrong citation FAILS
      company: AAPL
      form_type: 10-K
      page: 30                  # page in the PDF where Ben verified the number
      raw_label: "Total net sales"
    refusal_kind: null          # for behavior: refuse — the RefusalKind name, e.g. NOT_FILED_YET
  notes: ""                     # anything Ben wants to remember about the entry

- id: B18
  category: should_refuse
  question: "What was Microsoft's net income in the latest annual filing?"
  expect: {behavior: refuse, refusal_kind: OUT_OF_CORPUS, value: null}
```

### 6.2 Scoring script behavior (`bench/runner.py` + `bench/score.py`)

- Runs every entry through `query.pipeline.answer()` — the same public entry as the CLI;
  no bench-only side doors.
- **Correct**, defined before any run (ARCHITECTURE §6): behavior class matches AND — for
  answers — `value` (exact Decimal equality on normalized values; only membership in the
  computed `allowed_renderings` tolerated for the *formatted* field) ∧ `concept`/
  `raw_label` (line item) ∧ `period` (typed) ∧ `citation` (accession-resolved form +
  page). Refusal entries must match `refusal_kind` — refusing for the wrong reason fails.
  Spurious refusals fail. A right number off the wrong row fails.
- **Retrieval-vs-answer divergence** (ARCHITECTURE §4.5) logged per question: whether the
  right statement was located/parsed (from `statements` + `checks`) independently of
  whether the final answer was right — "right table, wrong cell" is made visible.
- Output: `benchmark/reports/run-{timestamp}.json` + a printed table: per-category
  pass/fail, each failure with its classification label.

### 6.3 Failure classification — labels map to the guard that leaked

| Label | Meaning | Guard implicated |
|---|---|---|
| `PLANNER_MISREAD` | structured query ≠ question | interpreted-question echo (weakness #4) |
| `PERIOD_RESOLUTION` | wrong typed period chosen | typed periods / fiscal calendar |
| `EXTRACTION_WRONG_VALUE` | stored value ≠ printed value | grounding (existence ≠ association) |
| `EXTRACTION_WRONG_ROW` | right value-shape, wrong line item | dictionary / footing (P1) |
| `EXTRACTION_WRONG_SCALE` | off by 1e3/1e6 or per-share slip | scale sanity |
| `EXTRACTION_COLUMN_SWAP` | periods transposed at parse | period check / tie check (P1) |
| `RETRIEVAL_MISS` | fact in PDF, absent from store | quarantine policy / segmentation |
| `WRONG_CITATION` | right answer, wrong provenance | evidence assembly |
| `SPURIOUS_REFUSAL` | refused an answerable question | refusal-path precision |
| `MISSED_REFUSAL` | answered a should-refuse | resolve gates |
| `COMPOSE_NUMERAL` (P1) | composed text disagreed with evidence | numeral audit |
| `NEEDS_REVIEW` | scorer can't attribute mechanically | — (Ben classifies) |

The scorer auto-suggests a label from the field-diff pattern (e.g. value≠ ∧ label= ∧
period= ⇒ `EXTRACTION_WRONG_VALUE`; value= ∧ period≠ ⇒ `PERIOD_RESOLUTION` or
`EXTRACTION_COLUMN_SWAP`, disambiguated by which provenance row was used); anything
ambiguous is `NEEDS_REVIEW`. A milestone is "done" only after a benchmark run whose
report has been reviewed (rule 10).

### 6.4 Ground-truth spot-check (`bench/xbrl_spotcheck.py`)

For ~10 benchmark entries, fetch
`data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{tag}.json` (hand-mapped
concept→us-gaap tag table inside the script; ≤20 calls lifetime, every call through
`common/edgar.py` and thus in the ledger) and compare against **Ben's expected values**,
not the system's answers — this checks the checker. Mismatch ⇒ printed flag for Ben to
re-read the PDF; the script never edits `benchmark.yaml` (rule 9). One-time; zero calls
on any query path. SEC requests send `User-Agent: sec-filing-intelligence
lederbenjamin@gmail.com`.

---

## 7. Build order — P0 → P1 checklist

Each step independently verifiable; DoD = definition of done. Stops marked ⛔ are rule-12
review gates. P1 steps are ordered per ARCHITECTURE §5.5 and touch no P0 behavior except
where the seam is named.

**P0**

1. **Scaffolding.** uv project, package skeleton, config/.env loader, `schema.sql`
   applied, `edgar.py` ledger writer, CLI stub.
   *DoD:* `uv run sfi --help` lists all subcommands; `pytest` runs (0 tests ok);
   `facts.sqlite` created with full schema; model strings and pricing in J1 verified
   against current Anthropic docs (correction recorded in §0 if they changed).
2. **Manifest (stage 0).** `company_tickers.json` + 2 submissions calls, cached raw;
   manifest.json written; filename↔accession join computed.
   *DoD:* manifest lists 7 records (6 PDFs + 10-K/A, `amends_accession` set);
   `edgar_log.jsonl` shows exactly 3 lines (1 bulk + 2 api); join table prints cleanly;
   unit test: ambiguous join input hard-fails. ⛔ Ben eyeballs the join table.
3. **Segmentation (stage 1).** Anchor rules for the three statements per filing;
   `sfi ingest --dry-run` prints located page ranges.
   *DoD:* 18/18 statements located with page ranges; any text-layer surprise (missing
   layer, garbled anchors) reported verbatim, not worked around (rule 13).
   ⛔ Ben spot-checks ranges against 2–3 PDFs.
4. **Concept dictionary v1.** Authored from the actual statements' printed labels;
   loader + validation + matching semantics.
   *DoD:* ≥18 concepts; disambiguation pair present; loader rejects unknown keys and
   asymmetric pairs; rule-11 test: label matching two concepts maps to none.
5. **Parser + acceptance + store (stage 2/3).** `extract.py`, `accept.py` (checks 0–3),
   normalization, `FactWriter`.
   *DoD:* all 18 statements ACCEPTED or QUARANTINED with reasons; every stored fact has a
   PASS grounding check row; per-check rejection tests pass (rule 11); quarantines stop
   the run and print pages. ⛔ Ben reviews any quarantine (rule 12).
6. **Query pipeline (template composition).** plan/resolve/retrieve/compute/evidence/
   template render; all P0 refusal kinds; `sfi ask`.
   *DoD:* the five in-scope example questions (net-income growth trap, Q1 YoY, AAPL FY25
   revenue, operating-margin change, biggest balance-sheet changes) each produce an
   answer or typed refusal with full evidence; cross-duration rule-11 test passes;
   NOT_FILED_YET offers the nearest alternative.
7. **Benchmark harness + Ben authors ~25 entries + spot-check.**
   *DoD:* `sfi bench run` produces the classified report; `sfi bench spotcheck` run once,
   ≤20 logged calls, mismatches (if any) flagged to Ben.
   ⛔ **P0 exit review: benchmark report + failure classes.**

**Measurements (rule 14, cheap, walkthrough-critical)**

M1. `sfi measure llm-arithmetic` — N≈50 growth/margin computations on SEC-scale operands
   (5–7 digit, ×10⁶) asked of the model directly; error rate vs Decimal ground truth →
   `notes/measurements.md`. Runnable any time after P0.1.
M2. `sfi measure label-cosine` — cosine of the net-income pair (and 2–3 other close label
   pairs) on the prose-path embedding model → `notes/measurements.md`. Requires P1.5's
   dependency group; run alongside P1.5.

**P1** (in §5.5 order; each lands with a benchmark re-run showing no regressions)

1. **Footing checks.** Author `footing:` blocks for both companies from the PDFs; wire
   `check_footing` into `accept_statement`; re-ingest.
   *DoD:* footing rules exist for both companies' income statements (+ cash flow if
   printed subtotals allow) and a BALANCE rule per company enumerating the
   liabilities-to-total span (incl. Tesla's mezzanine redeemable NCI), giving the
   check-3 informative sub-check its FAIL-severity P1 counterpart; rule-11 broken-sum
   rejection test; re-ingest quarantines nothing new (or stops for review).
2. **Numeral audit + LLM composer** (a pair; neither ships alone).
   *DoD:* audited compositions replace templates on the happy path; template fallback on
   double audit failure observed in a forced test; rule-11 tests (fabricated /
   re-rounded / transposed numerals rejected).
3. **Fuzzy fallback + candidate lists + caveats.**
   *DoD:* dictionary-miss question returns candidates; single-survivor answers carry
   `FUZZY_SINGLE_MATCH`; disambiguation-pair members never auto-picked (rule-11 test);
   threshold chosen from real label-distance data and recorded in measurements.
4. **Cross-filing tie check (minimal).** `sfi tie-check` matches facts across filings on
   `(ticker, concept|raw_label, duration_type, period_end)`; AGREE ⇒ both rows VERIFIED;
   CONFLICT ⇒ both CONFLICTING + flagged.
   *DoD:* the ~dozen overlapping facts get ties; statuses propagate into evidence;
   deliberate value-mutation test yields CONFLICT.
5. **Narrative path** (J2). Segment MD&A/Item 1A; chunk (~page-scoped, size
   §8-open); embed; `intent=narrative` retrieves top-k chunks and answers with verbatim
   quotes + page cites, labeled "narrative path: weaker guarantees; no numeric claims" —
   numerals in narrative answers are quoted, never computed on.
   *DoD:* "What did management cite as risks this quarter?" returns cited verbatim
   quotes; numeric-question-shaped inputs still route to the fact path; M2 recorded.

**P2 — never built** (rule 6). Present only as schema (§3.1) and enum values.

---

## 8. Deliberately left open (chosen consciously during implementation, with data)

| Open item | Where it bites | Deferred because |
|---|---|---|
| Fuzzy-match threshold + normalization details | `retrieve.fuzzy_candidates` (P1.3) | Needs the real distribution of label distances; will be measured, not guessed. |
| Layout-hint format v2 (word x-positions) | `extract.py` input | Only if layout-text parses fail; format follows the observed failure mode. |
| `typical_magnitude` bands per concept + unit defaults | `check_scale` | Set after seeing real values; too tight ⇒ spurious quarantines, too loose ⇒ useless. |
| Comparative-column date tolerance (provisional ±14 days) | `check_periods` (c) | Apple's 52/53-week drift measured from actual headers. |
| Anchor phrase variants per company | `segment.py` | Exact casing/wording read off the real PDFs at P0.3. |
| Parser page-window size (whole statement vs per-page calls) | `extract.py` | Depends on how statements span pages in these 6 PDFs. |
| Footing rule contents | `concepts.yaml` | Authored from printed subtotal structure at P1.1. |
| Prose chunk size/overlap; top-k | `prose.py` / `narrative.py` | Tune on the real MD&A sections. |
| Template renderer exact wording | `render_template` | Cosmetic; fixed once evidence fields are real. |
| Benchmark question list (~25) | `benchmark.yaml` | Ben authors while reading the PDFs (rule 9). |
| Concept→us-gaap tag map for spot-check | `xbrl_spotcheck.py` | Only the ~10 sampled concepts need tags. |
| Composer model downgrade after the audit exists | `llm/client.py` | Cost/quality call once the audit makes composer errors harmless. Composer only — per J1, the planner is never a downgrade candidate. |
