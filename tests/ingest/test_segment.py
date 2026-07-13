import pytest

from sfi.ingest.segment import LocatedStatement, SegmentationError, locate_statements

HDR = "7/12/26, 6:53 PM tsla-20251231"  # print-to-PDF header noise on every page


def _tsla_pages():
    return [
        # p1: TOC — same casing as the real headings but with trailing page
        # numbers, so full-line equality must NOT match.
        f"{HDR}\nTable of Contents\nConsolidated Balance Sheets 4\n"
        "Consolidated Statements of Operations 5\nConsolidated Statements of Cash Flows 8",
        # p2: balance sheet anchor page
        f"{HDR}\nTesla, Inc.\nConsolidated Balance Sheets\n(in millions, except per share data)\n"
        "Total assets 122,070 121,349",
        # p3: print-to-PDF spillover page (page-number footer only)
        f"{HDR}\n49\nhttps://www.sec.gov/Archives/...htm 3/9",
        # p4: income statement
        f"{HDR}\nTesla, Inc.\nConsolidated Statements of Operations\n"
        "(in millions, except per share data)\nTotal revenues 97,690",
        # p5: comprehensive income (boundary we don't extract)
        f"{HDR}\nTesla, Inc.\nConsolidated Statements of Comprehensive Income\n(in millions)",
        # p6: cash flows; body prose mentions other statements mid-sentence
        f"{HDR}\nTesla, Inc.\nConsolidated Statements of Cash Flows\n(in millions)\n"
        "as presented in the consolidated balance sheets were as follows",
        # p7: notes boundary
        f"{HDR}\nTesla, Inc.\nNotes to Consolidated Financial Statements\nNote 1 – Overview",
    ]


def test_happy_path_ranges_include_spillover_page():
    located = {s.statement_type: s for s in locate_statements(_tsla_pages(), "TSLA")}
    assert located["BALANCE"] == LocatedStatement("BALANCE", 2, 3, "Consolidated Balance Sheets")
    assert (located["INCOME"].page_start, located["INCOME"].page_end) == (4, 4)
    assert (located["CASHFLOW"].page_start, located["CASHFLOW"].page_end) == (6, 6)


def test_aapl_10q_condensed_anchors_match():
    pages = [
        "Apple Inc.\nCONDENSED CONSOLIDATED STATEMENTS OF OPERATIONS (Unaudited)\n(In millions)",
        "Apple Inc.\nCONDENSED CONSOLIDATED BALANCE SHEETS (Unaudited)\n(In millions)",
        "Apple Inc.\nCONDENSED CONSOLIDATED STATEMENTS OF CASH FLOWS (Unaudited)\n(In millions)",
        "Apple Inc.\nNotes to Condensed Consolidated Financial Statements (Unaudited)",
    ]
    located = {s.statement_type: (s.page_start, s.page_end) for s in locate_statements(pages, "AAPL")}
    assert located == {"INCOME": (1, 1), "BALANCE": (2, 2), "CASHFLOW": (3, 3)}


def test_rejects_toc_only_document():
    # rule 11: a document whose only "headings" are index lines must fail
    # loudly, never match the TOC.
    pages = [_tsla_pages()[0]]
    with pytest.raises(SegmentationError):
        locate_statements(pages, "TSLA")


def test_rejects_duplicate_anchor():
    pages = _tsla_pages()
    pages.append(pages[3])  # a second income-statement page
    with pytest.raises(SegmentationError, match="INCOME.*got 2"):
        locate_statements(pages, "TSLA")


def test_rejects_anchor_page_without_scale_declaration():
    pages = _tsla_pages()
    pages[3] = f"{HDR}\nTesla, Inc.\nConsolidated Statements of Operations\nTotal revenues 97,690"
    with pytest.raises(SegmentationError, match="scale declaration"):
        locate_statements(pages, "TSLA")


def test_rejects_unbounded_final_statement():
    pages = _tsla_pages()[:-1]  # drop the notes heading after cash flows
    with pytest.raises(SegmentationError, match="CASHFLOW.*no boundary"):
        locate_statements(pages, "TSLA")


def test_rejects_wrong_case_for_company():
    # Tesla's title-case heading must not satisfy Apple's all-caps anchors.
    pages = [
        "Apple Inc.\nConsolidated Balance Sheets\n(In millions)",
        "Apple Inc.\nCONDENSED CONSOLIDATED STATEMENTS OF OPERATIONS (Unaudited)\n(In millions)",
        "Apple Inc.\nCONDENSED CONSOLIDATED STATEMENTS OF CASH FLOWS (Unaudited)\n(In millions)",
        "Apple Inc.\nNotes to Condensed Consolidated Financial Statements (Unaudited)",
    ]
    with pytest.raises(SegmentationError, match="BALANCE"):
        locate_statements(pages, "AAPL")


def test_rejects_unknown_ticker():
    with pytest.raises(SegmentationError):
        locate_statements(_tsla_pages(), "MSFT")


def test_heading_below_top_of_page_is_ignored():
    # A full-line anchor string buried mid-page (e.g. quoted in a note table)
    # is not a statement heading.
    pages = _tsla_pages()
    filler = "\n".join(["filler line"] * 10)
    pages.append(f"{HDR}\n{filler}\nConsolidated Statements of Operations\n(in millions)")
    located = {s.statement_type: s.page_start for s in locate_statements(pages, "TSLA")}
    assert located["INCOME"] == 4
