"""Rule-11 coverage for the query pipeline: every refusal gate rejects its
crafted bad input; the D3 query-time rider is pinned; provenance preference
and conflict handling proven against a real (temp) fact store."""

from datetime import date
from decimal import Decimal

import pytest

from sfi.concepts import dictionary as dictionary_mod
from sfi.query import resolve as resolve_mod
from sfi.query.compute import allowed_renderings, compute
from sfi.query.pipeline import Deps, answer
from sfi.query.retrieve import ConflictFound, RetrievedFacts, retrieve
from sfi.query.types import (
    Answered,
    FactRecord,
    Plan,
    PlanPeriod,
    Refusal,
    RefusalKind,
    Refused,
    ResolvedQuery,
    RetrievedFact,
    TypedPeriod,
)
from sfi.store import db

DICT = dictionary_mod.load()
TODAY = date(2026, 7, 13)
MANIFEST = {
    "companies": {
        "TSLA": {"cik": "0001318605", "name": "Tesla, Inc.", "fiscal_year_end_mmdd": "--12-31"},
        "AAPL": {"cik": "0000320193", "name": "Apple Inc.", "fiscal_year_end_mmdd": "--09-26"},
    },
    "filings": [],
}


def mk_plan(**kw) -> Plan:
    base = dict(
        intent="numeric", company_text="Tesla", company="TSLA",
        concept_text="revenue", concept="revenue", operation="value",
        periods_text="", periods=(), narrative_topic=None, notes="",
    )
    base.update(kw)
    return Plan(**base)


class FakeReader:
    """held_periods-only reader for resolve tests."""

    def __init__(self, held):
        self._held = held  # list of dicts

    def held_periods(self, ticker, concept, duration_types=None):
        return self._held

    def lookup(self, *a, **k):
        return []


TSLA_HELD = [
    {"fiscal_year": 2026, "fiscal_period": "Q1", "duration_type": "QUARTER", "period_end": "2026-03-31"},
    {"fiscal_year": 2025, "fiscal_period": "FY", "duration_type": "FISCAL_YEAR", "period_end": "2025-12-31"},
    {"fiscal_year": 2025, "fiscal_period": "Q1", "duration_type": "QUARTER", "period_end": "2025-03-31"},
    {"fiscal_year": 2024, "fiscal_period": "FY", "duration_type": "FISCAL_YEAR", "period_end": "2024-12-31"},
    {"fiscal_year": 2023, "fiscal_period": "FY", "duration_type": "FISCAL_YEAR", "period_end": "2023-12-31"},
]


def _resolve(plan, held=TSLA_HELD):
    return resolve_mod.resolve(plan, MANIFEST, DICT, FakeReader(held), TODAY)


# ------------------------------------------------------------ resolve gates


def test_narrative_refused():
    r = _resolve(mk_plan(intent="narrative", narrative_topic="risks"))
    assert isinstance(r, Refusal) and r.kind == RefusalKind.NARRATIVE_NOT_SUPPORTED


def test_unparseable_refused():
    r = _resolve(mk_plan(intent="other"))
    assert isinstance(r, Refusal) and r.kind == RefusalKind.UNPARSEABLE_QUESTION


def test_out_of_corpus_refused():
    r = _resolve(mk_plan(company="OTHER", company_text="Microsoft"))
    assert isinstance(r, Refusal) and r.kind == RefusalKind.OUT_OF_CORPUS
    assert "Microsoft" in r.reason


def test_concept_not_supported_refused():
    r = _resolve(mk_plan(concept="OTHER", concept_text="AWS revenue"))
    assert isinstance(r, Refusal) and r.kind == RefusalKind.CONCEPT_NOT_SUPPORTED


def test_not_filed_yet_offers_nearest_alternative():
    # "net income growth between 2025 and 2026" — FY2026 unfiled in July 2026.
    plan = mk_plan(
        concept="net_income", operation="growth",
        periods=(PlanPeriod(2026, "FY"), PlanPeriod(2025, "FY")),
    )
    r = _resolve(plan)
    assert isinstance(r, Refusal) and r.kind == RefusalKind.NOT_FILED_YET
    assert r.alternatives and "answerable" in r.alternatives[0]


