import sqlite3

import pytest

from sfi.store import db

EXPECTED_TABLES = {"filings", "statements", "facts", "checks", "fact_ties", "prose_chunks"}


@pytest.fixture()
def con(tmp_path):
    path = tmp_path / "facts.sqlite"
    db.init_db(path)
    con = db.connect(path)
    yield con
    con.close()


def _insert_filing(con):
    con.execute(
        "INSERT INTO filings (accession_no, ticker, cik, form_type, filing_date,"
        " period_end, fiscal_year, fiscal_period) VALUES"
        " ('acc-1', 'TSLA', '0001318605', '10-K', '2026-01-30', '2025-12-31', 2025, 'FY')"
    )


def _insert_statement(con):
    con.execute(
        "INSERT INTO statements (id, accession_no, statement_type, page_start,"
        " page_end, anchor_text, parse_status) VALUES"
        " (1, 'acc-1', 'INCOME', 9, 10, 'Consolidated Statements of Operations', 'PENDING')"
    )


def test_schema_applies_all_tables(con):
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert EXPECTED_TABLES <= tables


def test_init_db_is_idempotent(tmp_path):
    path = tmp_path / "facts.sqlite"
    db.init_db(path)
    db.init_db(path)  # must not raise on the plain CREATE TABLE schema


def test_rejects_bad_statement_type(con):
    _insert_filing(con)
    with pytest.raises(sqlite3.IntegrityError):
        con.execute(
            "INSERT INTO statements (accession_no, statement_type, page_start,"
            " page_end, anchor_text, parse_status) VALUES"
            " ('acc-1', 'EQUITY', 1, 2, 'x', 'PENDING')"
        )


def test_rejects_bad_parse_status(con):
    _insert_filing(con)
    with pytest.raises(sqlite3.IntegrityError):
        con.execute(
            "INSERT INTO statements (accession_no, statement_type, page_start,"
            " page_end, anchor_text, parse_status) VALUES"
            " ('acc-1', 'INCOME', 1, 2, 'x', 'MAYBE')"
        )


def test_rejects_bad_unit_on_fact(con):
    _insert_filing(con)
    _insert_statement(con)
    with pytest.raises(sqlite3.IntegrityError):
        con.execute(
            "INSERT INTO facts (statement_id, accession_no, ticker, statement_type,"
            " raw_label, row_index, page, period_end, duration_type, fiscal_year,"
            " fiscal_period, value_raw, value_normalized, unit, scale) VALUES"
            " (1, 'acc-1', 'TSLA', 'INCOME', 'Total revenues', 0, 9, '2025-12-31',"
            " 'FISCAL_YEAR', 2025, 'FY', '97,690', '97690000000', 'EUR', 1000000)"
        )


def test_rejects_bad_duration_type(con):
    _insert_filing(con)
    _insert_statement(con)
    with pytest.raises(sqlite3.IntegrityError):
        con.execute(
            "INSERT INTO facts (statement_id, accession_no, ticker, statement_type,"
            " raw_label, row_index, page, period_end, duration_type, fiscal_year,"
            " fiscal_period, value_raw, value_normalized, unit, scale) VALUES"
            " (1, 'acc-1', 'TSLA', 'INCOME', 'Total revenues', 0, 9, '2025-12-31',"
            " 'MONTHLY', 2025, 'FY', '97,690', '97690000000', 'USD', 1000000)"
        )


def test_rejects_statement_without_filing(con):
    with pytest.raises(sqlite3.IntegrityError):
        _insert_statement(con)  # FK: no filings row yet
