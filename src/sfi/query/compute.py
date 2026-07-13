"""Deterministic arithmetic with an emitted step trace (§5.4). All Decimal;
the LLM never computes, rounds, or restates a number (CLAUDE.md rule 2)."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from .types import (
    Computation,
    Refusal,
    RefusalKind,
    ResolvedQuery,
    RetrievedFact,
    Step,
    TypedPeriod,
)

_RATIO_PLACES = Decimal("1e-10")  # trace precision for divisions


def _durations_compatible(a, b) -> bool:
    """Same duration_type, or the D3 rider (DEVIATIONS.md): CASHFLOW facts
    whose spans both start at their fiscal year's start — a Q1 'QUARTER' and
    a YTD are the same kind of cumulative span (check 0b guarantees the
    fiscal-year-start property for every stored CASHFLOW fact)."""
    if a.duration_type == b.duration_type:
        return True
    return (
        a.statement_type == "CASHFLOW"
        and b.statement_type == "CASHFLOW"
        and {a.duration_type, b.duration_type} <= {"QUARTER", "YTD"}
    )


def compute(
    rq: ResolvedQuery, retrieved: dict[tuple[str, TypedPeriod], RetrievedFact]
) -> Computation | Refusal:
    op = rq.operation
    if op == "value":
        return _value(rq, retrieved)
    if op in ("delta", "growth"):
        return _delta_growth(rq, retrieved, op)
    if op == "margin":
        return _margin(rq, retrieved)
    if op == "rank_deltas":
        return _rank_deltas(rq, retrieved)
    return Refusal(RefusalKind.UNPARSEABLE_QUESTION, f"unsupported operation {op!r}")


def _fact(retrieved, concept, period) -> RetrievedFact:
    return retrieved[(concept, period)]


def _value(rq, retrieved):
    concept = rq.concepts[0]
    period = rq.periods[0]
    f = _fact(retrieved, concept, period).record
    steps = (
        Step(1, f"value = {f.value_normalized} (printed {f.value_raw!r} × scale {f.scale})",
             f.value_normalized),
    )
    return Computation("value", steps, f.value_normalized, f.unit,
                       format_value(Decimal(f.value_normalized), f.unit))


def _pair(rq, retrieved, concept):
    newer = _fact(retrieved, concept, rq.periods[0]).record
    older = _fact(retrieved, concept, rq.periods[1]).record
    return newer, older


def _delta_growth(rq, retrieved, op):
    concept = rq.concepts[0]
    newer, older = _pair(rq, retrieved, concept)
    if not _durations_compatible(newer, older):
        return Refusal(
            RefusalKind.CROSS_DURATION,
            f"refusing {op} across duration types "
            f"({newer.duration_type} {rq.periods[0].label()} vs "
            f"{older.duration_type} {rq.periods[1].label()}) — annual/quarterly "
            f"mixing is a type error",
        )
    if newer.unit != older.unit:
        return Refusal(
            RefusalKind.CROSS_DURATION,
            f"incompatible units {newer.unit} vs {older.unit}",
        )
    y, x = Decimal(newer.value_normalized), Decimal(older.value_normalized)
    delta = y - x
    steps = [Step(1, f"delta = {y} - {x}", str(delta))]
    if op == "delta":
        return Computation("delta", tuple(steps), str(delta), newer.unit,
                           format_value(delta, newer.unit))
    if x == 0:
        return Refusal(
            # No dedicated kind exists in the frozen enum for a zero-base
            # growth; UNPARSEABLE is the honest closest ("cannot be computed
            # as asked"), with the why in the reason.
            RefusalKind.UNPARSEABLE_QUESTION,
            "growth is undefined: the base period value is zero",
        )
    growth = (delta / abs(x)).quantize(_RATIO_PLACES)
    steps.append(Step(2, f"growth = delta / |{x}|", str(growth)))
    return Computation(
        "growth", tuple(steps), str(growth), "ratio", format_ratio(growth),
        sign_convention=x < 0,
    )


def _margin(rq, retrieved):
    num_c, den_c = rq.concepts[0], rq.concepts[1]
    steps: list[Step] = []
    margins: list[Decimal] = []
    n = 0
    for period in rq.periods:
        a = _fact(retrieved, num_c, period).record
        b = _fact(retrieved, den_c, period).record
        if not _durations_compatible(a, b):
            return Refusal(
                RefusalKind.CROSS_DURATION,
                f"{num_c} ({a.duration_type}) vs {den_c} ({b.duration_type}) "
                f"for {period.label()}",
            )
        bv = Decimal(b.value_normalized)
        if bv == 0:
            return Refusal(
                RefusalKind.UNPARSEABLE_QUESTION,
                f"margin is undefined: {den_c} is zero in {period.label()}",
            )
        m = (Decimal(a.value_normalized) / bv).quantize(_RATIO_PLACES)
        n += 1
        steps.append(
            Step(n, f"margin({period.label()}) = {a.value_normalized} / {b.value_normalized}", str(m))
        )
        margins.append(m)
    if len(margins) == 1:
        return Computation("margin", tuple(steps), str(margins[0]), "ratio",
                           format_ratio(margins[0]))
    change = margins[0] - margins[1]
    n += 1
    steps.append(Step(n, f"change = margin({rq.periods[0].label()}) - margin({rq.periods[1].label()})",
                      str(change)))
    return Computation("margin", tuple(steps), str(change), "pp", format_pp(change))


def _rank_deltas(rq, retrieved):
    newer_p, older_p = rq.periods[0], rq.periods[1]
    rows = []
    steps: list[Step] = []
    n = 0
    for concept in rq.concepts:
        if (concept, newer_p) not in retrieved or (concept, older_p) not in retrieved:
            continue  # only concepts present in BOTH periods (§5.4)
        newer = retrieved[(concept, newer_p)].record
        older = retrieved[(concept, older_p)].record
        if not _durations_compatible(newer, older):
            continue
        y, x = Decimal(newer.value_normalized), Decimal(older.value_normalized)
        delta = y - x
        growth = (delta / abs(x)).quantize(_RATIO_PLACES) if x != 0 else None
        n += 1
        steps.append(Step(n, f"{concept}: delta = {y} - {x}", str(delta)))
        rows.append(
            {
                "concept": concept,
                "raw_label": newer.raw_label,
                "newer": str(y),
                "older": str(x),
                "delta": str(delta),
                "growth": str(growth) if growth is not None else None,
                "unit": newer.unit,
            }
        )
    if not rows:
        return Refusal(
            RefusalKind.PERIOD_NOT_HELD,
            f"no concept present in both {newer_p.label()} and {older_p.label()}",
        )
    rows.sort(
        key=lambda r: abs(Decimal(r["delta"])), reverse=True
    )
    top = rows[0]
    formatted = (
        f"largest absolute change: {top['raw_label']} "
        f"{format_value(Decimal(top['delta']), top['unit'])}"
    )
    return Computation("rank_deltas", tuple(steps), top["delta"], top["unit"],
                       formatted, table=tuple(rows))


# ------------------------------------------------------------- renderings


def format_value(v: Decimal, unit: str) -> str:
    if unit == "USD_PER_SHARE":
        return f"${v}"
    if unit == "USD":
        millions = (v / 1_000_000).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        return f"${millions:,} million"
    return str(v)


def format_ratio(r: Decimal) -> str:
    pct = (r * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return f"{pct}%"


def format_pp(d: Decimal) -> str:
    pp = (d * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return f"{pp} percentage points"


def allowed_renderings(value: Decimal, unit: str) -> frozenset[str]:
    """The closed whitelist (§5.4) the P1 numeral audit checks membership
    against — 'declared rounding' made mechanical."""
    out = {str(value)}
    if unit in ("USD",):
        i = value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        out |= {f"{i:,}", f"${i:,}", str(i)}
        millions = value / 1_000_000
        billions = value / 1_000_000_000
        for scaled, word in ((millions, "million"), (billions, "billion")):
            for places in ("1", "0.1"):
                q = scaled.quantize(Decimal(places), rounding=ROUND_HALF_UP)
                out |= {f"${q:,} {word}", f"{q:,} {word}"}
    elif unit == "USD_PER_SHARE":
        out |= {f"${value}", f"{value}"}
    elif unit in ("ratio", "pp"):
        for places in ("0.1", "0.01"):
            pct = (value * 100).quantize(Decimal(places), rounding=ROUND_HALF_UP)
            suffix = "%" if unit == "ratio" else " pp"
            out |= {f"{pct}{suffix}"}
        for places in ("0.01", "0.001", "0.0001"):
            out.add(str(value.quantize(Decimal(places), rounding=ROUND_HALF_UP)))
    return frozenset(out)
