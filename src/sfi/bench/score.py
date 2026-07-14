"""Benchmark validation + scoring (§6.2) and failure classification (§6.3).
L3 — imports query public types + common. The scorer never generates or
repairs an expectation; suspected errors are flagged for Ben.
"""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation

from ..query.types import Answered, Conflict, Refusal, RefusalKind, Refused

VALID_BEHAVIORS = {"answer", "refuse", "candidates", "conflict"}
VALID_UNITS = {"USD", "USD_PER_SHARE", "ratio", None}
VALID_CATEGORIES = {
    "direct_lookup", "derived", "quarterly_yoy", "period_trap",
    "label_trap", "scale_trap", "should_refuse",
}
# derived expectations name the metric; the cited primary fact is the numerator
DERIVED_PRIMARY = {
    "gross_margin": "gross_profit",
    "operating_margin": "operating_income",
    "net_margin": "net_income",
}
_SCALE_FACTORS = {Decimal(1000), Decimal(1_000_000), Decimal(1_000_000_000)}


def validate(entries: list[dict], dictionary) -> list[str]:
    """Hard-fail checks before any scored run (the yaml header's contract)."""
    errors: list[str] = []
    seen_ids: set[str] = set()
    for i, entry in enumerate(entries):
        eid = entry.get("id", f"<entry {i}>")
        if "FILL_ME" in json.dumps(entry):
            errors.append(f"{eid}: surviving FILL_ME")
        if eid in seen_ids:
            errors.append(f"{eid}: duplicate id")
        seen_ids.add(eid)
        if entry.get("category") not in VALID_CATEGORIES:
            errors.append(f"{eid}: bad category {entry.get('category')!r}")
        expect = entry.get("expect") or {}
        behavior = expect.get("behavior")
        if behavior not in VALID_BEHAVIORS:
            errors.append(f"{eid}: bad behavior {behavior!r}")
            continue
        if behavior == "answer":
            if expect.get("value") is None:
                errors.append(f"{eid}: answer entry with null value")
            if expect.get("unit") not in VALID_UNITS or expect.get("unit") is None:
                errors.append(f"{eid}: bad unit {expect.get('unit')!r}")
            concept = expect.get("concept")
            if concept not in dictionary.entries and concept not in DERIVED_PRIMARY:
                errors.append(f"{eid}: unknown concept {concept!r}")
            period = expect.get("period") or {}
            if not isinstance(period.get("fiscal_year"), int) or period.get(
                "fiscal_period"
            ) not in ("FY", "Q1", "Q2", "Q3"):
                errors.append(f"{eid}: bad period {period!r}")
            citation = expect.get("citation") or {}
            for key in ("company", "form_type", "page", "raw_label"):
                if not citation.get(key):
                    errors.append(f"{eid}: citation missing {key}")
            try:
                Decimal(str(expect.get("value")))
            except InvalidOperation:
                errors.append(f"{eid}: value is not a decimal: {expect.get('value')!r}")
        else:
            kind = expect.get("refusal_kind")
            if behavior == "refuse" and (kind is None or kind not in RefusalKind.__members__):
                errors.append(f"{eid}: bad refusal_kind {kind!r}")
            if expect.get("value") is not None:
                errors.append(f"{eid}: non-answer entry carries a value")
    return errors


def _expected_period_label(period: dict) -> str:
    fy, fp = period["fiscal_year"], period["fiscal_period"]
    return f"FY{fy}" if fp == "FY" else f"{fp} FY{fy}"


def score_entry(entry: dict, result) -> dict:
    expect = entry["expect"]
    out = {
        "id": entry["id"],
        "category": entry["category"],
        "question": entry["question"],
        "passed": False,
        "failure_class": None,
        "detail": "",
    }

    if expect["behavior"] == "refuse":
        if isinstance(result, (Answered, Conflict)):
            out["failure_class"] = "MISSED_REFUSAL"
            out["detail"] = "answered a should-refuse question"
            return out
        assert isinstance(result, Refused)
        got_kind = result.refusal.kind.name
        if got_kind == expect["refusal_kind"]:
            out["passed"] = True
            out["detail"] = f"refused {got_kind}"
        else:
            out["failure_class"] = "NEEDS_REVIEW"
            out["detail"] = (
                f"refused for the wrong reason: {got_kind} != {expect['refusal_kind']}"
            )
        return out

    # behavior: answer
    if isinstance(result, Refused):
        out["failure_class"] = "SPURIOUS_REFUSAL"
        out["detail"] = f"{result.refusal.kind.name}: {result.refusal.reason}"
        return out
    if isinstance(result, Conflict):
        out["failure_class"] = "NEEDS_REVIEW"
        out["detail"] = "conflict returned where an answer was expected"
        return out
    assert isinstance(result, Answered)
    ev = result.evidence

    expected_value = Decimal(str(expect["value"]))
    got_value = Decimal(ev["calculation"]["result"]["value"])
    value_ok = got_value == expected_value

    primary = ev["facts_used"][0]
    citation = expect["citation"]
    expected_concept = DERIVED_PRIMARY.get(expect["concept"], expect["concept"])
    concept_ok = primary["concept"] == expected_concept
    label_ok = primary["raw_label"] == citation["raw_label"]
    period_ok = primary["period"]["fiscal_label"] == _expected_period_label(expect["period"])
    citation_ok = (
        primary["filing"]["form_type"] == citation["form_type"]
        and primary["page"] == citation["page"]
        and primary["company"] == citation["company"]
    )

    if value_ok and concept_ok and label_ok and period_ok and citation_ok:
        out["passed"] = True
        out["detail"] = f"value {got_value} on {primary['raw_label']!r} p.{primary['page']}"
        return out

    # §6.3 auto-suggested classification from the field-diff pattern
    diffs = []
    if not value_ok:
        diffs.append(f"value {got_value} != {expected_value}")
    if not label_ok:
        diffs.append(f"label {primary['raw_label']!r} != {citation['raw_label']!r}")
    if not period_ok:
        diffs.append(f"period {primary['period']['fiscal_label']}")
    if not concept_ok:
        diffs.append(f"concept {primary['concept']}")
    if not citation_ok:
        diffs.append(
            f"citation {primary['filing']['form_type']} p.{primary['page']}"
        )
    out["detail"] = "; ".join(diffs)

    if not value_ok and label_ok and period_ok:
        ratio = None
        if expected_value != 0 and got_value != 0:
            q = got_value / expected_value
            ratio = q if q >= 1 else 1 / q
        if ratio is not None and ratio in _SCALE_FACTORS:
            out["failure_class"] = "EXTRACTION_WRONG_SCALE"
        else:
            out["failure_class"] = "EXTRACTION_WRONG_VALUE"
    elif value_ok and not period_ok:
        out["failure_class"] = "PERIOD_RESOLUTION"
    elif not label_ok or not concept_ok:
        out["failure_class"] = "EXTRACTION_WRONG_ROW"
    elif value_ok and label_ok and period_ok and not citation_ok:
        out["failure_class"] = "WRONG_CITATION"
    else:
        out["failure_class"] = "NEEDS_REVIEW"
    return out