def test_past_uncovered_period_is_period_not_held():
    r = _resolve(mk_plan(periods=(PlanPeriod(2022, "FY"),)))
    assert isinstance(r, Refusal) and r.kind == RefusalKind.PERIOD_NOT_HELD


def test_rank_deltas_targets_balance_statement():
    plan = mk_plan(
        intent="rank_changes", operation="rank_deltas",
        concept="OTHER", concept_text="balance sheet changes",
        periods=(PlanPeriod(2026, "Q1"), PlanPeriod(2025, "FY")),
    )
    held = [
        {"fiscal_year": 2026, "fiscal_period": "Q1", "duration_type": "INSTANT", "period_end": "2026-03-31"},
        {"fiscal_year": 2025, "fiscal_period": "FY", "duration_type": "INSTANT", "period_end": "2025-12-31"},
    ]
    rq = _resolve(plan, held)
    assert isinstance(rq, ResolvedQuery)
    assert all(DICT.entries[c].statement == "BALANCE" for c in rq.concepts)


def test_derived_margin_expands_components():
    rq = _resolve(mk_plan(concept="DERIVED_OPERATING_MARGIN", operation="margin",
                          periods=(PlanPeriod(2025, "FY"),)))
    assert isinstance(rq, ResolvedQuery)
    assert rq.concepts == ("operating_income", "revenue") and rq.operation == "margin"


# ----------------------------------------------------------------- compute


def mk_record(concept="revenue", fy=2026, fp="Q1", duration="QUARTER",
              value="22387000000", unit="USD", statement="INCOME",
              form="10-Q", start="2026-01-01", end="2026-03-31",
              raw="22,387", fact_id=1):
    return FactRecord(
        fact_id=fact_id, ticker="TSLA", concept=concept, raw_label="Total revenues",
        match_method="dictionary_exact", statement_type=statement,
        accession_no=f"acc-{fact_id}", form_type=form, filing_date="2026-04-23",
        page=6, period_start=start, period_end=end, duration_type=duration,
        fiscal_year=fy, fiscal_period=fp, value_raw=raw, value_normalized=value,
        unit=unit, scale=1_000_000, verification_status="UNVERIFIED",
        filing_period_end=end,
    )


def _rq(operation, concepts=("revenue",), periods=None):
    periods = periods or (TypedPeriod(2026, "Q1"), TypedPeriod(2025, "Q1"))
    return ResolvedQuery("TSLA", concepts, operation, tuple(periods), restatement="t")


def test_cross_duration_refused():
    # rule 11: FY-vs-Q arithmetic is a type error.
    facts = {
        ("revenue", TypedPeriod(2025, "FY")): RetrievedFact(
            mk_record(fy=2025, fp="FY", duration="FISCAL_YEAR", value="94827000000",
                      start="2025-01-01", end="2025-12-31", fact_id=2), 0),
        ("revenue", TypedPeriod(2026, "Q1")): RetrievedFact(mk_record(), 0),
    }
    rq = _rq("growth", periods=(TypedPeriod(2026, "Q1"), TypedPeriod(2025, "FY")))
    r = compute(rq, facts)
    assert isinstance(r, Refusal) and r.kind == RefusalKind.CROSS_DURATION


def test_d3_rider_quarter_vs_ytd_cashflow_compatible():
    # DEVIATIONS.md D3 query rider: fy-start QUARTER == YTD span for CASHFLOW.
    facts = {
        ("operating_cash_flow", TypedPeriod(2026, "Q1")): RetrievedFact(
            mk_record(concept="operating_cash_flow", statement="CASHFLOW",
                      duration="QUARTER", value="3937000000", fact_id=3), 0),
        ("operating_cash_flow", TypedPeriod(2025, "Q1")): RetrievedFact(
            mk_record(concept="operating_cash_flow", statement="CASHFLOW",
                      duration="YTD", fy=2025, value="2156000000",
                      start="2025-01-01", end="2025-03-31", fact_id=4), 0),
    }
    rq = _rq("growth", concepts=("operating_cash_flow",))
    comp = compute(rq, facts)
    assert not isinstance(comp, Refusal)
    assert comp.result_value.startswith("0.826")  # (3937-2156)/2156


