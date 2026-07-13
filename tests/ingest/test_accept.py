"""Rule-11 coverage for the acceptance harness: per check, at least one
crafted bad input that must be REJECTED — plus pins for the two flagged
§4.3 deviations and the stop-2 riders."""

from decimal import Decimal

import pytest

from sfi.common.models import Filing
from sfi.common.periods import FiscalCalendar
from sfi.concepts import dictionary as dictionary_mod
from sfi.ingest import accept as a
from sfi.ingest.segment import LocatedStatement

DICT = dictionary_mod.load()
TSLA_CAL = FiscalCalendar.from_mmdd("1231")
AAPL_CAL = FiscalCalendar.from_mmdd("0926")

TSLA_10K = Filing(
    ticker="TSLA", accession_no="acc-10k", form_type="10-K",
    filing_date="2026-01-29", period_end="2025-12-31", fiscal_year=2025,
    fiscal_period="FY", is_amendment=False, amends_accession=None, pdf_path="x",
)
TSLA_10Q = Filing(
    ticker="TSLA", accession_no="acc-10q", form_type="10-Q",
    filing_date="2026-04-23", period_end="2026-03-31", fiscal_year=2026,
    fiscal_period="Q1", is_amendment=False, amends_accession=None, pdf_path="x",
)
AAPL_10Q = Filing(
    ticker="AAPL", accession_no="acc-a10q", form_type="10-Q",
    filing_date="2026-05-01", period_end="2026-03-28", fiscal_year=2026,
    fiscal_period="Q2", is_amendment=False, amends_accession=None, pdf_path="x",
)


def col(index, end, duration, start=None, header="hdr"):
    return a.ParsedColumn(index, header, start, end, duration)


def row(idx, label, values, page=80, subtotal=False):
    cells = tuple(
        a.ParsedCell(ci, v, page) for ci, v in enumerate(values) if v is not None
    )
    return a.ParsedRow(idx, label, 0, subtotal, cells)


# ---------------------------------------------------------------- fixtures

BAL_LOCATED = LocatedStatement("BALANCE", 80, 81, "Consolidated Balance Sheets")


def balance_statement(rows=None, columns=None):
    return a.ParsedStatement(
        statement_type="BALANCE",
        scale_text="(in millions, except per share data)",
        scale_multiplier=1_000_000,
        per_share_exception=True,
        columns=tuple(
            columns
            or (col(0, "2025-12-31", "INSTANT"), col(1, "2024-12-31", "INSTANT"))
        ),
        rows=tuple(
            rows
            or (
                row(0, "Assets", []),
                row(1, "Total assets", ["137,806", "122,070"], subtotal=True),
                row(2, "Liabilities", []),
                row(3, "Total liabilities", ["54,941", "48,390"], subtotal=True),
                row(4, "Redeemable noncontrolling interests in subsidiaries", ["58", "63"]),
                row(5, "Total stockholders’ equity", ["82,137", "72,913"], subtotal=True),
                row(6, "Noncontrolling interests in subsidiaries", ["670", "704"]),
                row(7, "Total liabilities and equity", ["137,806", "122,070"], subtotal=True),
            )
        ),
    )


BAL_PAGE = (
    "Tesla, Inc.\nConsolidated Balance Sheets\n(in millions, except per share data)\n"
    "Assets\nTotal assets 137,806 122,070\nLiabilities\n"
    "Total liabilities 54,941 48,390\n"
    "Redeemable noncontrolling interests in subsidiaries 58 63\n"
    "Total stockholders’ equity 82,137 72,913\n"
    "Noncontrolling interests in subsidiaries 670 704\n"
    "Total liabilities and equity 137,806 122,070"
)
BAL_TEXTS = {80: BAL_PAGE, 81: ""}


INC_LOCATED = LocatedStatement("INCOME", 82, 82, "Consolidated Statements of Operations")


def income_statement(multiplier=1_000_000, rows=None):
    return a.ParsedStatement(
        statement_type="INCOME",
        scale_text="(in millions, except per share data)",
        scale_multiplier=multiplier,
        per_share_exception=True,
        columns=(col(0, "2025-12-31", "FISCAL_YEAR", start="2025-01-01"),),
        rows=tuple(
            rows
            or (
                row(0, "Revenues", []),
                row(1, "Total revenues", ["94,827"], page=82, subtotal=True),
                row(2, "Restructuring and other", ["—"], page=82),
                row(3, "Net income", ["3,855"], page=82),
                row(4, "Net income per share of common stock attributable to common stockholders", []),
                row(5, "Basic", ["$ 1.18"], page=82),
            )
        ),
    )


