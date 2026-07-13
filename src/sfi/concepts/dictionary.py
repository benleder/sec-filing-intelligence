"""Load + validate concepts.yaml; matching semantics (§3.2). L1 — imports common.

Matching:
1. normalize both sides (normalize_chars per stop-2 rider, casefold, collapse
   whitespace, strip edge punctuation + trailing footnote markers)
2. exact match against labels[company] — plus, when a section heading is
   supplied, context_labels[company] (§3.2 extension, ratified 2026-07-13,
   DEVIATIONS.md D1: both companies print EPS rows as bare "Basic"/"Diluted",
   identical to the share-count rows; only the printed section heading
   distinguishes them)
3. anchored label_patterns only when no exact/context hit
4. two or more concept hits => maps to NONE (Ambiguity) — never pick a side

Concepts are statement-scoped: a "Net income" row on a CASHFLOW statement
never matches the INCOME concept.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

import yaml

from ..common.text import normalize_chars

DEFAULT_PATH = Path(__file__).with_name("concepts.yaml")

_TOP_KEYS = {"version", "concepts", "disambiguation_pairs", "footing"}
_CONCEPT_KEYS = {
    "statement",
    "unit",
    "description",
    "labels",
    "label_patterns",
    "context_labels",
    "typical_magnitude",
    "disambiguate_from",
}
_STATEMENTS = {"INCOME", "BALANCE", "CASHFLOW"}
_UNITS = {"USD", "USD_PER_SHARE", "SHARES"}


class DictionaryError(Exception):
    pass


def normalize_label(label: str) -> str:
    s = normalize_chars(label)
    s = re.sub(r"\s+", " ", s).strip().casefold()
    prev = None
    while prev != s:  # strip layered edge punctuation + footnote markers
        prev = s
        s = re.sub(r"\(\d+\)$", "", s).strip()
        s = s.strip(".:;,*† ")
    return s


@dataclass(frozen=True)
class ConceptEntry:
    concept_id: str
    statement: str
    unit: str
    description: str
    labels: dict[str, tuple[str, ...]]
    label_patterns: tuple[str, ...] = ()
    context_labels: dict[str, tuple[tuple[str, str], ...]] = field(default_factory=dict)
    typical_magnitude: tuple[Decimal, Decimal] | None = None
    disambiguate_from: tuple[str, ...] = ()


@dataclass(frozen=True)
class Match:
    concept: str
    method: str  # 'dictionary_exact' | 'dictionary_pattern'


@dataclass(frozen=True)
class Ambiguity:
    candidates: tuple[str, ...]


class Dictionary:
    def __init__(self, entries: dict[str, ConceptEntry], pairs: tuple[tuple[str, str], ...], footing: dict):
        self.entries = entries
        self.pairs = pairs
        self.footing = footing
        self._exact: dict[tuple[str, str, str], list[str]] = {}
        self._context: dict[tuple[str, str, str, str], list[str]] = {}
        self._patterns: list[tuple[str, str, re.Pattern]] = []
        for cid, e in entries.items():
            for ticker, labels in e.labels.items():
                for label in labels:
                    key = (ticker, e.statement, normalize_label(label))
                    self._exact.setdefault(key, []).append(cid)
            for ticker, pairs_ in e.context_labels.items():
                for section, label in pairs_:
                    key = (ticker, e.statement, normalize_label(section), normalize_label(label))
                    self._context.setdefault(key, []).append(cid)
            for pattern in e.label_patterns:
                self._patterns.append((cid, e.statement, re.compile(pattern)))

    def match(
        self,
        ticker: str,
        statement_type: str,
        raw_label: str,
        section: str | None = None,
    ) -> Match | Ambiguity | None:
        norm = normalize_label(raw_label)
        hits = list(self._exact.get((ticker, statement_type, norm), []))
        if section is not None:
            hits += self._context.get(
                (ticker, statement_type, normalize_label(section), norm), []
            )
        hits = sorted(set(hits))
        if len(hits) > 1:
            return Ambiguity(tuple(hits))
        if len(hits) == 1:
            return Match(hits[0], "dictionary_exact")
        pattern_hits = sorted(
            {
                cid
                for cid, stmt, rx in self._patterns
                if stmt == statement_type
                and ticker in self.entries[cid].labels | self.entries[cid].context_labels
                and rx.fullmatch(norm)
            }
        )
        if len(pattern_hits) > 1:
            return Ambiguity(tuple(pattern_hits))
        if len(pattern_hits) == 1:
            return Match(pattern_hits[0], "dictionary_pattern")
        return None

    def concept_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self.entries))


def _fail(msg: str) -> None:
    raise DictionaryError(msg)


def load(path: Path | None = None) -> Dictionary:
    path = DEFAULT_PATH if path is None else path
    doc = yaml.safe_load(path.read_text())
    if not isinstance(doc, dict):
        _fail("concepts.yaml: top level must be a mapping")
    if set(doc) - _TOP_KEYS:
        _fail(f"concepts.yaml: unknown top-level keys {sorted(set(doc) - _TOP_KEYS)}")
    if doc.get("version") != 1:
        _fail(f"concepts.yaml: unsupported version {doc.get('version')!r}")

    entries: dict[str, ConceptEntry] = {}
    for cid, spec in (doc.get("concepts") or {}).items():
        if not isinstance(spec, dict):
            _fail(f"{cid}: concept spec must be a mapping")
        if set(spec) - _CONCEPT_KEYS:
            _fail(f"{cid}: unknown keys {sorted(set(spec) - _CONCEPT_KEYS)}")
        if spec.get("statement") not in _STATEMENTS:
            _fail(f"{cid}: bad statement {spec.get('statement')!r}")
        if spec.get("unit") not in _UNITS:
            _fail(f"{cid}: bad unit {spec.get('unit')!r}")
        labels_spec = spec.get("labels")
        if not isinstance(labels_spec, dict):
            _fail(f"{cid}: labels must be a mapping of ticker -> list of strings")
        labels: dict[str, tuple[str, ...]] = {}
        for ticker, lst in labels_spec.items():
            if not isinstance(lst, list) or not all(isinstance(x, str) for x in lst):
                _fail(f"{cid}: labels[{ticker}] must be a list of strings")
            labels[ticker] = tuple(lst)
        context: dict[str, tuple[tuple[str, str], ...]] = {}
        for ticker, items in (spec.get("context_labels") or {}).items():
            parsed = []
            for item in items:
                if not isinstance(item, dict) or set(item) != {"section", "label"}:
                    _fail(f"{cid}: context_labels entries need exactly section+label")
                parsed.append((item["section"], item["label"]))
            context[ticker] = tuple(parsed)
        magnitude = spec.get("typical_magnitude")
        band: tuple[Decimal, Decimal] | None = None
        if magnitude is not None:
            if not (isinstance(magnitude, list) and len(magnitude) == 2):
                _fail(f"{cid}: typical_magnitude must be [low, high]")
            low, high = Decimal(str(magnitude[0])), Decimal(str(magnitude[1]))
            if not (0 < low < high):
                _fail(f"{cid}: typical_magnitude needs 0 < low < high")
            band = (low, high)
        patterns = tuple(spec.get("label_patterns") or ())
        for pattern in patterns:
            try:
                re.compile(pattern)
            except re.error as exc:
                _fail(f"{cid}: bad label_pattern {pattern!r}: {exc}")
        entries[cid] = ConceptEntry(
            concept_id=cid,
            statement=spec["statement"],
            unit=spec["unit"],
            description=spec.get("description", ""),
            labels=labels,
            label_patterns=patterns,
            context_labels=context,
            typical_magnitude=band,
            disambiguate_from=tuple(spec.get("disambiguate_from") or ()),
        )

    pairs_spec = doc.get("disambiguation_pairs") or []
    pairs: list[tuple[str, str]] = []
    for pair in pairs_spec:
        if not (isinstance(pair, list) and len(pair) == 2 and pair[0] != pair[1]):
            _fail(f"disambiguation pair must be two distinct ids: {pair!r}")
        a, b = pair
        for cid in (a, b):
            if cid not in entries:
                _fail(f"disambiguation pair references unknown concept {cid!r}")
        if b not in entries[a].disambiguate_from or a not in entries[b].disambiguate_from:
            _fail(f"disambiguation pair [{a}, {b}] is not mirrored in disambiguate_from")
        pairs.append((a, b))
    declared = {frozenset(p) for p in pairs}
    for cid, e in entries.items():
        for other in e.disambiguate_from:
            if other not in entries:
                _fail(f"{cid}: disambiguate_from references unknown concept {other!r}")
            if frozenset((cid, other)) not in declared:
                _fail(f"{cid} <-> {other}: disambiguate_from without a disambiguation_pairs entry")

    footing = doc.get("footing") or {}
    for ticker, per_stmt in footing.items():
        if not isinstance(per_stmt, dict) or set(per_stmt) - _STATEMENTS:
            _fail(f"footing[{ticker}]: keys must be statement types")
        for stmt, rules in per_stmt.items():
            for rule in rules or []:
                if not isinstance(rule, dict) or set(rule) != {"total", "components"}:
                    _fail(f"footing[{ticker}][{stmt}]: rules need exactly total+components")

    return Dictionary(entries, tuple(pairs), footing)
