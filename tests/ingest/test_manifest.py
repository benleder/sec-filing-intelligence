import pytest

from sfi.common.periods import FiscalCalendar
from sfi.ingest import manifest as m

TSLA_CAL = {"TSLA": FiscalCalendar.from_mmdd("1231")}


def _row(form, acc, filed, report):
    return m.FilingRow(form, acc, filed, report)


def test_parse_pdf_filename_variants():
    p = m.parse_pdf_filename("TSLA_10-K_FY2025.pdf")
    assert (p.ticker, p.form, p.fiscal_year, p.fiscal_period) == ("TSLA", "10-K", 2025, "FY")
    p = m.parse_pdf_filename("TSLA_10-Q_Q1-2026.pdf")
    assert (p.fiscal_year, p.fiscal_period) == (2026, "Q1")
    p = m.parse_pdf_filename("AAPL_10-Q_FQ2-2026.pdf")
    assert (p.ticker, p.fiscal_year, p.fiscal_period) == ("AAPL", 2026, "Q2")


def test_parse_pdf_filename_rejects_garbage():
    for bad in ("TSLA_8-K_FY2025.pdf", "TSLA_10-Q_Q4-2026.pdf", "notes.pdf"):
        with pytest.raises(m.ManifestError):
            m.parse_pdf_filename(bad)


def test_join_happy_path_with_amendment():
    pdfs = [m.parse_pdf_filename("TSLA_10-K_FY2025.pdf")]
    rows = {
        "TSLA": [
            _row("10-K", "acc-10k", "2026-01-30", "2025-12-31"),
            _row("10-K/A", "acc-10ka", "2026-04-25", "2025-12-31"),
            _row("10-Q", "acc-10q", "2026-04-20", "2026-03-31"),
        ]
    }
    filings = m.match_filings(pdfs, rows, TSLA_CAL)
    assert len(filings) == 2
    base, amendment = filings
    assert base["accession_no"] == "acc-10k" and not base["is_amendment"]
    assert amendment["form_type"] == "10-K/A"
    assert amendment["amends_accession"] == "acc-10k"
    assert amendment["pdf_path"] is None


def test_join_hard_fails_on_zero_candidates():
    pdfs = [m.parse_pdf_filename("TSLA_10-K_FY2025.pdf")]
    rows = {"TSLA": [_row("10-Q", "acc-10q", "2026-04-20", "2026-03-31")]}
    with pytest.raises(m.ManifestError):
        m.match_filings(pdfs, rows, TSLA_CAL)


def test_join_hard_fails_on_ambiguity():
    # rule 11/13: two manifest rows resolving to the same fiscal label must
    # never be silently disambiguated.
    pdfs = [m.parse_pdf_filename("TSLA_10-K_FY2025.pdf")]
    rows = {
        "TSLA": [
            _row("10-K", "acc-a", "2026-01-30", "2025-12-31"),
            _row("10-K", "acc-b", "2026-02-15", "2025-12-31"),
        ]
    }
    with pytest.raises(m.ManifestError):
        m.match_filings(pdfs, rows, TSLA_CAL)


def test_amendment_form_does_not_match_base_pdf():
    # A filename saying 10-K must join the 10-K, never the 10-K/A.
    pdfs = [m.parse_pdf_filename("TSLA_10-K_FY2025.pdf")]
    rows = {
        "TSLA": [
            _row("10-K/A", "acc-10ka", "2026-04-25", "2025-12-31"),
            _row("10-K", "acc-10k", "2026-01-30", "2025-12-31"),
        ]
    }
    filings = m.match_filings(pdfs, rows, TSLA_CAL)
    assert filings[0]["accession_no"] == "acc-10k"


def test_resolve_ciks_rejects_missing_ticker():
    tickers_json = {"0": {"cik_str": 1318605, "ticker": "TSLA", "title": "Tesla, Inc."}}
    with pytest.raises(m.ManifestError):
        m.resolve_ciks(["TSLA", "AAPL"], tickers_json)


def test_resolve_ciks_zero_pads():
    tickers_json = {"0": {"cik_str": 1318605, "ticker": "TSLA", "title": "Tesla, Inc."}}
    assert m.resolve_ciks(["TSLA"], tickers_json) == {"TSLA": "0001318605"}
