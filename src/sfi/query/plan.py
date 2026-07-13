"""Planner (§5.1): one LLM call, schema §3.5 forced, NO gating logic.

The Plan lands verbatim in the evidence echo — the sole guard on the one LLM
step with no deterministic test behind it (ARCHITECTURE weakness #4). Every
gate lives in resolve.py, so a planner hallucination can misread a question
(visible in the echo) but cannot invent an answerable one.
"""

from __future__ import annotations

from datetime import date

from .types import Plan

PLANNER_VERSION = "p0.6-v1"

DERIVED_CONCEPTS = ("DERIVED_GROSS_MARGIN", "DERIVED_OPERATING_MARGIN", "DERIVED_NET_MARGIN")

_SYSTEM_TEMPLATE = """You convert one natural-language question about SEC filings into a structured
query. You do not answer questions, compute, or judge answerability. Extract exactly
what was asked, using ONLY the enum values provided. If the company or metric is not
in the enums, use OTHER. If a year could be calendar or fiscal, treat it as fiscal and
say so in notes. Today's date is {today}.
Known corpus:
{corpus}
Concept glossary:
{glossary}"""


def planner_schema(dictionary) -> dict:
    concept_enum = list(dictionary.concept_ids()) + list(DERIVED_CONCEPTS) + ["OTHER", "NONE"]
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "intent", "company_text", "company", "concept_text", "concept",
            "operation", "periods_text", "periods", "narrative_topic", "notes",
        ],
        "properties": {
            "intent": {"enum": ["numeric", "rank_changes", "narrative", "other"]},
            "company_text": {"type": "string"},
            "company": {"enum": ["TSLA", "AAPL", "OTHER", "NONE"]},
            "concept_text": {"type": "string"},
            "concept": {"enum": concept_enum},
            "operation": {"enum": ["value", "growth", "delta", "margin", "rank_deltas"]},
            "periods_text": {"type": "string"},
            # §3.5 says maxItems 2, but the structured-outputs API rejects
            # array constraints — the <=2 rule is enforced in resolve.py
            # (code beats schema for a guard anyway).
            "periods": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["fiscal_year", "fiscal_period"],
                    "properties": {
                        "fiscal_year": {"type": ["integer", "null"]},
                        "fiscal_period": {"enum": ["FY", "Q1", "Q2", "Q3", "LATEST"]},
                    },
                },
            },
            "narrative_topic": {"type": ["string", "null"]},
            "notes": {"type": "string"},
        },
    }


def corpus_summary(manifest: dict) -> str:
    lines = []
    for ticker in sorted(manifest["companies"]):
        parts = []
        for f in manifest["filings"]:
            if f["ticker"] != ticker:
                continue
            label = (
                f"FY{f['fiscal_year']}"
                if f["fiscal_period"] == "FY"
                else f"{f['fiscal_period']} FY{f['fiscal_year']}"
            )
            suffix = " (amendment, no statements)" if f["is_amendment"] else ""
            parts.append(f"{f['form_type']} {label}{suffix}")
        lines.append(f"  {ticker}: " + "; ".join(parts))
    return "\n".join(lines)


def glossary(dictionary) -> str:
    lines = [
        f"  {cid}: {dictionary.entries[cid].description}"
        for cid in dictionary.concept_ids()
    ]
    lines += [
        "  DERIVED_GROSS_MARGIN: gross profit / revenue",
        "  DERIVED_OPERATING_MARGIN: operating income / revenue",
        "  DERIVED_NET_MARGIN: net income / revenue",
    ]
    return "\n".join(lines)


def plan(question: str, dictionary, manifest: dict, llm, today: date) -> Plan:
    system = _SYSTEM_TEMPLATE.format(
        today=today.isoformat(),
        corpus=corpus_summary(manifest),
        glossary=glossary(dictionary),
    )
    doc = llm.structured(
        system=system,
        user=question,
        schema=planner_schema(dictionary),
        purpose="plan",
        max_tokens=2000,
    )
    return Plan.from_json(doc)
