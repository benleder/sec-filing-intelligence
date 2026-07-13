"""Stage 2: the LLM parser call (§4.1/§4.2). L2 — imports common, llm.

The parser TRANSCRIBES; every cell it returns is verified against the source
page by accept.py. Layout-hints v1 = extract_text(layout=True), furniture-
stripped; richer hints (word x-positions) remain the designed fallback
(§8-open).
"""

from __future__ import annotations

from .segment import LocatedStatement

PROMPT_VERSION = "p0.5-v1"

SYSTEM = """You transcribe the structure of one financial statement from PDF text. You are a
PARSER, not an analyst. Hard rules:
- TRANSCRIBE, never compute, never infer, never correct. If a value is missing or
  illegible, omit the cell — do not guess.
- Copy label and value characters EXACTLY as printed, including commas, parentheses,
  and '$'. Do not normalize numbers.
- Report the scale declaration verbatim (e.g. "(in millions, except per share data)")
  and your reading of it.
- Report each column header verbatim and your reading of its period (start/end dates,
  duration kind). Do not resolve fiscal aliases beyond what is printed.
- Section headings printed without values (e.g. "Operating expenses", "Earnings per
  share:") are rows with an empty cells array.
- For each cell, report the page number whose text contains it.
Nothing you output is trusted; every cell will be verified against the source page."""

PARSER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["statement_type", "scale", "columns", "rows"],
    "properties": {
        "statement_type": {"enum": ["INCOME", "BALANCE", "CASHFLOW"]},
        "scale": {
            "type": "object",
            "additionalProperties": False,
            "required": ["text_verbatim", "multiplier", "per_share_exception"],
            "properties": {
                "text_verbatim": {"type": "string"},
                "multiplier": {"enum": [1, 1000, 1000000]},
                "per_share_exception": {"type": "boolean"},
            },
        },
        "columns": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["index", "header_verbatim", "period_start", "period_end", "duration"],
                "properties": {
                    "index": {"type": "integer"},
                    "header_verbatim": {"type": "string"},
                    "period_start": {"type": ["string", "null"]},
                    "period_end": {"type": "string"},
                    "duration": {"enum": ["INSTANT", "QUARTER", "YTD", "FISCAL_YEAR"]},
                },
            },
        },
        "rows": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["row_index", "label_verbatim", "indent_level", "is_subtotal", "cells"],
                "properties": {
                    "row_index": {"type": "integer"},
                    "label_verbatim": {"type": "string"},
                    "indent_level": {"type": "integer"},
                    "is_subtotal": {"type": "boolean"},
                    "cells": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["column_index", "value_verbatim", "page"],
                            "properties": {
                                "column_index": {"type": "integer"},
                                "value_verbatim": {"type": "string"},
                                "page": {"type": "integer"},
                            },
                        },
                    },
                },
            },
        },
    },
}


def build_user_message(
    ticker: str,
    form_type: str,
    located: LocatedStatement,
    layout_texts: dict[int, str],
    feedback: str | None = None,
) -> str:
    pages = f"{located.page_start}-{located.page_end}"
    parts = [
        f"statement_type: {located.statement_type}",
        f"company: {ticker}        form: {form_type}        pages: {pages}",
    ]
    for page_no in range(located.page_start, located.page_end + 1):
        parts.append(f"--- page {page_no} ---")
        parts.append(layout_texts[page_no])
    if feedback:
        parts.append(f"PREVIOUS ATTEMPT FAILED CHECKS:\n{feedback}")
    return "\n".join(parts)


def parse_statement(
    client,
    *,
    ticker: str,
    form_type: str,
    located: LocatedStatement,
    layout_texts: dict[int, str],
    feedback: str | None = None,
) -> dict:
    user = build_user_message(ticker, form_type, located, layout_texts, feedback)
    attempt = "retry" if feedback else "first"
    return client.structured(
        system=SYSTEM,
        user=user,
        schema=PARSER_SCHEMA,
        purpose=f"parse:{ticker}:{located.statement_type}:{attempt}",
    )