INC_PAGE = (
    "Tesla, Inc.\nConsolidated Statements of Operations\n"
    "Revenues\nTotal revenues 94,827\nRestructuring and other —\n"
    "Net income 3,855\n"
    "Net income per share of common stock attributable to common stockholders\n"
    "Basic $ 1.18"
)
INC_TEXTS = {82: INC_PAGE}


def accept_balance(statement=None, texts=None):
    return a.accept_statement(
        statement or balance_statement(), TSLA_10K, texts or BAL_TEXTS,
        DICT, TSLA_CAL, BAL_LOCATED,
    )


def accept_income(statement=None, texts=None):
    return a.accept_statement(
        statement or income_statement(), TSLA_10K, texts or INC_TEXTS,
        DICT, TSLA_CAL, INC_LOCATED,
    )


def fails(results):
    return [c for c in results if c.status == "FAIL"]


# ------------------------------------------------------------- happy paths


def test_tesla_balance_accepted_with_mezzanine_residual():
    result = accept_balance()
    assert isinstance(result, a.AcceptedStatement)
    hard = [c for c in result.checks if c.check_name == "balance" and c.status == "PASS"]
    assert any("total_assets == total_liabilities_and_equity" in c.detail for c in hard)
    # Ben's check-3 note: Tesla's mezzanine rows produce a NONZERO residual in
    # the informative sub-check — INCONCLUSIVE, never FAIL.
    residuals = [
        c for c in result.checks if c.check_name == "balance" and c.status == "INCONCLUSIVE"
    ]
    assert residuals and "728000000" in residuals[0].detail
    assert "Redeemable noncontrolling interests in subsidiaries" in residuals[0].detail
    mapped = {f.concept for f in result.facts if f.concept}
    assert mapped == {"total_assets", "total_liabilities", "total_equity", "total_liabilities_and_equity", }
    assets = next(f for f in result.facts if f.concept == "total_assets" and f.column_index == 0)
    assert assets.value_normalized == "137806000000"
    assert (assets.fiscal_year, assets.fiscal_period, assets.duration_type) == (2025, "FY", "INSTANT")
    comparative = next(f for f in result.facts if f.concept == "total_assets" and f.column_index == 1)
    assert (comparative.fiscal_year, comparative.fiscal_period) == (2024, "FY")


def test_income_accepted_with_eps_and_dash():
    result = accept_income()
    assert isinstance(result, a.AcceptedStatement)
    eps = next(f for f in result.facts if f.concept == "eps_basic")
    # the benchmark's scale trap: per-share rows are NOT multiplied by 1e6
    assert eps.value_normalized == "1.18" and eps.unit == "USD_PER_SHARE" and eps.scale == 1
    dash = next(f for f in result.facts if f.raw_label == "Restructuring and other")
    assert Decimal(dash.value_normalized) == 0
    revenue = next(f for f in result.facts if f.concept == "revenue")
    assert revenue.value_normalized == "94827000000"
    # DoD: every stored fact has a PASS grounding check row
    grounded = {
        c.fact_ref for c in result.checks if c.check_name == "grounding" and c.status == "PASS"
    }
    assert {(f.row_index, f.column_index) for f in result.facts} <= grounded


# ------------------------------------------------------ check 1: grounding


def test_value_absent_from_page_is_rejected():
    rows = list(balance_statement().rows)
    rows[1] = row(1, "Total assets", ["999,999", "122,070"], subtotal=True)
    result = accept_balance(balance_statement(rows=rows))
    assert isinstance(result, a.Quarantine)
    assert any("'999,999' not found" in c.detail for c in fails(result.checks))


def test_whole_token_membership_1204_vs_11204():
    parsed = a.ParsedStatement(
        "BALANCE", "(in millions)", 1_000_000, False,
        (col(0, "2025-12-31", "INSTANT"),),
        (row(0, "Debt", ["1,204"], page=80),),
    )
    texts = {80: "Debt stuff 11,204", 81: ""}
    checks = a.check_grounding(
        parsed, {p: a.build_page_tokens(t) for p, t in texts.items()}, texts, BAL_LOCATED
    )
    assert any("'1,204' not found" in c.detail for c in fails(checks))


def test_fabricated_label_is_rejected():
    rows = list(balance_statement().rows)
    rows.append(row(8, "Imaginary line item", ["58"], page=80))
    result = accept_balance(balance_statement(rows=rows))
    assert isinstance(result, a.Quarantine)
    assert any("Imaginary line item" in c.detail for c in fails(result.checks))


