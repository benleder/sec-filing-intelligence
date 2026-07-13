"""M1 (rule 14): LLM arithmetic error rate on SEC-scale operands, measured in
THIS repo against Decimal ground truth. Full table -> notes/measurements.md
(gitignored scratch); headline + protocol -> committed MEASUREMENTS.md
(stop-2 rider 4).

Protocol:
- N problems, seeded RNG (reproducible), alternating growth and margin.
- growth: (B - A) / |A| with 5-7 digit millions-scale operands, ~1 in 4
  bases negative (the SIGN_CONVENTION case). margin: A / B, B > 0.
- One structured-output call per problem, no tools: the model is asked for
  the bare decimal to 6 significant digits.
- correct  := relative error < 1e-5 vs Decimal ground truth (allows honest
  last-digit rounding); gross error := relative error > 1e-3 (would survive
  any display rounding — the dangerous kind).
"""

from __future__ import annotations

import random
from datetime import date
from decimal import Context, Decimal, InvalidOperation

from ..common import config

N = 50
SEED = 42
_SIX = Context(prec=6)

_ANSWER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["answer"],
    "properties": {"answer": {"type": "string"}},
}

_SYSTEM = (
    "You are asked to do one arithmetic computation. Reply with only the "
    "final number as a plain decimal (no commas, no %, no words), rounded "
    "to 6 significant digits."
)


def _problems(n: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    problems = []
    for i in range(n):
        if i % 2 == 0:
            a = rng.randint(10_000, 9_999_999) * 1_000_000
            b = rng.randint(10_000, 9_999_999) * 1_000_000
            if rng.random() < 0.25:
                a = -a
            problems.append(
                {
                    "kind": "growth",
                    "prompt": f"Compute ({b} - {a}) / |{a}|.",
                    "truth": (Decimal(b) - Decimal(a)) / abs(Decimal(a)),
                }
            )
        else:
            a = rng.randint(10_000, 9_999_999) * 1_000_000
            b = rng.randint(100_000, 9_999_999) * 1_000_000
            problems.append(
                {
                    "kind": "margin",
                    "prompt": f"Compute {a} / {b}.",
                    "truth": Decimal(a) / Decimal(b),
                }
            )
    return problems


def measure(llm, n: int = N, seed: int = SEED) -> dict:
    rows = []
    for i, prob in enumerate(_problems(n, seed)):
        doc = llm.structured(
            system=_SYSTEM,
            user=prob["prompt"],
            schema=_ANSWER_SCHEMA,
            purpose=f"m1:{prob['kind']}:{i}",
            max_tokens=200,
        )
        raw = doc["answer"].strip()
        truth = prob["truth"]
        try:
            got = Decimal(raw)
            rel_err = abs((got - truth) / truth) if truth != 0 else abs(got - truth)
        except InvalidOperation:
            got, rel_err = None, Decimal("Infinity")
        rows.append(
            {
                "kind": prob["kind"],
                "prompt": prob["prompt"],
                "truth_6sig": str(_SIX.plus(truth)),
                "model": raw,
                "rel_err": rel_err,
            }
        )
    correct = sum(1 for r in rows if r["rel_err"] < Decimal("1e-5"))
    gross = sum(1 for r in rows if r["rel_err"] > Decimal("1e-3"))
    finite = [r["rel_err"] for r in rows if r["rel_err"].is_finite()]
    return {
        "n": len(rows),
        "correct": correct,
        "gross_errors": gross,
        "error_rate": 1 - correct / len(rows),
        "max_rel_err": max(finite) if finite else None,
        "rows": rows,
    }


def _write_reports(stats: dict, model: str) -> None:
    config.NOTES_DIR.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# M1 llm-arithmetic — {date.today().isoformat()}, model {model}",
        f"n={stats['n']} correct={stats['correct']} gross={stats['gross_errors']}",
        "",
        "| kind | prompt | truth(6sig) | model | rel_err |",
        "|---|---|---|---|---|",
    ]
    for r in stats["rows"]:
        prompt = r["prompt"].replace("|", "\\|")  # |A| bars break table cells
        lines.append(
            f"| {r['kind']} | {prompt} | {r['truth_6sig']} | {r['model']} | {r['rel_err']:.2e} |"
        )
    with (config.NOTES_DIR / "measurements.md").open("a") as f:
        f.write("\n".join(lines) + "\n\n")

    headline = (
        f"## M1 — LLM arithmetic error rate (measured {date.today().isoformat()})\n\n"
        f"- Model: `{model}`, no tools, structured output, one call per problem.\n"
        f"- Operands: SEC-scale (5-7 significant digits × 1e6), {stats['n']} problems "
        f"(growth `(B-A)/|A|` incl. negative bases, and margin `A/B`), seed {SEED}.\n"
        f"- **Correct (rel. err < 1e-5): {stats['correct']}/{stats['n']} "
        f"— error rate {stats['error_rate']:.1%}.**\n"
        f"- Gross errors (rel. err > 1e-3, would survive display rounding): "
        f"{stats['gross_errors']}/{stats['n']}.\n"
        f"- Max relative error: {stats['max_rel_err']:.2e}.\n"
        f"- Full per-problem table: notes/measurements.md (local scratch).\n\n"
        f"Why it matters: this is the measured error rate the thesis rests on — "
        f"all arithmetic on the answer path runs in `decimal.Decimal` with an "
        f"emitted step trace, never in the model (CLAUDE.md rule 2).\n"
    )
    path = config.ROOT / "MEASUREMENTS.md"
    existing = path.read_text() if path.exists() else (
        "# MEASUREMENTS.md — numbers measured in this repo (rule 14)\n\n"
        "Headline results live here (committed); full tables in notes/ (scratch).\n\n"
    )
    path.write_text(existing + headline)


def run() -> int:
    from ..llm.client import LLMClient

    llm = LLMClient()
    stats = measure(llm)
    _write_reports(stats, llm.model)
    print(
        f"M1: {stats['correct']}/{stats['n']} correct (rel err < 1e-5), "
        f"{stats['gross_errors']} gross (> 1e-3), max rel err {stats['max_rel_err']:.2e}"
    )
    print("-> MEASUREMENTS.md (committed headline), notes/measurements.md (full table)")
    return 0
