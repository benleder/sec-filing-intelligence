"""Stage 1: anchor rules -> statement page ranges. L2 — imports common only.

Anchor strings were read off the real PDFs at P0.3 (§8-open): Tesla prints
title-case headings, Apple all-caps (10-K) and all-caps + " (Unaudited)"
(10-Q). Matching is full-line equality within the top lines of a page — TOC
and F-page index entries carry trailing page numbers ("Consolidated Balance
Sheets 49") and prose mentions are mid-sentence/lowercase, so neither can
match. The corpus PDFs are print-to-PDF captures of the EDGAR HTML, so a
statement may spill onto a nearly-empty footer page; ranges therefore run
from the anchor page to the page before the next full-line heading.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

STATEMENT_TYPES = ("INCOME", "BALANCE", "CASHFLOW")

_ANCHORS: dict[str, dict[str, tuple[str, ...]]] = {
    "TSLA": {
        "INCOME": ("Consolidated Statements of Operations",),
        "BALANCE": ("Consolidated Balance Sheets",),
        "CASHFLOW": ("Consolidated Statements of Cash Flows",),
    },
    "AAPL": {
        "INCOME": (
            "CONSOLIDATED STATEMENTS OF OPERATIONS",
            "CONDENSED CONSOLIDATED STATEMENTS OF OPERATIONS (Unaudited)",
        ),
        "BALANCE": (
            "CONSOLIDATED BALANCE SHEETS",
            "CONDENSED CONSOLIDATED BALANCE SHEETS (Unaudited)",
        ),
        "CASHFLOW": (
            "CONSOLIDATED STATEMENTS OF CASH FLOWS",
            "CONDENSED CONSOLIDATED STATEMENTS OF CASH FLOWS (Unaudited)",
        ),
    },
}

# Full-line headings that END a statement's range: the statements we don't
# extract (comprehensive income, equity) plus the notes heading.
_EXTRA_BOUNDARIES: dict[str, tuple[str, ...]] = {
    "TSLA": (
        "Consolidated Statements of Comprehensive Income",
        "Consolidated Statements of Redeemable Noncontrolling Interests and Equity",
        "Notes to Consolidated Financial Statements",
    ),
    "AAPL": (
        "CONSOLIDATED STATEMENTS OF COMPREHENSIVE INCOME",
        "CONDENSED CONSOLIDATED STATEMENTS OF COMPREHENSIVE INCOME (Unaudited)",
        "CONSOLIDATED STATEMENTS OF SHAREHOLDERS’ EQUITY",
        "CONDENSED CONSOLIDATED STATEMENTS OF SHAREHOLDERS’ EQUITY (Unaudited)",
        "Notes to Consolidated Financial Statements",
        "Notes to Condensed Consolidated Financial Statements (Unaudited)",
    ),
}

# Headings sit at the top of the page in these PDFs (after the print header
# and, for 10-Qs, the ITEM 1 / "Table of Contents" lines).
_HEAD_LINES = 8
_SCALE_RE = re.compile(r"\(in (millions|thousands)", re.IGNORECASE)


class SegmentationError(Exception):
    pass


@dataclass(frozen=True)
class LocatedStatement:
    statement_type: str
    page_start: int  # 1-based PDF page numbers
    page_end: int
    anchor_text: str


def _heading_on_page(page_text: str, phrases: frozenset[str]) -> str | None:
    for line in page_text.splitlines()[:_HEAD_LINES]:
        if line.strip() in phrases:
            return line.strip()
    return None


def locate_statements(pages: list[str], ticker: str) -> list[LocatedStatement]:
    """Pure page-text -> ranges logic; every failure is raised, never guessed
    around (rule 13)."""
    if ticker not in _ANCHORS:
        raise SegmentationError(f"no anchor rules for ticker {ticker!r}")
    anchors = _ANCHORS[ticker]
    boundaries = frozenset(
        phrase for group in anchors.values() for phrase in group
    ) | frozenset(_EXTRA_BOUNDARIES[ticker])

    boundary_pages = [
        page_no
        for page_no, text in enumerate(pages, start=1)
        if _heading_on_page(text, boundaries)
    ]

    located: list[LocatedStatement] = []
    for statement_type in STATEMENT_TYPES:
        wanted = frozenset(anchors[statement_type])
        hits = [
            (page_no, hit)
            for page_no, text in enumerate(pages, start=1)
            if (hit := _heading_on_page(text, wanted))
        ]
        if len(hits) != 1:
            where = [page_no for page_no, _ in hits]
            raise SegmentationError(
                f"{ticker} {statement_type}: expected exactly 1 anchor page, "
                f"got {len(hits)} {where or ''} for anchors {sorted(wanted)}"
            )
        page_start, anchor_text = hits[0]
        if not _SCALE_RE.search(pages[page_start - 1]):
            raise SegmentationError(
                f"{ticker} {statement_type}: anchor page {page_start} has no "
                f"scale declaration — surfacing instead of guessing"
            )
        following = [b for b in boundary_pages if b > page_start]
        if not following:
            raise SegmentationError(
                f"{ticker} {statement_type}: no boundary heading after "
                f"anchor page {page_start}; cannot bound the statement"
            )
        located.append(
            LocatedStatement(statement_type, page_start, min(following) - 1, anchor_text)
        )
    return located


def extract_pages(pdf_path: Path) -> list[str]:
    import pdfplumber  # heavy import stays out of module load

    with pdfplumber.open(pdf_path) as pdf:
        return [page.extract_text() or "" for page in pdf.pages]


def segment_filing(pdf_path: Path, ticker: str) -> list[LocatedStatement]:
    if not pdf_path.exists():
        raise SegmentationError(f"missing corpus PDF: {pdf_path}")
    return locate_statements(extract_pages(pdf_path), ticker)