def test_page_outside_located_range_is_rejected():
    rows = list(balance_statement().rows)
    rows[4] = row(4, "Redeemable noncontrolling interests in subsidiaries", ["58", "63"], page=99)
    result = accept_balance(balance_statement(rows=rows))
    assert isinstance(result, a.Quarantine)
    assert any("outside located range" in c.detail for c in fails(result.checks))


def test_value_present_only_in_stripped_furniture_fails_grounding():
    # stop-2 rider 3 pin: header/footer tokens must not ground anything.
    parsed = a.ParsedStatement(
        "BALANCE", "(in millions)", 1_000_000, False,
        (col(0, "2025-12-31", "INSTANT"),),
        (row(0, "Weird line", ["159"], page=80),),
    )
    texts = {
        80: "7/12/26, 6:53 PM tsla-20251231\nWeird line —\n"
            "https://www.sec.gov/Archives/edgar/x.htm 81/159",
        81: "",
    }
    checks = a.check_grounding(
        parsed, {p: a.build_page_tokens(t) for p, t in texts.items()}, texts, BAL_LOCATED
    )
    assert any("'159' not found" in c.detail for c in fails(checks))


# -------------------------------------------------------- check 0: periods


def test_duplicated_primary_column_is_rejected():
    statement = balance_statement(
        columns=(col(0, "2025-12-31", "INSTANT"), col(1, "2025-12-31", "INSTANT"))
    )
    result = accept_balance(statement)
    assert isinstance(result, a.Quarantine)
    assert any("exactly one primary" in c.detail for c in fails(result.checks))


def test_balance_with_duration_column_is_rejected():
    checks = a.check_periods(
        (col(0, "2025-12-31", "FISCAL_YEAR", start="2025-01-01"),),
        TSLA_10K, TSLA_CAL, "BALANCE",
    )
    assert any("has duration FISCAL_YEAR" in c.detail for c in fails(checks))


def test_comparative_not_earlier_is_rejected():
    checks = a.check_periods(
        (col(0, "2025-12-31", "INSTANT"), col(1, "2026-12-31", "INSTANT")),
        TSLA_10K, TSLA_CAL, "BALANCE",
    )
    assert any("strictly earlier" in c.detail for c in fails(checks))


def test_missing_period_start_on_duration_is_rejected():
    checks = a.check_periods(
        (col(0, "2025-12-31", "FISCAL_YEAR"),), TSLA_10K, TSLA_CAL, "INCOME"
    )
    assert any("missing period_start" in c.detail for c in fails(checks))


def test_deviation_a_prior_fye_comparative_accepted_but_arbitrary_gap_rejected():
    # 10-Q balance sheet: comparative = prior fiscal-year end (~3 months) OK…
    ok = a.check_periods(
        (col(0, "2026-03-31", "INSTANT"), col(1, "2025-12-31", "INSTANT")),
        TSLA_10Q, TSLA_CAL, "BALANCE",
    )
    assert not fails(ok)
    # …but an arbitrary mid-year instant is still rejected.
    bad = a.check_periods(
        (col(0, "2026-03-31", "INSTANT"), col(1, "2025-06-30", "INSTANT")),
        TSLA_10Q, TSLA_CAL, "BALANCE",
    )
    assert any("neither ~1 year" in c.detail for c in fails(bad))


def test_deviation_b_q1_cashflow_quarter_ok_discrete_quarter_rejected():
    ok = a.check_periods(
        (
            col(0, "2026-03-31", "QUARTER", start="2026-01-01"),
            col(1, "2025-03-31", "QUARTER", start="2025-01-01"),
        ),
        TSLA_10Q, TSLA_CAL, "CASHFLOW",
    )
    assert not fails(ok)
    bad = a.check_periods(
        (col(0, "2026-03-28", "QUARTER", start="2025-12-28"),),
        AAPL_10Q, AAPL_CAL, "CASHFLOW",
    )
    assert any("not at its fiscal year start" in c.detail for c in fails(bad))


def test_apple_four_column_two_group_income_passes():
    checks = a.check_periods(
        (
            col(0, "2026-03-28", "QUARTER", start="2025-12-28"),
            col(1, "2025-03-29", "QUARTER", start="2024-12-29"),
            col(2, "2026-03-28", "YTD", start="2025-09-28"),
            col(3, "2025-03-29", "YTD", start="2024-09-29"),
        ),
        AAPL_10Q, AAPL_CAL, "INCOME",
    )
    assert not fails(checks)


