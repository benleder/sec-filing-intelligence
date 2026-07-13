"""Rider-1 regression: every one of Ben's 30 hand-recorded statement start
pages holds. The three extracted types assert against segment_filing ranges;
boundary statements (comprehensive income, equity) assert that the recorded
page prints the heading as a full line near the top of the page.

Ground-truth correction 2026-07-13: rows for FQ2-2025 equity/cash-flows were
a copy-paste error (p8/p9 -> p7/p8), caught by this fixture test and
corrected by Ben — see DEVIATIONS.md (D5).
"""

import csv
from pathlib import Path

import pytest

from sfi.common import config
from sfi.common.text import normalize_chars
from sfi.ingest.segment import extract_pages, segment_filing

FIXTURE = Path(__file__).parents[1] / "fixtures" / "segmentation_truth.csv"
_HEAD_LINES = 8


def _extracted_type(finance_type: str) -> str | None:
    s = finance_type.casefold()
    if "comprehensive" in s or "equity" in s:
        return None
    if "balance sheets" in s:
        return "BALANCE"
    if "statements of operations" in s:
        return "INCOME"
    if "cash flows" in s:
        return "CASHFLOW"
    return None


def _params():
    with FIXTURE.open() as f:
        for row in csv.DictReader(f, skipinitialspace=True):
            row = {k.strip(): v.strip() for k, v in row.items()}
            yield pytest.param(
                row["file_name"],
                row["finance_type"],
                int(row["starting_page_number"]),
                id=f"{row['file_name']}-{row['finance_type'][:40]}",
            )


@pytest.fixture(scope="module")
def locate():
    cache: dict[str, dict] = {}

    def get(file_name: str) -> dict:
        if file_name not in cache:
            pdf = config.RAW_DIR / f"{file_name}.pdf"
            ticker = file_name.split("_")[0]
            cache[file_name] = {s.statement_type: s for s in segment_filing(pdf, ticker)}
        return cache[file_name]

    return get


@pytest.fixture(scope="module")
def pages():
    cache: dict[str, list[str]] = {}

    def get(file_name: str) -> list[str]:
        if file_name not in cache:
            cache[file_name] = extract_pages(config.RAW_DIR / f"{file_name}.pdf")
        return cache[file_name]

    return get


@pytest.mark.parametrize(("file_name", "finance_type", "page_start"), list(_params()))
def test_recorded_start_page_holds(locate, pages, file_name, finance_type, page_start):
    if not (config.RAW_DIR / f"{file_name}.pdf").exists():
        pytest.skip("corpus PDFs not present")
    stype = _extracted_type(finance_type)
    if stype is not None:
        assert locate(file_name)[stype].page_start == page_start
        return
    # Boundary statement: the recorded page must print the heading as a
    # full line near the top (same matching discipline as segment.py).
    top_lines = [
        normalize_chars(line.strip())
        for line in pages(file_name)[page_start - 1].splitlines()[:_HEAD_LINES]
    ]
    assert normalize_chars(finance_type) in top_lines