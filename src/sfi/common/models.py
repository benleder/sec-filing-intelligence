"""Frozen dataclasses shared across the pipeline. L0 — stdlib only."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Company:
    ticker: str
    cik: str  # zero-padded to 10 digits, from company_tickers.json (J7)
    name: str
    fiscal_year_end_mmdd: str  # e.g. "--12-31"


@dataclass(frozen=True)
class Filing:
    ticker: str
    accession_no: str
    form_type: str  # '10-K' | '10-Q' | '10-K/A'
    filing_date: str  # ISO date, EDGAR filingDate
    period_end: str  # ISO date, EDGAR reportDate
    fiscal_year: int
    fiscal_period: str  # 'FY' | 'Q1' | 'Q2' | 'Q3'
    is_amendment: bool
    amends_accession: str | None
    pdf_path: str | None  # relative under data/raw/; None for amendments


@dataclass(frozen=True)
class CheckResult:
    check_name: str  # 'period' | 'grounding' | 'scale' | 'balance' | 'footing'
    status: Literal["PASS", "FAIL", "INCONCLUSIVE"]
    fact_ref: tuple[int, int] | None  # (row_index, column_index) or None
    detail: str
