"""Deterministic gates (§5.2): aliases -> typed periods; corpus/dictionary/
period availability. The planner extracts; THIS module decides refusals."""

from __future__ import annotations

from datetime import date, timedelta

from ..common import config
from ..common.periods import FiscalCalendar
from .types import (
    PlanPeriod,
    Plan,
    Refusal,
    RefusalKind,
    ResolvedQuery,
    TypedPeriod,
    duration_family,
)

DERIVED = {
    "DERIVED_GROSS_MARGIN": ("gross_margin", ("gross_profit", "revenue")),
    "DERIVED_OPERATING_MARGIN": ("operating_margin", ("operating_income", "revenue")),
    "DERIVED_NET_MARGIN": ("net_margin", ("net_income", "revenue")),
}


def _held(reader, ticker: str, concept: str, statement: str) -> list:
    """Held (fy, fp) pairs for a concept, newest first, restricted to the
    duration family a question about that statement would target."""
    rows = reader.held_periods(ticker, concept)
    held = []
    for r in rows:
        if r["duration_type"] in duration_family(statement, r["fiscal_period"]):
            held.append((r["fiscal_year"], r["fiscal_period"], r["period_end"]))
    return held


# SEC 10-Q deadline for large accelerated filers is 40 days; a just-ended,
# unfiled period inside this window is honestly "not filed yet", not
# "outside the corpus".
_FILING_GRACE = timedelta(days=45)


def _last_completed_quarter(calendar: FiscalCalendar, today: date) -> tuple[int, str]:
    """'last quarter' denotes the most recent COMPLETED fiscal quarter —
    which in a filing lag window is typically unfiled, and must route to the
    NOT_FILED_YET honesty gate rather than silently substituting the latest
    held quarter (benchmark B20 spec ruling)."""
    fy = calendar.fiscal_year_of(today)
    fy_start_anchor = calendar.fy_end_approx(fy - 1)
    for quarter in (3, 2, 1):
        end = fy_start_anchor + timedelta(days=round(quarter * 91.3125))
        if end <= today:
            return fy, f"Q{quarter}"
    # inside the first quarter of fy: the prior completed quarter is last
    # fiscal year's Q4, which has no 10-Q — the nearest quarterly period is
    # the prior year's Q3
    return fy - 1, "Q3"


def _default_pair(held: list) -> tuple[TypedPeriod, TypedPeriod] | None:
    """Latest same-fiscal-period pair (YoY-comparable), for change-type
    operations asked without explicit periods."""
    for fy, fp, _ in held:
        for fy2, fp2, _ in held:
            if fp2 == fp and fy2 < fy:
                return (TypedPeriod(fy, fp), TypedPeriod(fy2, fp2))
    return None


