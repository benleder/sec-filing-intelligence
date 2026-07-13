"""The ONLY module allowed to touch sec.gov (rule 5). L0 — stdlib only.

Every outbound request appends one JSON line to data/edgar_log.jsonl BEFORE
the request is sent, so the ledger is complete even for failed calls. Budgets
are enforced by re-reading the ledger, which makes them persistent across
runs: 2 submissions calls, ≤20 XBRL spot-check calls, lifetime. Bulk files
(company_tickers.json, J7) are logged but not budget-capped — the SEC's own
bulk/API distinction.
"""

from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from . import config

_BUDGETS = {"submissions": 2, "xbrl": 20}


class EdgarError(Exception):
    pass


class DisallowedURLError(EdgarError):
    pass


class BudgetExceededError(EdgarError):
    pass


def classify(url: str) -> str:
    """Map a URL to its budget class; reject anything outside the three
    endpoint families this project is allowed to touch."""
    p = urlparse(url)
    if p.scheme != "https":
        raise DisallowedURLError(f"non-https URL refused: {url}")
    if p.netloc == "data.sec.gov" and p.path.startswith("/submissions/"):
        return "submissions"
    if p.netloc == "data.sec.gov" and p.path.startswith("/api/xbrl/"):
        return "xbrl"
    if p.netloc == "www.sec.gov" and p.path.startswith("/files/"):
        return "bulk"
    raise DisallowedURLError(f"URL outside the allowed SEC endpoints: {url}")


def read_ledger(log_path: Path | None = None) -> list[dict]:
    log_path = config.EDGAR_LOG_PATH if log_path is None else log_path
    if not log_path.exists():
        return []
    return [
        json.loads(line)
        for line in log_path.read_text().splitlines()
        if line.strip()
    ]


def _default_urlopen(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": config.SEC_USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def fetch_json(
    url: str,
    *,
    purpose: str,
    log_path: Path | None = None,
    _urlopen=None,
) -> dict:
    log_path = config.EDGAR_LOG_PATH if log_path is None else log_path
    cls = classify(url)
    if cls in _BUDGETS:
        used = sum(1 for entry in read_ledger(log_path) if classify(entry["url"]) == cls)
        if used >= _BUDGETS[cls]:
            raise BudgetExceededError(
                f"{cls} budget exhausted: {used}/{_BUDGETS[cls]} calls already "
                f"logged in {log_path}; refusing {url}"
            )
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "url": url,
        "purpose": purpose,
        "kind": "bulk_file" if cls == "bulk" else "api",
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    raw = (_urlopen or _default_urlopen)(url)
    return json.loads(raw)


def fetch_json_cached(
    url: str,
    cache_path: Path,
    *,
    purpose: str,
    log_path: Path | None = None,
    _urlopen=None,
) -> tuple[dict, bool]:
    """Returns (payload, from_cache). Cache hits make zero network calls and
    log nothing — the manifest is rebuildable with zero further EDGAR calls."""
    if cache_path.exists():
        return json.loads(cache_path.read_text()), True
    payload = fetch_json(url, purpose=purpose, log_path=log_path, _urlopen=_urlopen)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload))
    return payload, False
