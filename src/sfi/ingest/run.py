"""Per-filing ingest orchestrator: segment -> extract -> accept -> write (§1).

Retry policy is J5: exactly one re-parse with the check-failure feedback
appended, then quarantine. A quarantine writes its statement + check rows,
stops the run loudly with the page numbers, and returns non-zero — Ben is
the review queue (rule 12).
"""

from __future__ import annotations

import json

from ..common import config
from ..common.models import Filing
from ..common.periods import FiscalCalendar
from ..common.text import strip_print_furniture
from ..concepts import dictionary as dictionary_mod
from ..store import db
from . import accept, extract, segment


class IngestError(Exception):
    pass


def load_manifest() -> dict:
    if not config.MANIFEST_PATH.exists():
        raise IngestError(f"{config.MANIFEST_PATH} missing — run `sfi manifest` first")
    return json.loads(config.MANIFEST_PATH.read_text())


def _filing_from_record(record: dict) -> Filing:
    return Filing(
        ticker=record["ticker"],
        accession_no=record["accession_no"],
        form_type=record["form_type"],
        filing_date=record["filing_date"],
        period_end=record["period_end"],
        fiscal_year=record["fiscal_year"],
        fiscal_period=record["fiscal_period"],
        is_amendment=record["is_amendment"],
        amends_accession=record["amends_accession"],
        pdf_path=record["pdf_path"],
    )


def _page_texts(pdf_path, located_list) -> tuple[dict[int, str], dict[int, str]]:
    """Both representations, furniture-stripped: layout=True for the parser
    input, plain for the grounding token sets (stop-2 rider 3)."""
    import pdfplumber

    pages_needed = sorted(
        {
            page
            for st in located_list
            for page in range(st.page_start, st.page_end + 1)
        }
    )
    layout, plain = {}, {}
    with pdfplumber.open(pdf_path) as pdf:
        for page_no in pages_needed:
            page = pdf.pages[page_no - 1]
            layout[page_no] = strip_print_furniture(page.extract_text(layout=True) or "")
            plain[page_no] = strip_print_furniture(page.extract_text() or "")
    return layout, plain


def _ingest_statement(llm, filing, located, layout_texts, plain_texts, dictionary, calendar):
    """One statement through parse -> accept, with the single J5 retry.
    Returns (result, attempts)."""
    feedback = None
    for attempt in (1, 2):
        raw = extract.parse_statement(
            llm,
            ticker=filing.ticker,
            form_type=filing.form_type,
            located=located,
            layout_texts={
                p: layout_texts[p]
                for p in range(located.page_start, located.page_end + 1)
            },
            feedback=feedback,
        )
        try:
            parsed = accept.ParsedStatement.from_json(raw)
        except accept.ParseShapeError as exc:
            from ..common.models import CheckResult

            quarantine = accept.Quarantine(
                f"structure: {exc}",
                (CheckResult("period", "FAIL", None, f"structural: {exc}"),),
            )
            if attempt == 1:
                feedback = f"structure: {exc}"
                continue
            return quarantine, attempt
        result = accept.accept_statement(
            parsed, filing, plain_texts, dictionary, calendar, located
        )
        if isinstance(result, accept.AcceptedStatement):
            return result, attempt
        if attempt == 1:
            feedback = accept.failure_feedback(result.checks)
    return result, 2


def run(filing: str | None = None, dry_run: bool = False) -> int:
    manifest = load_manifest()
    records = [f for f in manifest["filings"] if f["pdf_path"]]
    if filing is not None:
        records = [f for f in records if f["accession_no"] == filing]
        if not records:
            raise IngestError(f"accession {filing!r} not in manifest (or has no PDF)")

    if dry_run:
        return _dry_run(records)

    dictionary = dictionary_mod.load()
    from ..llm.client import LLMClient

    llm = LLMClient()
    con = db.connect()
    writer = db.FactWriter(con)
    writer.ensure_filings(manifest)
    con.commit()

    summary: list[str] = []
    for record in records:
        filing_obj = _filing_from_record(record)
        calendar = FiscalCalendar.from_mmdd(
            manifest["companies"][filing_obj.ticker]["fiscal_year_end_mmdd"]
        )
        pdf_path = config.ROOT / record["pdf_path"]
        located_list = segment.segment_filing(pdf_path, filing_obj.ticker)
        layout_texts, plain_texts = _page_texts(pdf_path, located_list)
        writer.replace_filing(filing_obj.accession_no)

        for located in located_list:
            statement_plain = {
                p: plain_texts[p]
                for p in range(located.page_start, located.page_end + 1)
            }
            result, attempts = _ingest_statement(
                llm, filing_obj, located, layout_texts, statement_plain, dictionary, calendar
            )
            name = f"{pdf_path.name} {located.statement_type} p{located.page_start}-{located.page_end}"
            if isinstance(result, accept.Quarantine):
                writer.write_quarantined(
                    filing_obj, located, result, llm.model, extract.PROMPT_VERSION
                )
                con.commit()
                print("\n".join(summary))
                print(f"\n*** QUARANTINED after {attempts} attempt(s): {name}")
                print(f"*** pages to review: {located.page_start}-{located.page_end} of {pdf_path.name}")
                for c in result.checks:
                    if c.status == "FAIL":
                        print(f"***   {c.check_name} FAIL {c.fact_ref or ''}: {c.detail}")
                print("*** ingestion stopped for review (rule 12)")
                return 1
            writer.write_accepted(
                filing_obj, located, result, llm.model, extract.PROMPT_VERSION
            )
            con.commit()
            statuses = {"PASS": 0, "INCONCLUSIVE": 0}
            for c in result.checks:
                statuses[c.status] = statuses.get(c.status, 0) + 1
            retry = " (after 1 retry)" if attempts == 2 else ""
            summary.append(
                f"ACCEPTED    {name}: {len(result.facts)} facts, "
                f"{statuses['PASS']} PASS / {statuses['INCONCLUSIVE']} INCONCLUSIVE{retry}"
            )
        writer.mark_ingested(filing_obj.accession_no)
        con.commit()

    print("\n".join(summary))
    print(f"\n{len(summary)} statement(s) ACCEPTED, 0 QUARANTINED")
    return 0


def _dry_run(records: list[dict]) -> int:
    header = ("pdf", "statement", "pages", "anchor matched")
    rows: list[tuple[str, ...]] = [header, tuple("-" * len(h) for h in header)]
    total = 0
    for f in records:
        located = segment.segment_filing(config.ROOT / f["pdf_path"], f["ticker"])
        for st in located:
            pages = (
                str(st.page_start)
                if st.page_start == st.page_end
                else f"{st.page_start}-{st.page_end}"
            )
            rows.append((f["pdf_path"].split("/")[-1], st.statement_type, pages, st.anchor_text))
            total += 1
    widths = [max(len(r[i]) for r in rows) for i in range(len(header))]
    for row in rows:
        print("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
    print(f"\n{total}/{3 * len(records)} statements located")
    return 0
