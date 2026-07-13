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
