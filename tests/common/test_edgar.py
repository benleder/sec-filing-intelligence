import json

import pytest

from sfi.common import edgar

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK0001318605.json"
XBRL_URL = "https://data.sec.gov/api/xbrl/companyconcept/CIK0001318605/us-gaap/Revenues.json"
BULK_URL = "https://www.sec.gov/files/company_tickers.json"


def _ok_opener(url: str) -> bytes:
    return b'{"ok": true}'


def _boom_opener(url: str) -> bytes:
    raise ConnectionError("network down")


def _seed_ledger(log_path, url, n):
    lines = [json.dumps({"ts": "t", "url": url, "purpose": "p", "kind": "api"}) for _ in range(n)]
    log_path.write_text("\n".join(lines) + "\n")


def test_rejects_non_sec_url(tmp_path):
    with pytest.raises(edgar.DisallowedURLError):
        edgar.fetch_json(
            "https://example.com/x.json",
            purpose="p",
            log_path=tmp_path / "log.jsonl",
            _urlopen=_ok_opener,
        )


def test_rejects_http_url(tmp_path):
    with pytest.raises(edgar.DisallowedURLError):
        edgar.fetch_json(
            "http://data.sec.gov/submissions/CIK0000000000.json",
            purpose="p",
            log_path=tmp_path / "log.jsonl",
            _urlopen=_ok_opener,
        )


def test_rejects_unknown_sec_path(tmp_path):
    with pytest.raises(edgar.DisallowedURLError):
        edgar.fetch_json(
            "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany",
            purpose="p",
            log_path=tmp_path / "log.jsonl",
            _urlopen=_ok_opener,
        )


def test_rejects_third_submissions_call(tmp_path):
    log = tmp_path / "log.jsonl"
    _seed_ledger(log, SUBMISSIONS_URL, 2)
    with pytest.raises(edgar.BudgetExceededError):
        edgar.fetch_json(SUBMISSIONS_URL, purpose="manifest", log_path=log, _urlopen=_ok_opener)


def test_rejects_21st_xbrl_call(tmp_path):
    log = tmp_path / "log.jsonl"
    _seed_ledger(log, XBRL_URL, 20)
    with pytest.raises(edgar.BudgetExceededError):
        edgar.fetch_json(XBRL_URL, purpose="spotcheck", log_path=log, _urlopen=_ok_opener)


def test_budget_rejection_makes_no_request_and_logs_nothing(tmp_path):
    log = tmp_path / "log.jsonl"
    _seed_ledger(log, SUBMISSIONS_URL, 2)
    with pytest.raises(edgar.BudgetExceededError):
        edgar.fetch_json(SUBMISSIONS_URL, purpose="manifest", log_path=log, _urlopen=_boom_opener)
    assert len(edgar.read_ledger(log)) == 2  # nothing appended


def test_logs_before_request_is_sent(tmp_path):
    log = tmp_path / "log.jsonl"
    with pytest.raises(ConnectionError):
        edgar.fetch_json(SUBMISSIONS_URL, purpose="manifest", log_path=log, _urlopen=_boom_opener)
    entries = edgar.read_ledger(log)
    assert len(entries) == 1 and entries[0]["url"] == SUBMISSIONS_URL


def test_bulk_is_logged_with_bulk_kind(tmp_path):
    log = tmp_path / "log.jsonl"
    edgar.fetch_json(BULK_URL, purpose="cik_resolution", log_path=log, _urlopen=_ok_opener)
    assert edgar.read_ledger(log)[0]["kind"] == "bulk_file"


def test_cache_hit_makes_no_call_and_logs_nothing(tmp_path):
    log = tmp_path / "log.jsonl"
    cache = tmp_path / "cached.json"
    cache.write_text('{"cached": true}')
    payload, from_cache = edgar.fetch_json_cached(
        SUBMISSIONS_URL, cache, purpose="manifest", log_path=log, _urlopen=_boom_opener
    )
    assert from_cache and payload == {"cached": True}
    assert edgar.read_ledger(log) == []
