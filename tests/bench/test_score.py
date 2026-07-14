"""Rule-11 coverage for the benchmark scorer: crafted wrong answers must be
REJECTED with the §6.3 class that names the leaking guard."""

import copy

from sfi.bench.score import score_entry, validate
from sfi.concepts import dictionary as dictionary_mod
from sfi.query.types import Answered, Refusal, RefusalKind, Refused

DICT = dictionary_mod.load()

ENTRY = {
    "id": "T01",
    "category": "direct_lookup",
    "question": "What was Tesla's net income for fiscal 2025?",
    "expect": {
        "behavior": "answer",
        "value": 3855000000,
        "unit": "USD",
        "concept": "net_income",
        "period": {"fiscal_year": 2025, "fiscal_period": "FY"},
        "citation": {
            "company": "TSLA", "form_type": "10-K", "page": 82,
            "raw_label": "Net income", "value_as_printed": "3,855",
        },
        "refusal_kind": None,
    },
    "notes": "",
}

REFUSE_ENTRY = {
    "id": "T02",
    "category": "should_refuse",
    "question": "What was Microsoft's net income?",
    "expect": {
        "behavior": "refuse", "value": None, "unit": None, "concept": None,
        "period": {"fiscal_year": None, "fiscal_period": None},
        "citation": {"company": "MSFT", "form_type": None, "page": None,
                     "raw_label": None, "value_as_printed": None},
        "refusal_kind": "OUT_OF_CORPUS",
    },
    "notes": "",
}


def answered(value="3855000000", label="Net income", fiscal_label="FY2025",
             form="10-K", page=82, concept="net_income"):
    ev = {
        "schema_version": 1,
        "interpreted_question": {"restatement": "r", "structured_query": {}},
        "facts_used": [{
            "fact_id": 1, "company": "TSLA", "concept": concept,
            "raw_label": label, "match_method": "dictionary_exact",
            "filing": {"form_type": form, "accession_no": "a", "filing_date": "d"},
            "statement": "INCOME", "page": page,
            "period": {"start": None, "end": "2025-12-31",
                       "duration_type": "FISCAL_YEAR", "fiscal_label": fiscal_label},
            "value_raw": "3,855", "value_normalized": value, "unit": "USD",
            "scale": 1000000, "verification_status": "UNVERIFIED",
        }],
        "calculation": {"operation": "value", "steps": [],
                        "result": {"value": value, "unit": "USD", "formatted": "x"},
                        "allowed_renderings": []},
        "verification_status": "UNVERIFIED",
        "caveats": [],
    }
    return Answered(ev, "text")


def refused(kind=RefusalKind.OUT_OF_CORPUS):
    return Refused({"refusal": {}}, Refusal(kind, "reason"), "text")


def test_exact_match_passes():
    s = score_entry(ENTRY, answered())
    assert s["passed"] and s["failure_class"] is None


def test_wrong_value_same_row_is_extraction_wrong_value():
    s = score_entry(ENTRY, answered(value="3856000000"))
    assert not s["passed"] and s["failure_class"] == "EXTRACTION_WRONG_VALUE"


def test_value_off_by_1e6_is_scale_class():
    s = score_entry(ENTRY, answered(value="3855"))
    assert not s["passed"] and s["failure_class"] == "EXTRACTION_WRONG_SCALE"


def test_right_value_wrong_row_fails_as_wrong_row():
    s = score_entry(ENTRY, answered(
        label="Net income attributable to common stockholders",
        concept="net_income_attributable_common",
    ))
    assert not s["passed"] and s["failure_class"] == "EXTRACTION_WRONG_ROW"


def test_wrong_period_is_period_resolution():
    s = score_entry(ENTRY, answered(fiscal_label="FY2024"))
    assert not s["passed"] and s["failure_class"] == "PERIOD_RESOLUTION"


def test_right_answer_wrong_citation_fails():
    s = score_entry(ENTRY, answered(page=99))
    assert not s["passed"] and s["failure_class"] == "WRONG_CITATION"


def test_refusing_an_answerable_question_is_spurious():
    s = score_entry(ENTRY, refused(RefusalKind.PERIOD_NOT_HELD))
    assert not s["passed"] and s["failure_class"] == "SPURIOUS_REFUSAL"


def test_answering_a_should_refuse_is_missed_refusal():
    s = score_entry(REFUSE_ENTRY, answered())
    assert not s["passed"] and s["failure_class"] == "MISSED_REFUSAL"


def test_refusing_for_the_wrong_reason_fails():
    s = score_entry(REFUSE_ENTRY, refused(RefusalKind.CONCEPT_NOT_SUPPORTED))
    assert not s["passed"]


def test_expected_refusal_kind_passes():
    s = score_entry(REFUSE_ENTRY, refused(RefusalKind.OUT_OF_CORPUS))
    assert s["passed"]


# ------------------------------------------------------------- validator


def test_validator_accepts_the_real_file():
    import yaml

    from sfi.common import config

    entries = yaml.safe_load((config.BENCH_DIR / "benchmark.yaml").read_text())
    assert validate(entries, DICT) == []
    assert len(entries) == 25


def test_validator_rejects_fill_me_and_bad_fields():
    bad = copy.deepcopy(ENTRY)
    bad["expect"]["citation"]["raw_label"] = "FILL_ME"
    errors = validate([bad], DICT)
    assert any("FILL_ME" in e for e in errors)

    bad2 = copy.deepcopy(ENTRY)
    bad2["expect"]["concept"] = "ebitda"
    assert any("unknown concept" in e for e in validate([bad2], DICT))

    bad3 = copy.deepcopy(REFUSE_ENTRY)
    bad3["expect"]["refusal_kind"] = "NOT_A_KIND"
    assert any("refusal_kind" in e for e in validate([bad3], DICT))

    dupes = [copy.deepcopy(ENTRY), copy.deepcopy(ENTRY)]
    assert any("duplicate id" in e for e in validate(dupes, DICT))
