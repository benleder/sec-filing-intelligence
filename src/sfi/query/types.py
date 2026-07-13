"""Query-side types (§5). Every refusal is a value, not an exception."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto


class RefusalKind(Enum):
    OUT_OF_CORPUS = auto()
    NOT_FILED_YET = auto()
    CONCEPT_NOT_SUPPORTED = auto()
    PERIOD_NOT_HELD = auto()
    AMBIGUOUS_CONCEPT = auto()  # P1
    CROSS_DURATION = auto()
    NARRATIVE_NOT_SUPPORTED = auto()  # P0 only; retired by P1.5
    UNPARSEABLE_QUESTION = auto()


@dataclass(frozen=True)
class Refusal:
    kind: RefusalKind
    reason: str  # printed to the user, always with the "why"
    alternatives: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlanPeriod:
    fiscal_year: int | None  # None = "latest"
    fiscal_period: str  # 'FY' | 'Q1' | 'Q2' | 'Q3' | 'LATEST'


@dataclass(frozen=True)
class Plan:
    """The planner's structured query (§3.5) — extraction only, no gating."""

    intent: str
    company_text: str
    company: str
    concept_text: str
    concept: str
    operation: str
    periods_text: str
    periods: tuple[PlanPeriod, ...]
    narrative_topic: str | None
    notes: str

    @classmethod
    def from_json(cls, doc: dict) -> "Plan":
        return cls(
            intent=doc["intent"],
            company_text=doc["company_text"],
            company=doc["company"],
            concept_text=doc["concept_text"],
            concept=doc["concept"],
            operation=doc["operation"],
            periods_text=doc["periods_text"],
            periods=tuple(
                PlanPeriod(p["fiscal_year"], p["fiscal_period"]) for p in doc["periods"]
            ),
            narrative_topic=doc.get("narrative_topic"),
            notes=doc["notes"],
        )

    def to_json(self) -> dict:
        return {
            "intent": self.intent,
            "company_text": self.company_text,
            "company": self.company,
            "concept_text": self.concept_text,
            "concept": self.concept,
            "operation": self.operation,
            "periods_text": self.periods_text,
            "periods": [
                {"fiscal_year": p.fiscal_year, "fiscal_period": p.fiscal_period}
                for p in self.periods
            ],
            "narrative_topic": self.narrative_topic,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class TypedPeriod:
    fiscal_year: int
    fiscal_period: str  # 'FY' | 'Q1' | 'Q2' | 'Q3'

    def label(self) -> str:
        return f"FY{self.fiscal_year}" if self.fiscal_period == "FY" else (
            f"{self.fiscal_period} FY{self.fiscal_year}"
        )


@dataclass(frozen=True)
class ResolvedQuery:
    ticker: str
    concepts: tuple[str, ...]  # dictionary ids, expansion done (§5.2)
    operation: str  # 'value' | 'growth' | 'delta' | 'margin' | 'rank_deltas'
    periods: tuple[TypedPeriod, ...]  # newest first
    derived: str | None = None  # 'gross_margin' | 'operating_margin' | 'net_margin'
    alias_interpreted: bool = False  # a year/period alias was resolved (caveat)
    restatement: str = ""


def duration_family(statement: str, fiscal_period: str) -> tuple[str, ...]:
    """Which stored duration_types satisfy a (statement, fiscal_period) ask.
    CASHFLOW quarters accept YTD too — D3 query-time rider (DEVIATIONS.md):
    a fiscal-year-start QUARTER cash-flow fact and a YTD fact are the same
    kind of span, so neither may cause a false refusal."""
    if statement == "BALANCE":
        return ("INSTANT",)
    if fiscal_period == "FY":
        return ("FISCAL_YEAR",)
    if statement == "CASHFLOW":
        return ("QUARTER", "YTD")
    return ("QUARTER",)


@dataclass(frozen=True)
class FactRecord:
    fact_id: int
    ticker: str
    concept: str | None
    raw_label: str
    match_method: str | None
    statement_type: str
    accession_no: str
    form_type: str
    filing_date: str
    page: int
    period_start: str | None
    period_end: str
    duration_type: str
    fiscal_year: int
    fiscal_period: str
    value_raw: str
    value_normalized: str
    unit: str
    scale: int
    verification_status: str
    filing_period_end: str  # the source filing's own report period

    @classmethod
    def from_row(cls, row) -> "FactRecord":
        return cls(
            fact_id=row["id"], ticker=row["ticker"], concept=row["concept"],
            raw_label=row["raw_label"], match_method=row["match_method"],
            statement_type=row["statement_type"], accession_no=row["accession_no"],
            form_type=row["form_type"], filing_date=row["filing_date"],
            page=row["page"], period_start=row["period_start"],
            period_end=row["period_end"], duration_type=row["duration_type"],
            fiscal_year=row["fiscal_year"], fiscal_period=row["fiscal_period"],
            value_raw=row["value_raw"], value_normalized=row["value_normalized"],
            unit=row["unit"], scale=row["scale"],
            verification_status=row["verification_status"],
            filing_period_end=row["filing_period_end"],
        )


@dataclass(frozen=True)
class RetrievedFact:
    record: FactRecord
    corroborating: int  # additional agreeing provenance rows (§5.3)


@dataclass(frozen=True)
class Step:
    n: int
    describe: str
    value: str


@dataclass(frozen=True)
class Computation:
    operation: str
    steps: tuple[Step, ...]
    result_value: str
    result_unit: str  # 'USD' | 'USD_PER_SHARE' | 'ratio' | 'pp'
    formatted: str
    sign_convention: bool = False  # growth with negative base (caveat)
    table: tuple[dict, ...] = ()  # rank_deltas only


@dataclass(frozen=True)
class Answered:
    evidence: dict
    text: str


@dataclass(frozen=True)
class Refused:
    evidence: dict
    refusal: Refusal
    text: str = ""


@dataclass(frozen=True)
class Conflict:
    evidence: dict
    facts: tuple[FactRecord, ...]
    text: str = ""


AnswerResult = Answered | Refused | Conflict
