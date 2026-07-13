"""Keyed lookup (§5.3). Multiple provenance rows for one key: all agree =>
preferred provenance (own-report filing, else most recently filed) with a
corroboration note; any disagreement => Conflict, both sources shown, no
computation. Misses are typed refusals. P1.3 adds the fuzzy fallback."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .types import (
    FactRecord,
    Refusal,
    RefusalKind,
    ResolvedQuery,
    RetrievedFact,
    TypedPeriod,
    duration_family,
)


@dataclass(frozen=True)
class RetrievedFacts:
    # keyed by (concept, period); rank_deltas tolerates per-concept misses
    facts: dict[tuple[str, TypedPeriod], RetrievedFact]


@dataclass(frozen=True)
class ConflictFound:
    concept: str
    period: TypedPeriod
    records: tuple[FactRecord, ...]


def retrieve(rq: ResolvedQuery, reader, dictionary) -> RetrievedFacts | Refusal | ConflictFound:
    facts: dict[tuple[str, TypedPeriod], RetrievedFact] = {}
    for concept in rq.concepts:
        statement = dictionary.entries[concept].statement
        for period in rq.periods:
            rows = reader.lookup(
                rq.ticker,
                concept,
                period.fiscal_year,
                period.fiscal_period,
                duration_family(statement, period.fiscal_period),
            )
            records = [FactRecord.from_row(r) for r in rows]
            if not records:
                if rq.operation == "rank_deltas":
                    continue  # per §5.4 rank_deltas uses concepts present in BOTH periods
                return Refusal(
                    RefusalKind.PERIOD_NOT_HELD,
                    f"no stored fact for {concept} {period.label()} ({rq.ticker})",
                )
            values = {Decimal(r.value_normalized) for r in records}
            if len(values) > 1:
                return ConflictFound(concept, period, tuple(records))
            preferred = _preferred(records)
            facts[(concept, period)] = RetrievedFact(preferred, len(records) - 1)
    if not facts:
        return Refusal(
            RefusalKind.PERIOD_NOT_HELD,
            f"no overlapping stored facts for {rq.operation} over {rq.periods}",
        )
    return RetrievedFacts(facts)


def _preferred(records: list[FactRecord]) -> FactRecord:
    """Own-report provenance (filing whose report period equals the fact's
    period) beats a comparative column; then most recently filed."""
    own = [r for r in records if r.filing_period_end == r.period_end]
    pool = own or records
    return max(pool, key=lambda r: r.filing_date)
