"""Stage 0: manifest.json from exactly 2 EDGAR submissions calls (+1 bulk
company_tickers.json fetch, J7). L2 — imports common only.

No field in the manifest is ever hand-typed (rule 5): CIKs come from
company_tickers.json, filing metadata from the submissions API. The only
human input is the six PDF filenames; the filename<->accession join is
computed, and hard-fails on 0 or >=2 candidates (rule 13: surfaced, never
guessed).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from ..common import config, edgar
from ..common.periods import FiscalCalendar, PeriodResolutionError

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"

# TSLA_10-K_FY2025 | TSLA_10-Q_Q1-2026 | AAPL_10-Q_FQ2-2026 ("FQ2" and "Q2"
# both mean fiscal Q2; Apple's filenames just spell the F out).
_FILENAME_RE = re.compile(
    r"^(?P<ticker>[A-Z]+)_(?P<form>10-[KQ])_(?P<label>FY\d{4}|F?Q[1-3]-\d{4})\.pdf$"
)


class ManifestError(Exception):
    pass


@dataclass(frozen=True)
class ParsedName:
    filename: str
    ticker: str
    form: str
    fiscal_year: int
    fiscal_period: str  # 'FY' | 'Q1' | 'Q2' | 'Q3'


@dataclass(frozen=True)
class FilingRow:
    form: str
    accession_no: str
    filing_date: str
    report_date: str


def parse_pdf_filename(filename: str) -> ParsedName:
    m = _FILENAME_RE.match(filename)
    if not m:
        raise ManifestError(f"unrecognized corpus filename: {filename!r}")
    label = m.group("label")
    if label.startswith("FY"):
        fiscal_period, fiscal_year = "FY", int(label[2:])
    else:
        q = label.lstrip("F")
        fiscal_period, fiscal_year = f"Q{q[1]}", int(q.split("-")[1])
    return ParsedName(filename, m.group("ticker"), m.group("form"), fiscal_year, fiscal_period)


def resolve_ciks(tickers: list[str], tickers_json: dict) -> dict[str, str]:
    ciks: dict[str, str] = {}
    for entry in tickers_json.values():
        t = entry["ticker"].upper()
        if t in tickers:
            ciks[t] = f"{int(entry['cik_str']):010d}"
    missing = sorted(set(tickers) - ciks.keys())
    if missing:
        raise ManifestError(f"CIK not found in company_tickers.json for: {missing}")
    return ciks


def _recent_rows(submissions: dict) -> list[FilingRow]:
    recent = submissions["filings"]["recent"]
    return [
        FilingRow(form, acc, filed, report)
        for form, acc, filed, report in zip(
            recent["form"],
            recent["accessionNumber"],
            recent["filingDate"],
            recent["reportDate"],
        )
    ]


def _label(cal: FiscalCalendar, row: FilingRow) -> tuple[int, str] | None:
    try:
        period_end = date.fromisoformat(row.report_date)
        return cal.fiscal_year_of(period_end), cal.fiscal_period_of(period_end, row.form)
    except (PeriodResolutionError, ValueError):
        return None  # not one of ours; a malformed date can't silently match


def match_filings(
    pdfs: list[ParsedName],
    rows_by_ticker: dict[str, list[FilingRow]],
    calendars: dict[str, FiscalCalendar],
) -> list[dict]:
    filings: list[dict] = []
    for pdf in pdfs:
        cal = calendars[pdf.ticker]
        candidates = [
            row
            for row in rows_by_ticker[pdf.ticker]
            if row.form == pdf.form
            and _label(cal, row) == (pdf.fiscal_year, pdf.fiscal_period)
        ]
        if len(candidates) != 1:
            listing = "; ".join(
                f"{r.accession_no} filed {r.filing_date} period {r.report_date}"
                for r in candidates
            )
            raise ManifestError(
                f"{pdf.filename}: expected exactly 1 manifest candidate, "
                f"got {len(candidates)}" + (f" [{listing}]" if listing else "")
            )
        row = candidates[0]
        filings.append(
            {
                "ticker": pdf.ticker,
                "accession_no": row.accession_no,
                "form_type": row.form,
                "filing_date": row.filing_date,
                "period_end": row.report_date,
                "fiscal_year": pdf.fiscal_year,
                "fiscal_period": pdf.fiscal_period,
                "is_amendment": False,
                "amends_accession": None,
                "pdf_path": f"data/raw/{pdf.filename}",
            }
        )
        for arow in rows_by_ticker[pdf.ticker]:
            if arow.form == pdf.form + "/A" and arow.report_date == row.report_date:
                filings.append(
                    {
                        "ticker": pdf.ticker,
                        "accession_no": arow.accession_no,
                        "form_type": arow.form,
                        "filing_date": arow.filing_date,
                        "period_end": arow.report_date,
                        "fiscal_year": pdf.fiscal_year,
                        "fiscal_period": pdf.fiscal_period,
                        "is_amendment": True,
                        "amends_accession": row.accession_no,
                        "pdf_path": None,
                    }
                )
    return filings


def build_manifest(
    raw_dir: Path | None = None,
    manifest_dir: Path | None = None,
    log_path: Path | None = None,
    _urlopen=None,
) -> dict:
    raw_dir = config.RAW_DIR if raw_dir is None else raw_dir
    manifest_dir = config.MANIFEST_DIR if manifest_dir is None else manifest_dir

    pdf_names = sorted(p.name for p in raw_dir.glob("*.pdf"))
    if len(pdf_names) != 6:
        raise ManifestError(
            f"expected the 6 corpus PDFs in {raw_dir} (rule 7), found {len(pdf_names)}"
        )
    pdfs = [parse_pdf_filename(name) for name in pdf_names]
    tickers = sorted({p.ticker for p in pdfs})

    requests: list[dict] = []
    tickers_json, _ = edgar.fetch_json_cached(
        TICKERS_URL,
        manifest_dir / "company_tickers.json",
        purpose="cik_resolution",
        log_path=log_path,
        _urlopen=_urlopen,
    )
    requests.append({"url": TICKERS_URL, "purpose": "cik_resolution", "kind": "bulk_file"})
    ciks = resolve_ciks(tickers, tickers_json)

    companies: dict[str, dict] = {}
    calendars: dict[str, FiscalCalendar] = {}
    rows_by_ticker: dict[str, list[FilingRow]] = {}
    for ticker in tickers:
        url = SUBMISSIONS_URL.format(cik=ciks[ticker])
        submissions, _ = edgar.fetch_json_cached(
            url,
            manifest_dir / f"CIK{ciks[ticker]}.json",
            purpose="manifest",
            log_path=log_path,
            _urlopen=_urlopen,
        )
        requests.append({"url": url, "purpose": "manifest", "kind": "api"})
        fye = submissions["fiscalYearEnd"]  # e.g. "1231"
        calendars[ticker] = FiscalCalendar.from_mmdd(fye)
        rows_by_ticker[ticker] = _recent_rows(submissions)
        companies[ticker] = {
            "cik": ciks[ticker],
            "name": submissions["name"],
            "fiscal_year_end_mmdd": f"--{fye[:2]}-{fye[2:]}",
        }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "edgar_requests": requests,
        "companies": companies,
        "filings": match_filings(pdfs, rows_by_ticker, calendars),
    }


def format_join_table(manifest: dict) -> str:
    header = ("pdf", "accession_no", "form", "filed", "period_end", "fiscal")
    rows = [header, tuple("-" * len(h) for h in header)]
    for f in manifest["filings"]:
        pdf = Path(f["pdf_path"]).name if f["pdf_path"] else "(no pdf)"
        fiscal = (
            f"FY{f['fiscal_year']}"
            if f["fiscal_period"] == "FY"
            else f"{f['fiscal_period']} FY{f['fiscal_year']}"
        )
        if f["is_amendment"]:
            fiscal += f"  amends {f['amends_accession']}"
        rows.append(
            (pdf, f["accession_no"], f["form_type"], f["filing_date"], f["period_end"], fiscal)
        )
    widths = [max(len(str(r[i])) for r in rows) for i in range(len(header))]
    return "\n".join(
        "  ".join(str(cell).ljust(widths[i]) for i, cell in enumerate(row)).rstrip()
        for row in rows
    )


def run() -> int:
    manifest = build_manifest()
    config.MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n")
    print(format_join_table(manifest))
    print(f"\n{len(manifest['filings'])} filing records -> {config.MANIFEST_PATH}")
    ledger = edgar.read_ledger()
    print(f"edgar ledger: {len(ledger)} lifetime call(s) in {config.EDGAR_LOG_PATH}")
    return 0
