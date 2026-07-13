"""Fiscal-calendar resolution (§3.3). L0 — stdlib only.

Exact period-end dates always come from the manifest/EDGAR, never from a
formula (Apple's 52/53-week calendar makes formulas wrong). This module only
assigns fiscal LABELS (FY2025, Q1 FY2026) to exact dates.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

# 52/53-week drift tolerance for fiscal-year boundaries — the same ±14-day
# window check-0(c) uses for comparative columns (§8-open).
_DRIFT = timedelta(days=14)
_QUARTER_DAYS = 91.3125  # 365.25 / 4


class PeriodResolutionError(Exception):
    pass


@dataclass(frozen=True)
class FiscalCalendar:
    fye_month: int
    fye_day: int

    @classmethod
    def from_mmdd(cls, mmdd: str) -> "FiscalCalendar":
        """Accepts EDGAR's '1231' and the XBRL-style '--12-31'."""
        m = re.fullmatch(r"(?:--)?(\d{2})-?(\d{2})", mmdd)
        if not m:
            raise PeriodResolutionError(f"unparseable fiscal-year-end: {mmdd!r}")
        month, day = int(m.group(1)), int(m.group(2))
        if not (1 <= month <= 12 and 1 <= day <= 31):
            raise PeriodResolutionError(f"impossible fiscal-year-end: {mmdd!r}")
        return cls(month, day)

    def fy_end_approx(self, fiscal_year: int) -> date:
        try:
            return date(fiscal_year, self.fye_month, self.fye_day)
        except ValueError:  # e.g. 02-29 in a non-leap year
            return date(fiscal_year, self.fye_month, 28)

    def fiscal_year_of(self, period_end: date) -> int:
        fy = period_end.year
        if period_end > self.fy_end_approx(fy) + _DRIFT:
            fy += 1
        return fy

    def fiscal_period_of(self, period_end: date, form_type: str) -> str:
        base = form_type.split("/")[0]
        if base == "10-K":
            return "FY"
        if base != "10-Q":
            raise PeriodResolutionError(f"unsupported form type: {form_type!r}")
        fy = self.fiscal_year_of(period_end)
        days_in = (period_end - self.fy_end_approx(fy - 1)).days
        quarter = round(days_in / _QUARTER_DAYS)
        if quarter not in (1, 2, 3):
            # 10-Qs only cover Q1–Q3 (Q4 lives in the 10-K); anything else
            # means a mislabeled date and must never be silently coerced.
            raise PeriodResolutionError(
                f"10-Q period end {period_end} resolves to Q{quarter} "
                f"({days_in} days into FY{fy}) — refusing to guess"
            )
        return f"Q{quarter}"
