"""Character normalization and print-furniture stripping. L0 — stdlib only.

Both functions are spec additions approved at the stop-2 review:

- normalize_chars: Apple prints curly apostrophes (U+2019) and PDFs can carry
  non-breaking spaces (U+00A0); these fold to ASCII before dictionary label
  matching and grounding tokenization. Nothing else is loosened — any other
  character difference must still fail a match.

- strip_print_furniture: the corpus is browser print-to-PDF captures of the
  EDGAR HTML, so every page carries a print header, a sec.gov URL footer, and
  folio (printed page-number) lines. Those tokens would enlarge the grounding
  token set and weaken the anti-hallucination guarantee, so they are stripped
  from page text before BOTH the parser input and the grounding token set.
"""

from __future__ import annotations

import re

_CHAR_MAP = str.maketrans({"’": "'", " ": " "})

# \s+ throughout: layout=True extraction pads columns with runs of spaces.
_FURNITURE_RES = (
    # browser print header: "7/12/26, 6:53 PM   tsla-20251231"
    re.compile(r"^\d{1,2}/\d{1,2}/\d{2},\s+\d{1,2}:\d{2}\s?[AP]M\s+\S+$"),
    # sec.gov URL footer, optionally with " 81/159" print pagination
    re.compile(r"^https://www\.sec\.gov/Archives/\S+(?:\s+\d+/\d+)?$"),
    # Apple's document footer: "Apple Inc. | Q2 2026 Form 10-Q | 3"
    re.compile(r"^Apple Inc\. \|\s+.*Form 10-[KQ]\s+\| \d+$|^Apple Inc\. \| .*Form 10-[KQ] \| \d+$"),
)
_FOLIO_RE = re.compile(r"^\d{1,3}$")


def normalize_chars(text: str) -> str:
    return text.translate(_CHAR_MAP)


def strip_print_furniture(text: str) -> str:
    lines = [
        line
        for line in text.splitlines()
        if not any(rx.match(line.strip()) for rx in _FURNITURE_RES)
    ]
    # Bare folio numbers are stripped only at the edges of what remains —
    # a bare-number line INSIDE the table must never be dropped. Whitespace-
    # only lines at the edges (layout=True padding) are consumed too so an
    # edge folio behind them is still reached.
    def _edge(line: str) -> bool:
        return not line.strip() or bool(_FOLIO_RE.match(line.strip()))

    while lines and _edge(lines[0]):
        lines.pop(0)
    while lines and _edge(lines[-1]):
        lines.pop()
    return "\n".join(lines)
