"""Benchmark runner (§6.2): every entry goes through query.pipeline.answer —
the same public entry point as the CLI; no bench-only side doors. Output:
benchmark/reports/run-{timestamp}.json (committed) + a printed table."""

from __future__ import annotations

import json
from collections import Counter
from datetime import date, datetime, timezone

import yaml

from ..common import config
from ..concepts import dictionary as dictionary_mod
from ..query.pipeline import Deps, answer
from ..store import db
from .score import DERIVED_PRIMARY, score_entry, validate

BENCHMARK_PATH = config.BENCH_DIR / "benchmark.yaml"
REPORTS_DIR = config.BENCH_DIR / "reports"


def load_entries() -> list[dict]:
    return yaml.safe_load(BENCHMARK_PATH.read_text())


def cmd_validate() -> int:
    dictionary = dictionary_mod.load()
    errors = validate(load_entries(), dictionary)
    if errors:
        for e in errors:
            print(f"INVALID  {e}")
        return 2
    entries = load_entries()
    counts = Counter(e["category"] for e in entries)
    print(f"benchmark.yaml OK: {len(entries)} entries, "
          + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return 0


def _retrieval_ok(con, entry, dictionary) -> bool | None:
    """§6.2 retrieval-vs-answer divergence: was the RIGHT statement located
    and ACCEPTED, independently of the final answer? None for refusals."""
    expect = entry["expect"]
    if expect["behavior"] != "answer":
        return None
    concept = DERIVED_PRIMARY.get(expect["concept"], expect["concept"])
    statement_type = dictionary.entries[concept].statement
    citation = expect["citation"]
    period = expect["period"]
    fp = period["fiscal_period"] if citation["form_type"] == "10-Q" else "FY"
    row = con.execute(
        "SELECT s.parse_status, s.page_start, s.page_end FROM statements s"
        " JOIN filings f ON f.accession_no = s.accession_no"
        " WHERE f.ticker = ? AND f.form_type = ? AND f.fiscal_year = ?"
        " AND f.fiscal_period = ? AND s.statement_type = ?",
        (citation["company"], citation["form_type"], period["fiscal_year"],
         fp, statement_type),
    ).fetchone()
    if row is None:
        return False
    return row[0] == "ACCEPTED" and row[1] <= citation["page"] <= row[2]


def cmd_run() -> int:
    entries = load_entries()
    dictionary = dictionary_mod.load()
    errors = validate(entries, dictionary)
    if errors:
        for e in errors:
            print(f"INVALID  {e}")
        return 2

    manifest = json.loads(config.MANIFEST_PATH.read_text())
    from ..llm.client import LLMClient

    con = db.connect()
    deps = Deps(
        reader=db.FactReader(con),
        dictionary=dictionary,
        manifest=manifest,
        llm=LLMClient(),
        today=date.today(),
    )

    scored: list[dict] = []
    for entry in entries:
        result = answer(entry["question"], deps)
        s = score_entry(entry, result)
        s["retrieval_ok"] = _retrieval_ok(con, entry, dictionary)
        scored.append(s)
        mark = "PASS" if s["passed"] else f"FAIL {s['failure_class']}"
        print(f"{s['id']}  {s['category']:<14} {mark:<28} {s['detail'][:90]}")

    by_category: dict[str, list[dict]] = {}
    for s in scored:
        by_category.setdefault(s["category"], []).append(s)
    print("\nper-category:")
    for category in sorted(by_category):
        group = by_category[category]
        passed = sum(1 for s in group if s["passed"])
        print(f"  {category:<14} {passed}/{len(group)}")
    total_passed = sum(1 for s in scored if s["passed"])
    divergent = [
        s["id"] for s in scored
        if not s["passed"] and s.get("retrieval_ok") is True
    ]
    print(f"\nTOTAL {total_passed}/{len(scored)} passed")
    if divergent:
        print(f"retrieval-vs-answer divergence (right statement parsed, wrong answer): {divergent}")

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = REPORTS_DIR / f"run-{stamp}.json"
    report_path.write_text(json.dumps(
        {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "total": len(scored),
            "passed": total_passed,
            "per_category": {
                c: {"passed": sum(1 for s in g if s["passed"]), "total": len(g)}
                for c, g in by_category.items()
            },
            "entries": scored,
        },
        indent=2,
    ) + "\n")
    print(f"report -> {report_path}")
    return 0
