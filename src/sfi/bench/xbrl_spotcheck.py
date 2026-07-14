"""Ground-truth spot-check (§6.4): ≤20 one-time XBRL calls validating the
benchmark's EXPECTED values — this checks the checker, never the system.
Every call goes through common/edgar.py (logged, budget-capped at 20 xbrl
calls lifetime); responses are cached so re-runs cost zero calls. The script
never edits benchmark.yaml.

With Ben's 2026-07-13 rule-9 waiver (FILL_ME values filled from the raw PDF
text layer), this is the independent verification leg for those values.
Concept -> us-gaap tag mapping is hand-maintained here; note the Tesla
subtlety it deliberately exercises: plain "Net income" (incl. NCI) is
us-gaap:ProfitLoss, while "attributable to common stockholders" is
us-gaap:NetIncomeLoss.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import yaml

from ..common import config, edgar

XBRL_URL = "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{tag}.json"

# entry id -> (ticker, tag, unit key, span kind)
# span kind: 'FY' duration ~1y, 'Q' duration ~3mo, 'instant'
CHECKS = [
    ("B01", "AAPL", "RevenueFromContractWithCustomerExcludingAssessedTax", "USD", "FY"),
    ("B02", "TSLA", "Revenues", "USD", "FY"),
    ("B03", "TSLA", "ProfitLoss", "USD", "FY"),
    ("B04", "AAPL", "CashAndCashEquivalentsAtCarryingValue", "USD", "instant"),
    ("B05", "TSLA", "Assets", "USD", "instant"),
    ("B06", "AAPL", "ResearchAndDevelopmentExpense", "USD", "FY"),
    ("B08", "AAPL", "Liabilities", "USD", "instant"),
    ("B21", "TSLA", "ProfitLoss", "USD", "Q"),
    ("B22", "TSLA", "NetIncomeLoss", "USD", "FY"),
    ("B23", "AAPL", "EarningsPerShareDiluted", "USD/shares", "FY"),
]

_SPAN_DAYS = {"FY": (350, 380), "Q": (80, 100)}


def _period_end(manifest: dict, ticker: str, period: dict) -> str:
    """Exact period end from the manifest — never hand-typed (rule 5)."""
    for f in manifest["filings"]:
        if (
            f["ticker"] == ticker
            and f["fiscal_year"] == period["fiscal_year"]
            and f["fiscal_period"] == period["fiscal_period"]
            and not f["is_amendment"]
        ):
            return f["period_end"]
    raise LookupError(f"{ticker} {period} not in manifest")


def _pick_fact(payload: dict, unit_key: str, end: str, span: str) -> dict | None:
    candidates = []
    for fact in payload.get("units", {}).get(unit_key, []):
        if fact.get("end") != end:
            continue
        if span != "instant":
            start = fact.get("start")
            if not start:
                continue
            days = (date.fromisoformat(end) - date.fromisoformat(start)).days
            low, high = _SPAN_DAYS[span]
            if not (low <= days <= high):
                continue
        candidates.append(fact)
    return max(candidates, key=lambda f: f.get("filed", "")) if candidates else None


def run() -> int:
    entries = {e["id"]: e for e in yaml.safe_load(
        (config.BENCH_DIR / "benchmark.yaml").read_text()
    )}
    manifest = json.loads(config.MANIFEST_PATH.read_text())
    cache_dir = config.MANIFEST_DIR / "xbrl"
    payloads: dict[tuple[str, str], dict] = {}
    mismatches = 0

    for entry_id, ticker, tag, unit_key, span in CHECKS:
        entry = entries[entry_id]
        cik = manifest["companies"][ticker]["cik"]
        key = (cik, tag)
        if key not in payloads:
            payloads[key], _ = edgar.fetch_json_cached(
                XBRL_URL.format(cik=cik, tag=tag),
                cache_dir / f"CIK{cik}-{tag}.json",
                purpose="benchmark_spotcheck",
            )
        end = _period_end(manifest, ticker, entry["expect"]["period"])
        fact = _pick_fact(payloads[key], unit_key, end, span)
        expected = Decimal(str(entry["expect"]["value"]))
        if fact is None:
            mismatches += 1
            print(f"{entry_id}  NO XBRL FACT for {tag} end={end} — flag for Ben")
            continue
        got = Decimal(str(fact["val"]))
        if got == expected:
            print(f"{entry_id}  OK        {tag}: XBRL {got} == expected")
        else:
            mismatches += 1
            print(
                f"{entry_id}  MISMATCH  {tag}: XBRL {got} != expected {expected} "
                f"(accn {fact.get('accn')}) — flag for Ben to re-read the PDF"
            )

    ledger = [e for e in edgar.read_ledger() if "api/xbrl" in e["url"]]
    print(f"\n{len(CHECKS)} expectations checked via {len(payloads)} distinct "
          f"XBRL concepts; lifetime xbrl calls logged: {len(ledger)}/20")
    if mismatches:
        print(f"{mismatches} FLAG(S) — benchmark.yaml is never auto-edited; re-check by hand")
    return 0 if mismatches == 0 else 1