def resolve(p: Plan, manifest: dict, dictionary, reader, today: date) -> ResolvedQuery | Refusal:
    if p.intent == "narrative":
        return Refusal(
            RefusalKind.NARRATIVE_NOT_SUPPORTED,
            "narrative questions are not supported in P0 — the prose path "
            "ships in P1.5 with weaker (quoted, non-computed) guarantees",
        )
    if p.intent == "other":
        return Refusal(
            RefusalKind.UNPARSEABLE_QUESTION,
            f"could not extract a supported question (planner notes: {p.notes or 'none'})",
        )
    if p.company not in config.TICKERS:
        named = p.company_text or "no company"
        return Refusal(
            RefusalKind.OUT_OF_CORPUS,
            f"{named!r} is not in the ingested corpus (held: {', '.join(config.TICKERS)})",
        )
    ticker = p.company
    calendar = FiscalCalendar.from_mmdd(
        manifest["companies"][ticker]["fiscal_year_end_mmdd"]
    )

    derived = None
    if p.operation == "rank_deltas" or p.intent == "rank_changes":
        # Statement-wide concept set (§5.2); the statement comes from the
        # question's own words, visible in the echo.
        text = f"{p.concept_text} {p.notes}".casefold()
        statement = "BALANCE" if "balance" in text else (
            "CASHFLOW" if "cash" in text else "INCOME"
        )
        concepts = tuple(
            cid for cid in dictionary.concept_ids()
            if dictionary.entries[cid].statement == statement
        )
        operation = "rank_deltas"
    elif p.concept in DERIVED:
        # Derived metrics are compute-layer margin formulas (§3.2); a
        # "change" question becomes margin over two periods + a delta step.
        derived, concepts = DERIVED[p.concept]
        operation = "margin"
    elif p.concept in dictionary.entries:
        concepts = (p.concept,)
        operation = p.operation
    else:
        return Refusal(
            RefusalKind.CONCEPT_NOT_SUPPORTED,
            f"{p.concept_text or p.concept!r} is not in the concept dictionary "
            f"(P0 answers only dictionary concepts; fuzzy fallback arrives in P1.3)",
        )

    primary = concepts[0]
    statement = dictionary.entries[primary].statement
    held = _held(reader, ticker, primary, statement)
    if not held:
        return Refusal(
            RefusalKind.PERIOD_NOT_HELD,
            f"no stored facts for {primary} ({ticker}) — corpus covers only "
            f"the six 2025/2026 filings",
        )
    held_set = {(fy, fp) for fy, fp, _ in held}

    alias = False
    periods: list[TypedPeriod] = []
    # §3.5's maxItems-2 lives here (the API rejects array schema constraints)
    for pp in p.periods[:2]:
        fy, fp = pp.fiscal_year, pp.fiscal_period
        if fp == "LATEST" and fy is None:
            if "last quarter" in p.periods_text.casefold():
                fy, fp = _last_completed_quarter(calendar, today)
            else:
                fy, fp = held[0][0], held[0][1]
            alias = True
        elif fp == "LATEST":
            matches = [h for h in held if h[0] == fy]
            if not matches:
                fp = held[0][1]  # fall through to the held check below
            else:
                fp = matches[0][1]
            alias = True
        elif fy is None:
            matches = [h for h in held if h[1] == fp]
            if matches:
                fy = matches[0][0]
            else:
                fy = held[0][0]
            alias = True
        periods.append(TypedPeriod(fy, fp))

    needs_two = operation in ("growth", "delta", "rank_deltas") or (
        operation == "margin" and len(periods) >= 2
    )
    if operation == "margin" and derived and len(p.periods) == 0:
        # "How did X's margin change?" with no periods: latest comparable pair.
        pair = _default_pair(held)
        if pair:
            periods, alias, needs_two = list(pair), True, True
    if needs_two and len(periods) < 2:
        pair = _default_pair(held)
        if pair is None:
            return Refusal(
                RefusalKind.PERIOD_NOT_HELD,
                f"{operation} needs two comparable periods; corpus holds only "
                f"{[f'{fp} FY{fy}' for fy, fp, _ in held]}",
            )
        if len(periods) == 1:
            # keep the stated period as the newer side, find its YoY partner
            stated = periods[0]
            partner = next(
                (TypedPeriod(fy, fp) for fy, fp, _ in held
                 if fp == stated.fiscal_period and fy == stated.fiscal_year - 1),
                None,
            )
            if partner is None:
                return Refusal(
                    RefusalKind.PERIOD_NOT_HELD,
                    f"no held comparison period for {stated.label()}",
                )
            periods = [stated, partner]
        else:
            periods = list(pair)
        alias = True
    if not periods:  # value/margin with nothing stated -> latest held
        periods = [TypedPeriod(held[0][0], held[0][1])]
        alias = True

    periods.sort(key=lambda tp: (tp.fiscal_year, tp.fiscal_period), reverse=True)

    for tp in periods:
        if (tp.fiscal_year, tp.fiscal_period) in held_set:
            continue
        # Not held: is it a future/unfiled period (honesty case) or just
        # outside the corpus?
        if tp.fiscal_period == "FY":
            approx_end = calendar.fy_end_approx(tp.fiscal_year)
        else:
            from datetime import timedelta

            quarter = int(tp.fiscal_period[1])
            approx_end = calendar.fy_end_approx(tp.fiscal_year - 1) + timedelta(
                days=round(quarter * 91.3125)
            )
        if approx_end + _FILING_GRACE >= today or tp.fiscal_year > held[0][0]:
            alternatives = ()
            pair = _default_pair(held)
            if pair:
                alternatives = (
                    f"{pair[0].label()} vs {pair[1].label()} is answerable — ask that?",
                )
            return Refusal(
                RefusalKind.NOT_FILED_YET,
                f"{tp.label()} ({ticker}) is not filed as of {today.isoformat()}",
                alternatives,
            )
        return Refusal(
            RefusalKind.PERIOD_NOT_HELD,
            f"{tp.label()} is a valid period but no filing in the corpus covers it "
            f"(held: {sorted(held_set, reverse=True)})",
        )

    if operation == "rank_deltas":
        metric = f"all {dictionary.entries[primary].statement} concepts"
    else:
        metric = derived or primary
    if len(periods) == 2:
        restatement = (
            f"{operation} of {ticker} {metric}, {periods[0].label()} vs {periods[1].label()}"
        )
    else:
        restatement = f"{operation} of {ticker} {metric}, {periods[0].label()}"
    if alias:
        restatement += " (period resolved from context)"

    return ResolvedQuery(
        ticker=ticker,
        concepts=concepts,
        operation=operation,
        periods=tuple(periods),
        derived=derived,
        alias_interpreted=alias,
        restatement=restatement,
    )
