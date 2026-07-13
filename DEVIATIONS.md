# DEVIATIONS.md — ratified deviations from the frozen design

DESIGN.md is a frozen implementation contract (CLAUDE.md rule 1). When the
real PDFs prove a spec decision wrong, the implementation never silently
deviates: the change is flagged at a review stop, pinned by a rejection-style
test, and recorded here once Ben ratifies it. Each entry: what the spec said,
what reality said, what changed, and the pinning test(s).

---

## D1 — `context_labels`: section-scoped dictionary matching (§3.2 extension)

**Ratified 2026-07-13.**

- **Spec said:** a raw label maps to a concept iff it exactly equals one of
  the concept's `labels[company]` entries (anchored regex fallback).
- **Reality said:** both companies print their EPS rows as bare
  `Basic`/`Diluted` — byte-identical to the share-count rows a few lines
  below (`Shares used in computing earnings per share` / `Weighted average
  shares…`). Pure label matching either leaves EPS unanswerable or maps share
  counts to `eps_basic`, where the scale check would quarantine every correct
  income-statement parse.
- **What changed:** concepts may declare `context_labels` — a match requires
  the row label AND the nearest preceding cell-less (section-heading) row to
  both match. The ambiguity rule (§3.2 #3, two concepts ⇒ none) is unchanged.
- **Pinned by:** `tests/concepts/test_dictionary.py::test_eps_requires_matching_section`,
  `tests/ingest/test_accept.py::test_share_count_basic_is_not_eps`,
  `::test_income_accepted_with_eps_and_dash`.

## D2 — check 0(c): INSTANT comparative columns (10-Q balance sheets)

**Ratified 2026-07-13.** Provenance note (per Ben): the over-general
"~1 year apart" rule was introduced during the external design review, not in
the original draft.

- **Spec said:** within each duration group, comparatives end ~1 year apart
  from the primary (±14 days).
- **Reality said:** 10-Q balance sheets print the *prior fiscal-year end* as
  the comparative — Tesla Q1: 2025-12-31 vs 2026-03-31 (~3 months); Apple
  FQ2: 2025-09-27 vs 2026-03-28 (~6 months). The as-written rule would have
  quarantined every correct 10-Q balance-sheet parse (4 of 6 filings).
- **What changed:** INSTANT comparatives accept EITHER ~1 year before the
  primary OR the fiscal year end immediately preceding the primary (±14 d).
  Duration groups keep the 1-year rule, applied to consecutive column gaps
  (Tesla's 10-K prints three annual columns).
- **Pinned by:** `tests/ingest/test_accept.py::test_deviation_a_prior_fye_comparative_accepted_but_arbitrary_gap_rejected`,
  `::test_annual_columns_two_years_apart_rejected`.

## D3 — check 0(b): Q1 cash-flow statements print a "quarter" that IS the YTD

**Ratified 2026-07-13, with a query-time rider (see below).**

- **Spec said:** CASHFLOW ⇒ YTD/FISCAL_YEAR only ("10-Q cash-flow statements
  print YTD, not discrete quarters").
- **Reality said:** Tesla's Q1 cash flow prints "Three Months Ended March
  31" — a faithful transcriber reads QUARTER, and for a Q1 filing the
  three-month span *is* the fiscal year-to-date.
- **What changed:** every non-INSTANT CASHFLOW column must start at its own
  fiscal year's start (±14 d). This admits Q1 "quarters" and still rejects
  discrete later quarters, preserving the cumulative-statement intent.
- **Query-time rider (P0.6):** retrieval treats a fiscal-year-start QUARTER
  cash-flow fact as satisfying a YTD query for the same span, and vice
  versa, so Tesla-Q1/Apple-H1 duration asymmetry can't cause a false refusal.
- **Pinned by:** `tests/ingest/test_accept.py::test_deviation_b_q1_cashflow_quarter_ok_discrete_quarter_rejected`;
  query rider pinned in the P0.6 test suite (`tests/query/`).

## D4 — disposition of unmapped rows that fail the scale check

**Ratified 2026-07-13.** A spec gap rather than a contradiction: §4.3
check 2 says unmapped scale failures drop the row with a check record, while
J6's plain reading ("every accepted cell becomes a fact") suggests storing
everything. Drop-with-record is the ratified disposition.

- **Root cause:** Apple's income statements declare "(In millions, except
  number of shares, which are reflected in **thousands**, and per-share
  amounts)" — a *per-row* scale regime inside a millions-declared statement.
  The parser schema (§4.2) carries one statement-level multiplier plus the
  per-share exception; a thousands regime for share rows is unsupported, so
  those rows normalize to ~1.5e13 "USD" and correctly fail the default band.
- **Affected rows (all 22, every Apple income statement; section "Shares
  used in computing earnings per share:"):**

  | Filing | Row | Printed values (thousands of shares) |
  |---|---|---|
  | AAPL 10-K FY2025 (p40) | Basic | 14,948,500 · 15,343,783 · 15,744,231 |
  | AAPL 10-K FY2025 (p40) | Diluted | 15,004,697 · 15,408,095 · 15,812,547 |
  | AAPL 10-Q FQ2-2025 (p4) | Basic | 14,994,082 · 15,405,856 · 15,037,903 · 15,457,810 |
  | AAPL 10-Q FQ2-2025 (p4) | Diluted | 15,056,133 · 15,464,709 · 15,103,499 · 15,520,675 |
  | AAPL 10-Q FQ2-2026 (p4) | Basic | 14,673,278 · 14,994,082 · 14,710,718 · 15,037,903 |
  | AAPL 10-Q FQ2-2026 (p4) | Diluted | 14,725,873 · 15,056,133 · 14,768,115 · 15,103,499 |

  (Tesla's share-count rows are printed in millions like the rest of its
  statement, so they store as unmapped rows normally.)
- **What changed:** nothing in code — this documents the ratified behavior.
  If share counts ever become an answer path, the fix is a per-row scale
  regime in the parser schema, not a wider default band.
- **Pinned by:** `tests/ingest/test_accept.py::test_unmapped_scale_failure_drops_row_without_quarantine`.

## D5 — ground-truth correction (not a code deviation)

**2026-07-13.** `tests/fixtures/segmentation_truth.csv` rows for
AAPL_10-Q_FQ2-2025 equity/cash-flows were recorded as p8/p9 — a human
copy-paste error from the FQ2-2026 block (the PDF prints equity on p7,
cash flows on p8, notes on p9). Caught by the fixture regression test
(strict-xfail with evidence), confirmed and corrected by Ben. All 30 rows
now assert normally in
`tests/ingest/test_segment_truth.py::test_recorded_start_page_holds`.

## D6 — §3.5 planner schema: `maxItems: 2` moved from wire schema to code

**2026-07-13.** The structured-outputs API rejects array constraints
(`maxItems` → 400 `invalid_request_error`), so the periods cap cannot live in
the wire schema as §3.5 writes it.

- **What changed:** the schema ships without `maxItems`; `resolve.py`
  enforces the ≤2-periods rule deterministically (`p.periods[:2]`). The
  constraint is preserved — and in code, which is where the thesis wants
  guards anyway.
- **Pinned by:** the live planner calls (a schema carrying `maxItems` cannot
  complete a single request), plus the resolve-path tests in
  `tests/query/test_query.py`.
