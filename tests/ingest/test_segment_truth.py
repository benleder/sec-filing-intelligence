"""Rider-1 regression: every located range starts at the page Ben recorded
by hand in tests/fixtures/segmentation_truth.csv (extracted statement types
only — comprehensive-income and equity rows are boundaries, not extractions).
"""

import csv
from pathlib import Path

import pytest

from sfi.common import config
from sfi.ingest.segment import segment_filing

FIXTURE = Path(__file__).parents[1] / "fixtures" / "segmentation_truth.csv"

# rule 9 protocol: Ben's recorded values are never edited here. This row
# disagrees with the PDF itself (FQ2-2025 p8's heading is CONDENSED
# CONSOLIDATED STATEMENTS OF CASH FLOWS, p9 is the notes heading; the CSV's
# 8/9 values for equity/cash-flows match the FQ2-2026 block) — flagged for
# Ben to re-check. strict=True makes this XPASS-fail the moment the CSV is
# corrected, so the marker gets removed rather than lingering.
FLAGGED = {
    ("AAPL_10-Q_FQ2-2025", "CASHFLOW"): "suspected copy of the FQ2-2026 row; PDF shows p8",
}


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
            stype = _extracted_type(row["finance_type"])
            if stype is None:
                continue
            key = (row["file_name"], stype)
            marks = (
                [pytest.mark.xfail(strict=True, reason=FLAGGED[key])]
                if key in FLAGGED
                else []
            )
            yield pytest.param(
                row["file_name"],
                stype,
                int(row["starting_page_number"]),
                id=f"{key[0]}-{stype}",
                marks=marks,
            )


@pytest.fixture(scope="module")
def locate():
    cache: dict[str, dict] = {}

    def get(file_name: str) -> dict:
        if file_name not in cache:
            pdf = config.RAW_DIR / f"{file_name}.pdf"
            ticker = file_name.split("_")[0]
            cache[file_name] = {
                s.statement_type: s for s in segment_filing(pdf, ticker)
            }
        return cache[file_name]

    return get


@pytest.mark.parametrize(("file_name", "stype", "page_start"), list(_params()))
def test_range_starts_at_recorded_page(locate, file_name, stype, page_start):
    if not (config.RAW_DIR / f"{file_name}.pdf").exists():
        pytest.skip("corpus PDFs not present")
    assert locate(file_name)[stype].page_start == page_start
