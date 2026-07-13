"""Per-filing ingest orchestrator: segment -> extract -> accept -> write (§1).

P0.3 ships stage 1 only: --dry-run prints located page ranges. The
extract/accept/write stages land at P0.5.
"""

from __future__ import annotations

import json

from ..common import config
from . import segment


class IngestError(Exception):
    pass


def load_manifest() -> dict:
    if not config.MANIFEST_PATH.exists():
        raise IngestError(f"{config.MANIFEST_PATH} missing — run `sfi manifest` first")
    return json.loads(config.MANIFEST_PATH.read_text())


def run(filing: str | None = None, dry_run: bool = False) -> int:
    if not dry_run:
        raise SystemExit("sfi ingest: extract/accept/write not built yet (P0.5); use --dry-run")

    manifest = load_manifest()
    filings = [f for f in manifest["filings"] if f["pdf_path"]]
    if filing is not None:
        filings = [f for f in filings if f["accession_no"] == filing]
        if not filings:
            raise IngestError(f"accession {filing!r} not in manifest (or has no PDF)")

    header = ("pdf", "statement", "pages", "anchor matched")
    rows: list[tuple[str, ...]] = [header, tuple("-" * len(h) for h in header)]
    total = 0
    for f in filings:
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
    print(f"\n{total}/{3 * len(filings)} statements located")
    return 0