def test_growth_sign_convention_flagged():
    facts = {
        ("net_income", TypedPeriod(2026, "Q1")): RetrievedFact(
            mk_record(concept="net_income", value="500000000", fact_id=5), 0),
        ("net_income", TypedPeriod(2025, "Q1")): RetrievedFact(
            mk_record(concept="net_income", fy=2025, value="-1000000000",
                      start="2025-01-01", end="2025-03-31", fact_id=6), 0),
    }
    comp = compute(_rq("growth", concepts=("net_income",)), facts)
    assert comp.sign_convention is True
    assert Decimal(comp.result_value) == Decimal("1.5")  # (500-(-1000))/|-1000|


def test_margin_zero_denominator_refused():
    facts = {
        ("operating_income", TypedPeriod(2026, "Q1")): RetrievedFact(
            mk_record(concept="operating_income", value="941000000", fact_id=7), 0),
        ("revenue", TypedPeriod(2026, "Q1")): RetrievedFact(
            mk_record(value="0", fact_id=8), 0),
    }
    rq = _rq("margin", concepts=("operating_income", "revenue"),
             periods=(TypedPeriod(2026, "Q1"),))
    r = compute(rq, facts)
    assert isinstance(r, Refusal) and "zero" in r.reason


def test_allowed_renderings_whitelist():
    r = allowed_renderings(Decimal("-0.0922961"), "ratio")
    assert "-9.2%" in r and "-9.23%" in r
    usd = allowed_renderings(Decimal("19335000000"), "USD")
    assert "$19,335 million" in usd and "$19.3 billion" in usd
    assert "$19,336 million" not in usd  # nothing off-by-one sneaks in


# -------------------------------------------------- retrieve on a real store


@pytest.fixture()
def store(tmp_path):
    path = tmp_path / "facts.sqlite"
    db.init_db(path)
    con = db.connect(path)
    con.executescript(
        """
        INSERT INTO filings VALUES
          ('acc-q26','TSLA','1','10-Q','2026-04-23','2026-03-31',2026,'Q1',NULL,'p.pdf',NULL),
          ('acc-q25','TSLA','1','10-Q','2025-04-23','2025-03-31',2025,'Q1',NULL,'p.pdf',NULL);
        INSERT INTO statements (id, accession_no, statement_type, page_start, page_end,
          anchor_text, parse_status) VALUES
          (1,'acc-q26','INCOME',6,6,'x','ACCEPTED'),
          (2,'acc-q25','INCOME',6,6,'x','ACCEPTED');
        """
    )
    con.commit()
    yield con
    con.close()


def _insert_fact(con, statement_id, acc, fy, fp, end, value, concept="revenue",
                 duration="QUARTER", start=None):
    con.execute(
        "INSERT INTO facts (statement_id, accession_no, ticker, statement_type,"
        " concept, match_method, raw_label, row_index, page, period_start,"
        " period_end, duration_type, fiscal_year, fiscal_period, value_raw,"
        " value_normalized, unit, scale) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (statement_id, acc, "TSLA", "INCOME", concept, "dictionary_exact",
         "Total revenues", 1, 6, start or end[:4] + "-01-01", end, duration,
         fy, fp, value, value, "USD", 1_000_000),
    )
    con.commit()


def test_preferred_provenance_and_corroboration(store):
    # Q1 FY2025 printed twice: own 10-Q + comparative column of the 2026 10-Q.
    _insert_fact(store, 2, "acc-q25", 2025, "Q1", "2025-03-31", "19335000000")
    _insert_fact(store, 1, "acc-q26", 2025, "Q1", "2025-03-31", "19335000000")
    reader = db.FactReader(store)
    rq = ResolvedQuery("TSLA", ("revenue",), "value",
                       (TypedPeriod(2025, "Q1"),), restatement="t")
    out = retrieve(rq, reader, DICT)
    assert isinstance(out, RetrievedFacts)
    rf = out.facts[("revenue", TypedPeriod(2025, "Q1"))]
    assert rf.record.accession_no == "acc-q25"  # own-report beats comparative
    assert rf.corroborating == 1


