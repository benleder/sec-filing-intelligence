"""Evidence-object assembly (§3.4). Every numeric answer carries one; refusals
and conflicts get the reduced object — traceability applies to "no" too."""

from __future__ import annotations

from decimal import Decimal

from .compute import allowed_renderings
from .types import Computation, FactRecord, Plan, Refusal, ResolvedQuery, RetrievedFact

SCHEMA_VERSION = 1

_CAVEAT_TEXT = {
    "UNAUDITED_INTERIM": "10-Q figures are unaudited.",
    "FISCAL_CALENDAR": "Periods are fiscal; exact dates shown above.",
    "UNVERIFIED_FACT": "Facts are single-source in P0; the cross-filing tie "
                       "check that upgrades them to VERIFIED arrives in P1.",
    "SIGN_CONVENTION": "Growth base was negative; growth = delta / |base|.",
    "CONFLICTING_SOURCES": "Two filings print different values for this fact; "
                           "both are shown, nothing was computed.",
}


def _fact_entry(rf: RetrievedFact) -> dict:
    r = rf.record
    period_label = (
        f"FY{r.fiscal_year}" if r.fiscal_period == "FY" else f"{r.fiscal_period} FY{r.fiscal_year}"
    )
    entry = {
        "fact_id": r.fact_id,
        "company": r.ticker,
        "concept": r.concept,
        "raw_label": r.raw_label,
        "match_method": r.match_method,
        "filing": {
            "form_type": r.form_type,
            "accession_no": r.accession_no,
            "filing_date": r.filing_date,
        },
        "statement": r.statement_type,
        "page": r.page,
        "period": {
            "start": r.period_start,
            "end": r.period_end,
            "duration_type": r.duration_type,
            "fiscal_label": period_label,
        },
        "value_raw": r.value_raw,
        "value_normalized": r.value_normalized,
        "unit": r.unit,
        "scale": r.scale,
        "verification_status": r.verification_status,
    }
    if rf.corroborating:
        entry["corroborating_rows"] = rf.corroborating
    return entry


def _caveats(records: list[FactRecord], rq: ResolvedQuery | None,
             comp: Computation | None) -> list[dict]:
    codes: list[str] = []
    if any(r.form_type.startswith("10-Q") for r in records):
        codes.append("UNAUDITED_INTERIM")
    if (records and any(r.ticker == "AAPL" for r in records)) or (rq and rq.alias_interpreted):
        codes.append("FISCAL_CALENDAR")
    if any(r.verification_status == "UNVERIFIED" for r in records):
        codes.append("UNVERIFIED_FACT")
    if comp is not None and comp.sign_convention:
        codes.append("SIGN_CONVENTION")
    return [{"code": c, "text": _CAVEAT_TEXT[c]} for c in codes]


def build_evidence(
    question: str,
    p: Plan,
    rq: ResolvedQuery,
    facts: list[RetrievedFact],
    comp: Computation,
) -> dict:
    renderings: set[str] = set()
    for rf in facts:
        renderings |= allowed_renderings(Decimal(rf.record.value_normalized), rf.record.unit)
    renderings |= allowed_renderings(Decimal(comp.result_value), comp.result_unit)
    records = [rf.record for rf in facts]
    ev = {
        "schema_version": SCHEMA_VERSION,
        "question_verbatim": question,
        "interpreted_question": {
            "restatement": rq.restatement,
            "structured_query": p.to_json(),
        },
        "facts_used": [_fact_entry(rf) for rf in facts],
        "calculation": {
            "operation": comp.operation,
            "steps": [{"n": s.n, "describe": s.describe, "value": s.value} for s in comp.steps],
            "result": {
                "value": comp.result_value,
                "unit": comp.result_unit,
                "formatted": comp.formatted,
            },
            "allowed_renderings": sorted(renderings),
        },
        "verification_status": _min_status(records),
        "caveats": _caveats(records, rq, comp),
    }
    if comp.table:
        ev["calculation"]["table"] = list(comp.table)
    return ev


def build_refusal_evidence(question: str, p: Plan | None, refusal: Refusal) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "question_verbatim": question,
        "interpreted_question": {
            "restatement": "(refused before/at resolution)",
            "structured_query": p.to_json() if p else None,
        },
        "refusal": {
            "kind": refusal.kind.name,
            "reason": refusal.reason,
            "alternatives": list(refusal.alternatives),
        },
        "caveats": [],
    }


def build_conflict_evidence(question: str, p: Plan, rq: ResolvedQuery,
                            records: tuple[FactRecord, ...]) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "question_verbatim": question,
        "interpreted_question": {
            "restatement": rq.restatement,
            "structured_query": p.to_json(),
        },
        "facts_used": [_fact_entry(RetrievedFact(r, 0)) for r in records],
        "verification_status": "CONFLICTING",
        "caveats": [{"code": "CONFLICTING_SOURCES", "text": _CAVEAT_TEXT["CONFLICTING_SOURCES"]}],
    }


def _min_status(records: list[FactRecord]) -> str:
    # CONFLICTING dominates, then UNVERIFIED, then VERIFIED (§5.5)
    statuses = {r.verification_status for r in records}
    for s in ("CONFLICTING", "UNVERIFIED", "VERIFIED"):
        if s in statuses:
            return s
    return "UNVERIFIED"
