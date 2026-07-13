"""answer(question) orchestrator (§5.7): plan -> resolve -> retrieve ->
compute -> evidence -> compose. Any stage returning a Refusal short-circuits
into Refused with a reduced evidence object — the echo is always present."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from . import compose, evidence, plan as plan_mod, resolve as resolve_mod, retrieve as retrieve_mod
from .compute import compute
from .retrieve import ConflictFound, RetrievedFacts
from .types import Answered, AnswerResult, Conflict, Refusal, Refused


@dataclass(frozen=True)
class Deps:
    reader: object  # store.db.FactReader
    dictionary: object
    manifest: dict
    llm: object
    today: date


def answer(question: str, deps: Deps) -> AnswerResult:
    p = plan_mod.plan(question, deps.dictionary, deps.manifest, deps.llm, deps.today)

    resolved = resolve_mod.resolve(p, deps.manifest, deps.dictionary, deps.reader, deps.today)
    if isinstance(resolved, Refusal):
        ev = evidence.build_refusal_evidence(question, p, resolved)
        return Refused(ev, resolved, compose.render_template(ev))

    retrieved = retrieve_mod.retrieve(resolved, deps.reader, deps.dictionary)
    if isinstance(retrieved, Refusal):
        ev = evidence.build_refusal_evidence(question, p, retrieved)
        return Refused(ev, retrieved, compose.render_template(ev))
    if isinstance(retrieved, ConflictFound):
        ev = evidence.build_conflict_evidence(question, p, resolved, retrieved.records)
        return Conflict(ev, retrieved.records, compose.render_template(ev))

    assert isinstance(retrieved, RetrievedFacts)
    comp = compute(resolved, retrieved.facts)
    if isinstance(comp, Refusal):
        ev = evidence.build_refusal_evidence(question, p, comp)
        return Refused(ev, comp, compose.render_template(ev))

    used = _facts_in_use(resolved, retrieved)
    ev = evidence.build_evidence(question, p, resolved, used, comp)
    return Answered(ev, compose.render_template(ev))


def _facts_in_use(resolved, retrieved: RetrievedFacts) -> list:
    """Facts in a stable, presentation-friendly order (by concept order in
    the resolved query, then newest period first)."""
    out = []
    for concept in resolved.concepts:
        for period in resolved.periods:
            rf = retrieved.facts.get((concept, period))
            if rf is not None:
                out.append(rf)
    return out
