import textwrap

import pytest

from sfi.concepts import dictionary as d


@pytest.fixture(scope="module")
def real() -> d.Dictionary:
    return d.load()


def test_real_dictionary_loads_19_concepts_with_pair(real):
    assert len(real.entries) == 19
    assert ("net_income", "net_income_attributable_common") in real.pairs


def test_exact_matches_per_company(real):
    assert real.match("TSLA", "INCOME", "Total revenues").concept == "revenue"
    assert real.match("AAPL", "INCOME", "Total net sales").concept == "revenue"
    # Apple prints the DOLLAR line as "Gross margin" — must map for AAPL only.
    assert real.match("AAPL", "INCOME", "Gross margin").concept == "gross_profit"
    assert real.match("TSLA", "INCOME", "Gross margin") is None
    assert real.match("TSLA", "INCOME", "Income from operations").concept == "operating_income"


def test_statement_scoping(real):
    # "Net income" opens both cash-flow statements; it must not map there.
    assert real.match("TSLA", "CASHFLOW", "Net income") is None
    assert real.match("TSLA", "INCOME", "Net income").concept == "net_income"


def test_curly_apostrophe_label_matches(real):
    # rider-2 pin: dictionary stores straight apostrophes; the PDF prints
    # U+2019. Only the apostrophe form may differ.
    assert real.match("TSLA", "BALANCE", "Total stockholders’ equity").concept == "total_equity"
    assert real.match("AAPL", "BALANCE", "Total shareholders’ equity").concept == "total_equity"
    assert real.match("TSLA", "BALANCE", "Total stockholders equity") is None


def test_footnote_marker_and_edge_punctuation_stripped(real):
    assert real.match("TSLA", "INCOME", "Total revenues (1)").concept == "revenue"
    assert real.match("TSLA", "INCOME", "Total revenues:").concept == "revenue"


def test_eps_requires_matching_section(real):
    eps = real.match("AAPL", "INCOME", "Basic", section="Earnings per share:")
    assert eps is not None and eps.concept == "eps_basic"
    tsla = real.match(
        "TSLA",
        "INCOME",
        "Diluted",
        section="Net income per share of common stock attributable to common stockholders",
    )
    assert tsla.concept == "eps_diluted"
    # rule 11: the share-count rows print the SAME bare labels — the wrong
    # section (or no section) must map to none.
    assert real.match("AAPL", "INCOME", "Basic", section="Shares used in computing earnings per share:") is None
    assert real.match("AAPL", "INCOME", "Basic") is None


AMBIGUOUS_YAML = textwrap.dedent(
    """
    version: 1
    concepts:
      net_income:
        statement: INCOME
        unit: USD
        labels: {TSLA: ["Net income"]}
        disambiguate_from: [net_income_attributable_common]
      net_income_attributable_common:
        statement: INCOME
        unit: USD
        labels: {TSLA: ["Net income"]}
        disambiguate_from: [net_income]
    disambiguation_pairs:
      - [net_income, net_income_attributable_common]
    """
)


def test_label_matching_two_concepts_maps_to_none(tmp_path):
    # rule 11 (P0.4 DoD): a crafted label matching both members of the
    # disambiguation pair must be rejected, never silently picked.
    path = tmp_path / "concepts.yaml"
    path.write_text(AMBIGUOUS_YAML)
    dic = d.load(path)
    result = dic.match("TSLA", "INCOME", "Net income")
    assert isinstance(result, d.Ambiguity)
    assert set(result.candidates) == {"net_income", "net_income_attributable_common"}


def _base_yaml(**overrides):
    doc = textwrap.dedent(
        """
        version: 1
        concepts:
          revenue:
            statement: INCOME
            unit: USD
            labels: {TSLA: ["Total revenues"]}
        """
    )
    return doc


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("version: 2", "version"),
        ("    bogus_key: 1\n", "unknown keys"),
        ("            unit: EUR", "bad unit"),
        ("            statement: EQUITY", "bad statement"),
    ],
)
def test_loader_rejects_bad_documents(tmp_path, mutation, message):
    doc = _base_yaml()
    if mutation.startswith("version"):
        doc = doc.replace("version: 1", mutation)
    elif "bogus" in mutation:
        doc += mutation
    elif "EUR" in mutation:
        doc = doc.replace("unit: USD", "unit: EUR")
    else:
        doc = doc.replace("statement: INCOME", "statement: EQUITY")
    path = tmp_path / "concepts.yaml"
    path.write_text(doc)
    with pytest.raises(d.DictionaryError, match=message):
        d.load(path)


def test_loader_rejects_asymmetric_pair(tmp_path):
    doc = textwrap.dedent(
        """
        version: 1
        concepts:
          a:
            statement: INCOME
            unit: USD
            labels: {TSLA: ["A"]}
            disambiguate_from: [b]
          b:
            statement: INCOME
            unit: USD
            labels: {TSLA: ["B"]}
        disambiguation_pairs:
          - [a, b]
        """
    )
    path = tmp_path / "concepts.yaml"
    path.write_text(doc)
    with pytest.raises(d.DictionaryError, match="not mirrored"):
        d.load(path)


def test_loader_rejects_unpaired_disambiguate_from(tmp_path):
    doc = textwrap.dedent(
        """
        version: 1
        concepts:
          a:
            statement: INCOME
            unit: USD
            labels: {TSLA: ["A"]}
            disambiguate_from: [b]
          b:
            statement: INCOME
            unit: USD
            labels: {TSLA: ["B"]}
            disambiguate_from: [a]
        """
    )
    path = tmp_path / "concepts.yaml"
    path.write_text(doc)
    with pytest.raises(d.DictionaryError, match="without a disambiguation_pairs"):
        d.load(path)
