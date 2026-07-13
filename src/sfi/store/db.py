"""SQLite access. L1 — imports common only.

schema.sql stays verbatim §3.1 (no IF NOT EXISTS edits); init_db keeps
application idempotent by checking sqlite_master first. FactWriter is the
ingest-side API; FactReader lands at P0.6.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from ..common import config

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = config.DB_PATH if path is None else path
    con = sqlite3.connect(path)
    con.execute("PRAGMA foreign_keys = ON")
    return con


def init_db(path: Path | None = None) -> None:
    path = config.DB_PATH if path is None else path
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = connect(path)
    try:
        tables = {
            row[0]
            for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if "facts" not in tables:
            con.executescript(SCHEMA_PATH.read_text())
            con.commit()
    finally:
        con.close()


class FactWriter:
    """Ingest-side writes. Re-ingest is idempotent per filing: the store's
    state is a function of the current parser output, never an accumulation
    of runs (§3.1 re-ingest semantics)."""

    def __init__(self, con: sqlite3.Connection):
        self.con = con

    def ensure_filings(self, manifest: dict) -> None:
        for f in manifest["filings"]:
            cik = manifest["companies"][f["ticker"]]["cik"]
            self.con.execute(
                "INSERT OR IGNORE INTO filings (accession_no, ticker, cik, form_type,"
                " filing_date, period_end, fiscal_year, fiscal_period,"
                " amends_accession, pdf_path) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    f["accession_no"], f["ticker"], cik, f["form_type"],
                    f["filing_date"], f["period_end"], f["fiscal_year"],
                    f["fiscal_period"], f["amends_accession"], f["pdf_path"],
                ),
            )

    def replace_filing(self, accession_no: str) -> None:
        """Single transaction: drop this filing's checks, ties, facts and
        statements, reset ingested_at. (Tie demotion of surviving facts is
        wired at P1.4 — no ties exist before then.)"""
        con = self.con
        con.execute("BEGIN")
        con.execute(
            "DELETE FROM checks WHERE statement_id IN"
            " (SELECT id FROM statements WHERE accession_no = ?)",
            (accession_no,),
        )
        con.execute(
            "DELETE FROM fact_ties WHERE fact_id_a IN"
            " (SELECT id FROM facts WHERE accession_no = ?)"
            " OR fact_id_b IN (SELECT id FROM facts WHERE accession_no = ?)",
            (accession_no, accession_no),
        )
        con.execute("DELETE FROM facts WHERE accession_no = ?", (accession_no,))
        con.execute("DELETE FROM statements WHERE accession_no = ?", (accession_no,))
        con.execute(
            "UPDATE filings SET ingested_at = NULL WHERE accession_no = ?",
            (accession_no,),
        )
        con.commit()

    def _insert_statement(self, filing, located, parse_status, quarantine_reason,
                          parser_model, prompt_version) -> int:
        cur = self.con.execute(
            "INSERT INTO statements (accession_no, statement_type, page_start,"
            " page_end, anchor_text, parse_status, quarantine_reason,"
            " parser_model, prompt_version, parsed_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                filing.accession_no, located.statement_type, located.page_start,
                located.page_end, located.anchor_text, parse_status,
                quarantine_reason, parser_model, prompt_version, _now(),
            ),
        )
        return cur.lastrowid

    def _insert_checks(self, statement_id: int, checks, fact_ids: dict) -> None:
        for c in checks:
            fact_id = fact_ids.get(c.fact_ref) if c.fact_ref else None
            self.con.execute(
                "INSERT INTO checks (statement_id, fact_id, check_name, status,"
                " detail) VALUES (?,?,?,?,?)",
                (statement_id, fact_id, c.check_name, c.status, c.detail),
            )

    def write_accepted(self, filing, located, accepted, parser_model, prompt_version) -> int:
        statement_id = self._insert_statement(
            filing, located, "ACCEPTED", None, parser_model, prompt_version
        )
        fact_ids: dict[tuple[int, int], int] = {}
        for f in accepted.facts:
            cur = self.con.execute(
                "INSERT INTO facts (statement_id, accession_no, ticker,"
                " statement_type, concept, match_method, raw_label, row_index,"
                " indent_level, is_subtotal, page, period_start, period_end,"
                " duration_type, fiscal_year, fiscal_period, value_raw,"
                " value_normalized, unit, scale) VALUES"
                " (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    statement_id, filing.accession_no, filing.ticker,
                    located.statement_type, f.concept, f.match_method,
                    f.raw_label, f.row_index, f.indent_level,
                    int(f.is_subtotal), f.page, f.period_start, f.period_end,
                    f.duration_type, f.fiscal_year, f.fiscal_period,
                    f.value_raw, f.value_normalized, f.unit, f.scale,
                ),
            )
            fact_ids[(f.row_index, f.column_index)] = cur.lastrowid
        self._insert_checks(statement_id, accepted.checks, fact_ids)
        return statement_id

    def write_quarantined(self, filing, located, quarantine, parser_model, prompt_version) -> int:
        statement_id = self._insert_statement(
            filing, located, "QUARANTINED", quarantine.reason, parser_model, prompt_version
        )
        self._insert_checks(statement_id, quarantine.checks, {})
        return statement_id

    def mark_ingested(self, accession_no: str) -> None:
        self.con.execute(
            "UPDATE filings SET ingested_at = ? WHERE accession_no = ?",
            (_now(), accession_no),
        )


class FactReader:
    """Query-side reads (§5.3 keyed lookup). The SQLite file is the only
    coupling between ingest and query (§1)."""

    def __init__(self, con: sqlite3.Connection):
        con.row_factory = sqlite3.Row
        self.con = con

    _BASE = (
        "SELECT f.*, fil.form_type, fil.filing_date,"
        " fil.period_end AS filing_period_end"
        " FROM facts f JOIN filings fil ON fil.accession_no = f.accession_no"
    )

    def lookup(
        self,
        ticker: str,
        concept: str,
        fiscal_year: int,
        fiscal_period: str,
        duration_types: tuple[str, ...],
    ) -> list[sqlite3.Row]:
        marks = ",".join("?" * len(duration_types))
        return self.con.execute(
            f"{self._BASE} WHERE f.ticker = ? AND f.concept = ?"
            f" AND f.fiscal_year = ? AND f.fiscal_period = ?"
            f" AND f.duration_type IN ({marks})"
            " ORDER BY fil.filing_date DESC, f.id",
            (ticker, concept, fiscal_year, fiscal_period, *duration_types),
        ).fetchall()

    def held_periods(
        self, ticker: str, concept: str, duration_types: tuple[str, ...] | None = None
    ) -> list[sqlite3.Row]:
        """Distinct (fiscal_year, fiscal_period, duration_type) actually held,
        newest first — drives 'latest' aliases and NOT_FILED_YET alternatives."""
        where = "WHERE ticker = ? AND concept = ?"
        args: list = [ticker, concept]
        if duration_types:
            where += f" AND duration_type IN ({','.join('?' * len(duration_types))})"
            args += list(duration_types)
        return self.con.execute(
            "SELECT DISTINCT fiscal_year, fiscal_period, duration_type, period_end"
            f" FROM facts {where} ORDER BY period_end DESC",
            args,
        ).fetchall()