def test_disagreeing_provenance_is_conflict(store):
    # rule 11: disagreement must never be silently averaged or preferred.
    _insert_fact(store, 2, "acc-q25", 2025, "Q1", "2025-03-31", "19335000000")
    _insert_fact(store, 1, "acc-q26", 2025, "Q1", "2025-03-31", "19999000000")
    reader = db.FactReader(store)
    rq = ResolvedQuery("TSLA", ("revenue",), "value",
                       (TypedPeriod(2025, "Q1"),), restatement="t")
    out = retrieve(rq, reader, DICT)
    assert isinstance(out, ConflictFound) and len(out.records) == 2


def test_missing_fact_is_period_not_held(store):
    reader = db.FactReader(store)
    rq = ResolvedQuery("TSLA", ("revenue",), "value",
                       (TypedPeriod(2024, "Q1"),), restatement="t")
    out = retrieve(rq, reader, DICT)
    assert isinstance(out, Refusal) and out.kind == RefusalKind.PERIOD_NOT_HELD


# ----------------------------------------------------------- pipeline (e2e)


class FakeLLM:
    def __init__(self, plan_doc):
        self.plan_doc = plan_doc

    def structured(self, **kw):
        return self.plan_doc


def test_pipeline_growth_end_to_end(store):
    _insert_fact(store, 1, "acc-q26", 2026, "Q1", "2026-03-31", "22387000000")
    _insert_fact(store, 2, "acc-q25", 2025, "Q1", "2025-03-31", "19335000000")
    plan_doc = {
        "intent": "numeric", "company_text": "Tesla", "company": "TSLA",
        "concept_text": "revenue", "concept": "revenue", "operation": "growth",
        "periods_text": "Q1 YoY",
        "periods": [
            {"fiscal_year": 2026, "fiscal_period": "Q1"},
            {"fiscal_year": 2025, "fiscal_period": "Q1"},
        ],
        "narrative_topic": None, "notes": "",
    }
    deps = Deps(reader=db.FactReader(store), dictionary=DICT,
                manifest=MANIFEST, llm=FakeLLM(plan_doc), today=TODAY)
    result = answer("What was Tesla's Q1 revenue change year-over-year?", deps)
    assert isinstance(result, Answered)
    ev = result.evidence
    assert ev["schema_version"] == 1
    assert ev["calculation"]["result"]["value"].startswith("0.157")  # +15.79%
    assert "15.8%" in ev["calculation"]["allowed_renderings"]
    assert {c["code"] for c in ev["caveats"]} >= {"UNAUDITED_INTERIM", "UNVERIFIED_FACT"}
    assert "Total revenues" in result.text and "Calculation:" in result.text


def test_pipeline_refusal_carries_echo(store):
    plan_doc = {
        "intent": "numeric", "company_text": "Microsoft", "company": "OTHER",
        "concept_text": "net income", "concept": "net_income", "operation": "value",
        "periods_text": "latest annual",
        "periods": [{"fiscal_year": None, "fiscal_period": "LATEST"}],
        "narrative_topic": None, "notes": "",
    }
    deps = Deps(reader=db.FactReader(store), dictionary=DICT,
                manifest=MANIFEST, llm=FakeLLM(plan_doc), today=TODAY)
    result = answer("What was Microsoft's net income in the latest annual filing?", deps)
    assert isinstance(result, Refused)
    assert result.refusal.kind == RefusalKind.OUT_OF_CORPUS
    # the echo is always present — a refusal to a misread question is visibly
    # a refusal to the wrong question
    assert result.evidence["interpreted_question"]["structured_query"]["company_text"] == "Microsoft"
    assert "REFUSED (OUT_OF_CORPUS)" in result.text