def test_annual_columns_two_years_apart_rejected():
    checks = a.check_periods(
        (
            col(0, "2025-12-31", "FISCAL_YEAR", start="2025-01-01"),
            col(1, "2023-12-31", "FISCAL_YEAR", start="2023-01-01"),
        ),
        TSLA_10K, TSLA_CAL, "INCOME",
    )
    assert any("not ~1 year apart" in c.detail for c in fails(checks))


# ---------------------------------------------------------- check 2: scale


def test_swapped_scale_declaration_quarantines():
    result = accept_income(income_statement(multiplier=1000))
    assert isinstance(result, a.Quarantine)
    assert any(
        c.check_name == "scale" and "outside concept revenue" in c.detail
        for c in fails(result.checks)
    )


def test_unmapped_scale_failure_drops_row_without_quarantine():
    rows = list(income_statement().rows)
    # An unmapped row whose magnitude explodes past the default USD band:
    # 99,999,999 × 1e6 = 9.99e13 > 1e13.
    rows.append(row(6, "Weighted average something", ["99,999,999"], page=82))
    texts = {82: INC_PAGE + "\nWeighted average something 99,999,999"}
    result = accept_income(income_statement(rows=rows), texts)
    assert isinstance(result, a.AcceptedStatement)
    assert not any(f.raw_label == "Weighted average something" for f in result.facts)
    assert any(
        c.check_name == "scale" and c.status == "INCONCLUSIVE" and "dropped" in c.detail
        for c in result.checks
    )


# -------------------------------------------------------- check 3: balance


def test_balance_identity_violation_quarantines():
    rows = list(balance_statement().rows)
    rows[7] = row(7, "Total liabilities and equity", ["137,807", "122,070"], subtotal=True)
    texts = {80: BAL_PAGE + "\nTotal liabilities and equity 137,807 122,070", 81: ""}
    result = accept_balance(balance_statement(rows=rows), texts)
    assert isinstance(result, a.Quarantine)
    assert any(
        "total_assets 137806000000 != total_liabilities_and_equity 137807000000" in c.detail
        for c in fails(result.checks)
    )


def test_balance_missing_subtotal_is_inconclusive_not_fatal():
    rows = [r for r in balance_statement().rows if r.row_index != 3]
    result = accept_balance(balance_statement(rows=rows))
    assert isinstance(result, a.AcceptedStatement)
    assert any(
        c.check_name == "balance" and c.status == "INCONCLUSIVE" and "skipped" in c.detail
        for c in result.checks
    )


# ------------------------------------------------------------- mapping etc.


AMBIGUOUS_YAML = """
version: 1
concepts:
  net_income:
    statement: INCOME
    unit: USD
    labels: {TSLA: ["Net income"]}
    disambiguate_from: [net_income_attributable_common]
  net_income_attributable_common:
    statement: INCOME
    unit: USD
    labels: {TSLA: ["Net income"]}
    disambiguate_from: [net_income]
disambiguation_pairs:
  - [net_income, net_income_attributable_common]
"""


def test_ambiguous_label_stored_unmapped(tmp_path):
    path = tmp_path / "concepts.yaml"
    path.write_text(AMBIGUOUS_YAML)
    ambiguous_dict = dictionary_mod.load(path)
    result = a.accept_statement(
        income_statement(), TSLA_10K, INC_TEXTS, ambiguous_dict, TSLA_CAL, INC_LOCATED
    )
    assert isinstance(result, a.AcceptedStatement)
    net_income = [f for f in result.facts if f.raw_label == "Net income"]
    assert net_income and all(f.concept is None for f in net_income)
    assert any(
        c.check_name == "mapping" and "net_income_attributable_common" in c.detail
        for c in result.checks
    )


def test_share_count_basic_is_not_eps():
    rows = list(income_statement().rows) + [
        row(6, "Weighted average shares used in computing net income per share of common stock", []),
        row(7, "Basic", ["3,225"], page=82),
    ]
    texts = {82: INC_PAGE + "\nWeighted average shares used in computing net income per share of common stock\nBasic 3,225"}
    result = accept_income(income_statement(rows=rows), texts)
    assert isinstance(result, a.AcceptedStatement)
    share_row = [f for f in result.facts if f.row_index == 7]
    assert share_row and share_row[0].concept is None


def test_normalize_value_forms():
    assert a.normalize_value("(1,204)", 1_000_000) == Decimal("-1204000000")
    assert a.normalize_value("$ 96,773", 1_000_000) == Decimal("96773000000")
    assert a.normalize_value("2.13", 1) == Decimal("2.13")
    assert a.normalize_value("—", 1_000_000) == 0
    with pytest.raises(Exception):
        a.normalize_value("N/A", 1)
