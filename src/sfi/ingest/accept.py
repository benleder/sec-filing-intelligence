"""Acceptance harness (§4.3): checks 0-3, cell normalization, concept mapping.
L2 — imports common, concepts. Never imports query/.

Two FLAGGED DEVIATIONS from §4.3 as written, both forced by the real PDFs
(rule 1: deviations are visible, tested, and pending Ben's ratification):

DEVIATION A — check 0(c), INSTANT groups. 10-Q balance sheets print the
PRIOR FISCAL YEAR END as the comparative column (Tesla Q1: Dec 31, ~3 months
earlier; Apple Q2: late September, ~6 months earlier). The as-written
"~1 year apart" rule would quarantine every correct 10-Q balance-sheet
parse. INSTANT comparatives therefore accept EITHER ~1 year before the
primary OR the fiscal year end immediately preceding the primary (±14 days).
Duration groups keep the as-written rule, applied to consecutive column gaps
(Tesla's 10-K prints three annual columns, each 1 year apart).

DEVIATION B — check 0(b), CASHFLOW. Tesla's Q1 cash-flow statement prints
"Three Months Ended March 31"; a faithful parser reads QUARTER, but for a Q1
filing three months IS the fiscal year-to-date. Every non-INSTANT CASHFLOW
column must start at its own fiscal year's start (±14 days) — which admits
Q1 "quarters" and rejects discrete later quarters, preserving the design's
intent that cash-flow statements are cumulative.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from ..common.models import CheckResult, Filing
from ..common.periods import FiscalCalendar, PeriodResolutionError
from ..common.text import normalize_chars, strip_print_furniture
from ..concepts.dictionary import Ambiguity, Dictionary, Match, normalize_label
from .segment import LocatedStatement

_TOL = timedelta(days=14)
_YEAR = timedelta(days=365)
_QUARTER_DAYS = 91.3125
_DASHES = {"—", "–", "-"}

DEFAULT_BANDS = {
    "USD": (Decimal("1e3"), Decimal("1e13")),
    "USD_PER_SHARE": (Decimal("0.001"), Decimal("1e4")),
    "SHARES": (Decimal("1"), Decimal("1e14")),
}


class ParseShapeError(Exception):
    pass


# ---------------------------------------------------------------- parsed shapes


@dataclass(frozen=True)
class ParsedColumn:
    index: int
    header_verbatim: str
    period_start: str | None
    period_end: str
    duration: str


@dataclass(frozen=True)
class ParsedCell:
    column_index: int
    value_verbatim: str
    page: int


@dataclass(frozen=True)
class ParsedRow:
    row_index: int
    label_verbatim: str
    indent_level: int
    is_subtotal: bool
    cells: tuple[ParsedCell, ...]


@dataclass(frozen=True)
class ParsedStatement:
    statement_type: str
    scale_text: str
    scale_multiplier: int
    per_share_exception: bool
    columns: tuple[ParsedColumn, ...]
    rows: tuple[ParsedRow, ...]

    @classmethod
    def from_json(cls, doc: dict) -> "ParsedStatement":
        columns = tuple(
            ParsedColumn(c["index"], c["header_verbatim"], c["period_start"], c["period_end"], c["duration"])
            for c in doc["columns"]
        )
        if not columns:
            raise ParseShapeError("parser returned zero columns")
        indices = [c.index for c in columns]
        if len(set(indices)) != len(indices):
            raise ParseShapeError(f"duplicate column indices: {indices}")
        known = set(indices)
        rows = []
        for r in doc["rows"]:
            cells = tuple(
                ParsedCell(c["column_index"], c["value_verbatim"], c["page"]) for c in r["cells"]
            )
            for cell in cells:
                if cell.column_index not in known:
                    raise ParseShapeError(
                        f"row {r['row_index']} cell references unknown column {cell.column_index}"
                    )
            rows.append(
                ParsedRow(r["row_index"], r["label_verbatim"], r["indent_level"], bool(r["is_subtotal"]), cells)
            )
        if not rows:
            raise ParseShapeError("parser returned zero rows")
        return cls(
            statement_type=doc["statement_type"],
            scale_text=doc["scale"]["text_verbatim"],
            scale_multiplier=int(doc["scale"]["multiplier"]),
            per_share_exception=bool(doc["scale"]["per_share_exception"]),
            columns=columns,
            rows=tuple(rows),
        )


@dataclass(frozen=True)
class CandidateFact:
    row_index: int
    column_index: int
    raw_label: str
    section: str | None
    indent_level: int
    is_subtotal: bool
    page: int
    concept: str | None
    match_method: str | None
    unit: str
    scale: int
    value_raw: str
    value_normalized: str
    period_start: str | None
    period_end: str
    duration_type: str
    fiscal_year: int
    fiscal_period: str


@dataclass(frozen=True)
class AcceptedStatement:
    facts: tuple[CandidateFact, ...]
    checks: tuple[CheckResult, ...]


@dataclass(frozen=True)
class Quarantine:
    reason: str
    checks: tuple[CheckResult, ...]


# ------------------------------------------------------------------ check 0


def check_periods(
    columns: tuple[ParsedColumn, ...],
    filing: Filing,
    calendar: FiscalCalendar,
    statement_type: str,
) -> list[CheckResult]:
    results: list[CheckResult] = []

    def fail(detail: str) -> None:
        results.append(CheckResult("period", "FAIL", None, detail))

    parsed: list[tuple[ParsedColumn, date | None, date]] = []
    for col in columns:
        try:
            end = date.fromisoformat(col.period_end)
            start = date.fromisoformat(col.period_start) if col.period_start else None
        except ValueError:
            fail(f"column {col.index} has unparseable ISO dates "
                 f"({col.period_start!r}, {col.period_end!r})")
            continue
        if col.duration == "INSTANT" and start is not None:
            fail(f"column {col.index} is INSTANT but carries period_start {col.period_start}")
        if col.duration != "INSTANT" and start is None:
            fail(f"column {col.index} ({col.duration}) is missing period_start")
        parsed.append((col, start, end))

    # (b) duration kinds consistent with the statement type
    for col, start, end in parsed:
        if statement_type == "BALANCE" and col.duration != "INSTANT":
            fail(f"BALANCE column {col.index} has duration {col.duration}")
        if statement_type in ("INCOME", "CASHFLOW") and col.duration == "INSTANT":
            fail(f"{statement_type} column {col.index} is INSTANT")
        if statement_type == "CASHFLOW" and col.duration != "INSTANT" and start is not None:
            # DEVIATION B: any non-INSTANT cash-flow column must start at its
            # own fiscal year's start — admits Q1 "three months", rejects
            # discrete later quarters.
            fy_start = calendar.fy_end_approx(calendar.fiscal_year_of(end) - 1) + timedelta(days=1)
            if abs(start - fy_start) > _TOL:
                fail(
                    f"CASHFLOW column {col.index} starts {start}, not at its fiscal "
                    f"year start (~{fy_start}) — discrete quarters are not cumulative"
                )

    filing_end = date.fromisoformat(filing.period_end)
    groups: dict[str, list[tuple[ParsedColumn, date | None, date]]] = {}
    for item in parsed:
        groups.setdefault(item[0].duration, []).append(item)

    for duration, members in groups.items():
        primaries = [m for m in members if m[2] == filing_end]
        if len(primaries) != 1:
            fail(
                f"{duration} group must contain exactly one primary column ending "
                f"{filing.period_end}; got {len(primaries)} of {len(members)}"
            )
            continue
        primary_end = primaries[0][2]
        comparatives = sorted((m[2] for m in members if m is not primaries[0]), reverse=True)
        if any(c >= primary_end for c in comparatives):
            fail(f"{duration} group has a comparative column not strictly earlier than the primary")
            continue
        if duration == "INSTANT":
            # DEVIATION A: ~1 year before the primary OR the immediately
            # preceding fiscal year end (10-Q balance-sheet comparatives).
            prior_fye = calendar.fy_end_approx(calendar.fiscal_year_of(primary_end) - 1)
            for comp in comparatives:
                year_apart = abs((primary_end - comp) - _YEAR) <= _TOL
                is_prior_fye = abs(comp - prior_fye) <= _TOL
                if not (year_apart or is_prior_fye):
                    fail(
                        f"INSTANT comparative {comp} is neither ~1 year before the "
                        f"primary {primary_end} nor the prior fiscal year end (~{prior_fye})"
                    )
        else:
            ends = [primary_end, *comparatives]
            for newer, older in zip(ends, ends[1:]):
                if abs((newer - older) - _YEAR) > _TOL:
                    fail(
                        f"{duration} columns ending {newer} and {older} are not "
                        f"~1 year apart (±14 days)"
                    )

    if not results:
        summary = ", ".join(
            f"{d}: {len(m)} column(s)" for d, m in sorted(groups.items())
        )
        results.append(CheckResult("period", "PASS", None, f"groups ok — {summary}"))
    return results


def label_columns(
    columns: tuple[ParsedColumn, ...], calendar: FiscalCalendar
) -> dict[int, tuple[int, str]]:
    """Assign (fiscal_year, fiscal_period) display labels per column."""
    labels: dict[int, tuple[int, str]] = {}
    for col in columns:
        end = date.fromisoformat(col.period_end)
        fy = calendar.fiscal_year_of(end)
        if col.duration == "FISCAL_YEAR":
            labels[col.index] = (fy, "FY")
            continue
        if col.duration == "INSTANT" and abs(end - calendar.fy_end_approx(fy)) <= _TOL:
            labels[col.index] = (fy, "FY")
            continue
        days_in = (end - calendar.fy_end_approx(fy - 1)).days
        quarter = round(days_in / _QUARTER_DAYS)
        if quarter not in (1, 2, 3):
            raise PeriodResolutionError(
                f"column {col.index} ending {end} resolves to Q{quarter} of FY{fy}"
            )
        labels[col.index] = (fy, f"Q{quarter}")
    return labels


# ------------------------------------------------------------------ check 1


def build_page_tokens(plain_page_text: str) -> frozenset[str]:
    """Grounding token set: furniture-stripped (stop-2 rider 3), char-
    normalized (rider 2), whitespace-split whole tokens."""
    return frozenset(normalize_chars(strip_print_furniture(plain_page_text)).split())


def _normalized_blob(plain_texts: dict[int, str]) -> str:
    joined = " ".join(strip_print_furniture(plain_texts[p]) for p in sorted(plain_texts))
    return re.sub(r"\s+", " ", normalize_chars(joined))


def _stripped_value(value_verbatim: str) -> str:
    v = normalize_chars(value_verbatim).replace("$", "").strip()
    if v.startswith("(") and v.endswith(")"):
        v = v[1:-1].strip()
    return v


def check_grounding(
    parsed: ParsedStatement,
    page_tokens: dict[int, frozenset[str]],
    plain_texts: dict[int, str],
    located: LocatedStatement,
) -> list[CheckResult]:
    """Anti-hallucination, absolute. Honest limit (stated here and in the
    walkthrough): proves each token EXISTS on the claimed page, not that it is
    attached to the right row/column."""
    results: list[CheckResult] = []
    blob = _normalized_blob(plain_texts)
    for row in parsed.rows:
        label_norm = re.sub(r"\s+", " ", normalize_chars(row.label_verbatim)).strip()
        if label_norm and label_norm not in blob:
            results.append(
                CheckResult(
                    "grounding", "FAIL", (row.row_index, -1),
                    f"label {row.label_verbatim!r} not found in pages "
                    f"{located.page_start}-{located.page_end}",
                )
            )
        for cell in row.cells:
            ref = (row.row_index, cell.column_index)
            if not (located.page_start <= cell.page <= located.page_end):
                results.append(
                    CheckResult(
                        "grounding", "FAIL", ref,
                        f"claimed page {cell.page} outside located range "
                        f"{located.page_start}-{located.page_end}",
                    )
                )
                continue
            v = _stripped_value(cell.value_verbatim)
            candidates = {v, f"({v})", f"${v}", f"$({v})"}
            if candidates & page_tokens[cell.page]:
                results.append(
                    CheckResult("grounding", "PASS", ref, f"token {v!r} on page {cell.page}")
                )
            else:
                results.append(
                    CheckResult(
                        "grounding", "FAIL", ref,
                        f"token {v!r} not found on page {cell.page}",
                    )
                )
    return results


# ------------------------------------------------------- normalization + mapping


def normalize_value(value_verbatim: str, multiplier: int) -> Decimal:
    v = normalize_chars(value_verbatim).replace("$", "").strip()
    negative = False
    if v.startswith("(") and v.endswith(")"):
        negative = True
        v = v[1:-1].strip()
    if v in _DASHES:
        return Decimal(0)
    v = v.replace(",", "").replace(" ", "")
    d = Decimal(v)  # InvalidOperation propagates to the caller
    if negative:
        d = -d
    return d * multiplier


def _is_per_share(raw_label: str, entry) -> bool:
    if entry is not None and entry.unit == "USD_PER_SHARE":
        return True
    return "per share" in normalize_label(raw_label)


# ------------------------------------------------------------------ check 2


def check_scale(fact: CandidateFact, entry, default_bands=DEFAULT_BANDS) -> CheckResult:
    ref = (fact.row_index, fact.column_index)
    value = abs(Decimal(fact.value_normalized))
    if value == 0:
        return CheckResult("scale", "PASS", ref, "zero always passes")
    if entry is not None and entry.typical_magnitude is not None:
        low, high = entry.typical_magnitude
        source = f"concept {fact.concept}"
    else:
        low, high = default_bands[fact.unit]
        source = f"default {fact.unit} band"
    if low <= value <= high:
        return CheckResult("scale", "PASS", ref, f"|{value}| within {source}")
    return CheckResult(
        "scale", "FAIL", ref,
        f"|{value}| outside {source} [{low}, {high}] "
        f"(raw {fact.value_raw!r} × scale {fact.scale})",
    )


# ------------------------------------------------------------------ check 3


def check_balance(facts: list[CandidateFact], dictionary: Dictionary) -> list[CheckResult]:
    results: list[CheckResult] = []
    by_column: dict[int, dict[str, CandidateFact]] = {}
    for fact in facts:
        if fact.concept:
            by_column.setdefault(fact.column_index, {})[fact.concept] = fact

    for column_index in sorted(by_column):
        concepts = by_column[column_index]
        assets = concepts.get("total_assets")
        grand = concepts.get("total_liabilities_and_equity")
        liabilities = concepts.get("total_liabilities")
        equity = concepts.get("total_equity")

        if assets is None or grand is None:
            missing = [c for c, f in (("total_assets", assets), ("total_liabilities_and_equity", grand)) if f is None]
            results.append(
                CheckResult(
                    "balance", "INCONCLUSIVE", None,
                    f"column {column_index}: missing mapped totals {missing}",
                )
            )
            continue
        if Decimal(assets.value_normalized) == Decimal(grand.value_normalized):
            results.append(
                CheckResult(
                    "balance", "PASS", None,
                    f"column {column_index}: total_assets == total_liabilities_and_equity "
                    f"({assets.value_normalized})",
                )
            )
        else:
            results.append(
                CheckResult(
                    "balance", "FAIL", None,
                    f"column {column_index}: total_assets {assets.value_normalized} != "
                    f"total_liabilities_and_equity {grand.value_normalized}",
                )
            )
            continue

        # Informative sub-check — never FAIL on its own: real balance sheets
        # print mezzanine rows outside both subtotals (Tesla's redeemable
        # noncontrolling interests), so a residual here is reported, not fatal.
        if liabilities is None or equity is None:
            results.append(
                CheckResult(
                    "balance", "INCONCLUSIVE", None,
                    f"column {column_index}: L+E sub-check skipped (missing mapped subtotal)",
                )
            )
            continue
        residual = (
            Decimal(grand.value_normalized)
            - Decimal(liabilities.value_normalized)
            - Decimal(equity.value_normalized)
        )
        if residual == 0:
            results.append(
                CheckResult(
                    "balance", "PASS", None,
                    f"column {column_index}: total_liabilities + total_equity == grand total",
                )
            )
        else:
            between = [
                f.raw_label
                for f in facts
                if f.column_index == column_index
                and liabilities.row_index < f.row_index < grand.row_index
                and f.concept not in ("total_equity",)
            ]
            results.append(
                CheckResult(
                    "balance", "INCONCLUSIVE", None,
                    f"column {column_index}: L+E residual {residual} (rows between the "
                    f"totals: {sorted(set(between))})",
                )
            )
    if not any(r.check_name == "balance" for r in results):
        results.append(CheckResult("balance", "INCONCLUSIVE", None, "no mapped balance totals"))
    return results


# ------------------------------------------------------------ accept/quarantine


def accept_statement(
    parsed: ParsedStatement,
    filing: Filing,
    plain_texts: dict[int, str],
    dictionary: Dictionary,
    calendar: FiscalCalendar,
    located: LocatedStatement,
) -> AcceptedStatement | Quarantine:
    """Order: periods -> normalize -> grounding -> mapping -> scale -> balance.
    Any FAIL rejects the whole statement (never partially ingested)."""
    checks: list[CheckResult] = []

    if parsed.statement_type != located.statement_type:
        checks.append(
            CheckResult(
                "period", "FAIL", None,
                f"parser returned statement_type {parsed.statement_type}, "
                f"expected {located.statement_type}",
            )
        )
        return Quarantine(_reason(checks), tuple(checks))

    checks += check_periods(parsed.columns, filing, calendar, parsed.statement_type)
    if _failed(checks):
        return Quarantine(_reason(checks), tuple(checks))
    try:
        column_labels = label_columns(parsed.columns, calendar)
    except PeriodResolutionError as exc:
        checks.append(CheckResult("period", "FAIL", None, str(exc)))
        return Quarantine(_reason(checks), tuple(checks))
    columns_by_index = {c.index: c for c in parsed.columns}

    # grounding before normalization commits anything
    page_tokens = {p: build_page_tokens(t) for p, t in plain_texts.items()}
    checks += check_grounding(parsed, page_tokens, plain_texts, located)
    if _failed(checks):
        return Quarantine(_reason(checks), tuple(checks))

    # mapping (with printed section context) + normalization -> candidate facts
    facts: list[CandidateFact] = []
    section: str | None = None
    for row in parsed.rows:
        if not row.cells:
            section = row.label_verbatim
            continue
        result = dictionary.match(
            filing.ticker, parsed.statement_type, row.label_verbatim, section=section
        )
        concept = method = None
        entry = None
        if isinstance(result, Ambiguity):
            # Conservative by design (§3.2): ambiguous maps to NONE, warning row.
            checks.append(
                CheckResult(
                    "mapping", "INCONCLUSIVE", None,
                    f"row {row.row_index} label {row.label_verbatim!r} matches "
                    f"{list(result.candidates)}; stored unmapped",
                )
            )
        elif isinstance(result, Match):
            concept, method = result.concept, result.method
            entry = dictionary.entries[concept]
        per_share = _is_per_share(row.label_verbatim, entry)
        unit = entry.unit if entry else ("USD_PER_SHARE" if per_share else "USD")
        multiplier = 1 if per_share else parsed.scale_multiplier
        for cell in row.cells:
            try:
                value = normalize_value(cell.value_verbatim, multiplier)
            except (InvalidOperation, ValueError):
                checks.append(
                    CheckResult(
                        "scale", "FAIL", (row.row_index, cell.column_index),
                        f"unparseable value_verbatim {cell.value_verbatim!r}",
                    )
                )
                continue
            col = columns_by_index[cell.column_index]
            fy, fp = column_labels[cell.column_index]
            facts.append(
                CandidateFact(
                    row_index=row.row_index,
                    column_index=cell.column_index,
                    raw_label=row.label_verbatim,
                    section=section,
                    indent_level=row.indent_level,
                    is_subtotal=row.is_subtotal,
                    page=cell.page,
                    concept=concept,
                    match_method=method,
                    unit=unit,
                    scale=multiplier,
                    value_raw=cell.value_verbatim,
                    value_normalized=str(value),
                    period_start=col.period_start,
                    period_end=col.period_end,
                    duration_type=col.duration,
                    fiscal_year=fy,
                    fiscal_period=fp,
                )
            )
    if _failed(checks):
        return Quarantine(_reason(checks), tuple(checks))

    # scale sanity: mapped FAIL => quarantine; unmapped FAIL => drop the row
    # (no answer path in P0), record the check.
    kept: list[CandidateFact] = []
    for fact in facts:
        entry = dictionary.entries[fact.concept] if fact.concept else None
        result = check_scale(fact, entry)
        if result.status == "FAIL" and fact.concept is None:
            checks.append(
                CheckResult(
                    "scale", "INCONCLUSIVE", result.fact_ref,
                    f"unmapped row dropped: {result.detail}",
                )
            )
            continue
        checks.append(result)
        if result.status != "FAIL":
            kept.append(fact)
    if _failed(checks):
        return Quarantine(_reason(checks), tuple(checks))

    if parsed.statement_type == "BALANCE":
        checks += check_balance(kept, dictionary)
        if _failed(checks):
            return Quarantine(_reason(checks), tuple(checks))

    return AcceptedStatement(tuple(kept), tuple(checks))


def _failed(checks: list[CheckResult]) -> bool:
    return any(c.status == "FAIL" for c in checks)


def _reason(checks: list[CheckResult]) -> str:
    fails = [c for c in checks if c.status == "FAIL"]
    head = "; ".join(f"{c.check_name}: {c.detail}" for c in fails[:3])
    more = f" (+{len(fails) - 3} more)" if len(fails) > 3 else ""
    return head + more


def failure_feedback(checks: tuple[CheckResult, ...]) -> str:
    """J5: the single retry gets the failed checks appended verbatim."""
    return "\n".join(
        f"{c.check_name}: {c.detail}" for c in checks if c.status == "FAIL"
    )
