from datetime import date

import pytest

from sfi.common.periods import FiscalCalendar, PeriodResolutionError

TSLA = FiscalCalendar.from_mmdd("1231")
AAPL = FiscalCalendar.from_mmdd("0927")


def test_calendar_year_fy_resolution():
    assert TSLA.fiscal_year_of(date(2025, 12, 31)) == 2025
    assert TSLA.fiscal_year_of(date(2026, 3, 31)) == 2026


def test_tsla_q1():
    assert TSLA.fiscal_period_of(date(2026, 3, 31), "10-Q") == "Q1"
    assert TSLA.fiscal_period_of(date(2025, 3, 31), "10-Q") == "Q1"


def test_aapl_fq2_with_52_53_week_dates():
    assert AAPL.fiscal_year_of(date(2025, 9, 27)) == 2025
    assert AAPL.fiscal_period_of(date(2026, 3, 28), "10-Q") == "Q2"
    assert AAPL.fiscal_period_of(date(2025, 3, 29), "10-Q") == "Q2"


def test_drift_tolerance_keeps_fy_label_stable():
    # A 52/53-week year can end a few days AFTER the submissions mmdd;
    # the ±14-day window must not push it into the next fiscal year.
    cal = FiscalCalendar.from_mmdd("0924")
    assert cal.fiscal_year_of(date(2025, 9, 27)) == 2025


def test_10k_is_fy_even_for_amendment_form():
    assert TSLA.fiscal_period_of(date(2025, 12, 31), "10-K") == "FY"
    assert TSLA.fiscal_period_of(date(2025, 12, 31), "10-K/A") == "FY"


def test_rejects_q4_shaped_10q():
    # rule 11: a 10-Q whose period end lands on the fiscal year end would be
    # "Q4" — that filing doesn't exist, so resolution must refuse, not guess.
    with pytest.raises(PeriodResolutionError):
        TSLA.fiscal_period_of(date(2025, 12, 31), "10-Q")


def test_rejects_unknown_form():
    with pytest.raises(PeriodResolutionError):
        TSLA.fiscal_period_of(date(2025, 12, 31), "8-K")


def test_rejects_garbage_fye():
    with pytest.raises(PeriodResolutionError):
        FiscalCalendar.from_mmdd("13-99")
    with pytest.raises(PeriodResolutionError):
        FiscalCalendar.from_mmdd("Dec 31")
