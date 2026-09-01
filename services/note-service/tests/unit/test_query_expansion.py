"""Query-expansion assembly — pure logic, no DB."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from note_service.domain.query_expansion import (
    MAX_EXPANSIONS,
    ExpandedQuery,
    assemble_tsquery,
)
from note_service.domain.search import SearchFilters, _fts_clause

G_KP = uuid4()
G_AT = uuid4()


def _row(group_id, term, lexemes) -> dict[str, Any]:
    return {"group_id": group_id, "term": term, "lexemes": lexemes}


KP_ROWS = [
    _row(G_KP, "КП", ["кп"]),
    _row(G_KP, "комерційна пропозиція", ["комерційна", "пропозиція"]),
    _row(G_KP, "offer", ["offer"]),
]


def test_single_abbreviation_expands_to_or_group():
    result = assemble_tsquery(["кп"], KP_ROWS)
    assert result.tsquery == "('кп' | ('комерційна' & 'пропозиція') | 'offer')"
    assert result.groups_used == 1
    assert "комерційна пропозиція" in result.expanded_terms


def test_full_form_expands_back_to_abbreviation():
    result = assemble_tsquery(["комерційна", "пропозиція"], KP_ROWS)
    # Each lexeme of the multi-word form gets the group's alternatives —
    # a document containing only «КП» satisfies both conjuncts.
    assert result.tsquery == (
        "('комерційна' | 'кп' | ('комерційна' & 'пропозиція') | 'offer')"
        " & "
        "('пропозиція' | 'кп' | ('комерційна' & 'пропозиція') | 'offer')"
    )
    assert result.groups_used == 1


def test_unmatched_lexemes_stay_plain():
    result = assemble_tsquery(["квартальний", "звіт"], KP_ROWS)
    assert result.tsquery == "'квартальний' & 'звіт'"
    assert result.groups_used == 0
    assert result.expanded_terms == []


def test_short_lexemes_never_expand():
    # «з» must not drag in the з/п = заробітна плата group.
    rows = [_row(G_AT, "з/п", ["з"]), _row(G_AT, "заробітна плата", ["заробітна", "плата"])]
    result = assemble_tsquery(["з", "командою"], rows)
    assert result.tsquery == "'з' & 'командою'"
    assert result.groups_used == 0


def test_apostrophe_lexemes_quoted_safely():
    rows = [
        _row(G_AT, "зв'язок з клієнтом", ["зв'язок", "клієнтом"]),
        _row(G_AT, "комунікація", ["комунікація"]),
    ]
    result = assemble_tsquery(["комунікація"], rows)
    assert result.tsquery == "('комунікація' | ('зв''язок' & 'клієнтом'))"


def test_expansion_cap_holds_on_adversarial_query():
    rows = []
    lexemes = []
    for i in range(MAX_EXPANSIONS + 4):
        gid = uuid4()
        lex = f"абр{i}"
        lexemes.append(lex)
        rows.append(_row(gid, f"АБР{i}", [lex]))
        rows.append(_row(gid, f"повна форма {i}", [f"повна{i}", f"форма{i}"]))
    result = assemble_tsquery(lexemes, rows)
    assert result.tsquery is not None
    # Exactly MAX_EXPANSIONS lexemes got an OR-group; the overflow stayed
    # plain. An expanded conjunct contains the group's full form; a plain
    # one is just the quoted lexeme.
    or_groups = result.tsquery.count(" | ")
    assert result.groups_used == MAX_EXPANSIONS
    assert or_groups == MAX_EXPANSIONS
    for i in range(MAX_EXPANSIONS, MAX_EXPANSIONS + 4):
        assert f"'абр{i}'" in result.tsquery
        assert f"повна{i}" not in result.tsquery


def test_empty_lexemes_yield_none():
    assert assemble_tsquery([], KP_ROWS) == ExpandedQuery(tsquery=None)


def test_same_term_in_two_groups_unions():
    # ПЗ: програмне забезпечення AND платіжне зобов'язання — deliberate.
    g_soft, g_pay = uuid4(), uuid4()
    rows = [
        _row(g_soft, "ПЗ", ["пз"]),
        _row(g_soft, "програмне забезпечення", ["програмне", "забезпечення"]),
        _row(g_pay, "ПЗ", ["пз"]),
        _row(g_pay, "платіжне зобов'язання", ["платіжне", "зобов'язання"]),
    ]
    result = assemble_tsquery(["пз"], rows)
    assert result.tsquery is not None
    assert "'забезпечення'" in result.tsquery
    assert "'платіжне'" in result.tsquery
    assert result.groups_used == 2


# ── search.py FTS clause selection ──────────────────────────────────


def test_fts_clause_plainto_without_expansion():
    args: list = []
    clause = _fts_clause(SearchFilters(q="КП"), args)
    assert clause is not None
    assert clause[0] == "v.search_vector @@ plainto_tsquery('simple', $1)"
    assert args == ["КП"]


def test_fts_clause_to_tsquery_with_expansion():
    args: list = ["prior-arg"]
    filters = SearchFilters(q="КП", ts_query="('кп' | 'offer')")
    clause = _fts_clause(filters, args)
    assert clause is not None
    assert clause[0] == "v.search_vector @@ to_tsquery('simple', $2)"
    assert clause[1] == "to_tsquery('simple', $2)"
    assert args == ["prior-arg", "('кп' | 'offer')"]


def test_fts_clause_absent_without_q():
    args: list = []
    assert _fts_clause(SearchFilters(), args) is None
    assert args == []
