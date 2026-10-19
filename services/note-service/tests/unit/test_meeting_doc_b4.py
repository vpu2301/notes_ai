"""Sprint B4 — the claims table (who claims what, the speaker's verdict, the seconds behind
it) and the provenance of every written line (verbatim, paraphrase, composed)."""

from __future__ import annotations

from types import SimpleNamespace

from note_service.domain import client_view, pdf_richtext
from note_service.domain.meeting_doc import render, roles, schema, support, types
from note_service.domain.meeting_doc.render import Line
from note_service.domain.meeting_doc.verify import VerifiedFact
from note_service.jobs import generate_note


def _vf(text: str, start_ms: int = 0, **kw: object) -> VerifiedFact:
    fields = {
        "kind": schema.KEY_POINT,
        "text": text,
        "quote": text,
        "turn": 0,
        "start_ms": start_ms,
        "end_ms": start_ms + 1_000,
        "speaker_label": "SPEAKER_1",
        "speaker_name": None,
    }
    fields.update(kw)
    return VerifiedFact(**fields)  # type: ignore[arg-type]


# r02-shaped relayed claims, in the order the recording said them.
R02 = [
    _vf(
        "Die Briefwahl werde manipuliert",
        401_000,
        certainty="unproven",
        attributed_to="Donald Trump",
        quote="Trump behauptet, die Briefwahl werde manipuliert, was unbelegt ist.",
    ),
    _vf(
        "Menschen ohne Staatsbürgerschaft wählten massenhaft",
        422_000,
        certainty="reported",
        attributed_to="Donald Trump",
        quote="Er sagt, Menschen ohne Staatsbürgerschaft wählten massenhaft; laut Untersuchungen ist das äußerst selten.",
    ),
    _vf(
        "Die Wahl 2020 sei gestohlen worden",
        490_000,
        certainty="refuted",
        attributed_to="Donald Trump",
        quote="Die Wahl 2020 sei gestohlen worden, eine Behauptung, die längst widerlegt ist.",
    ),
    _vf(
        "Eine Machtübernahme der radikalen Linken drohe",
        366_000,
        certainty="allegation",
        attributed_to="Republikaner",
        quote="Die Republikaner warnen vor einer Machtübernahme der radikalen Linken.",
    ),
]


# ── T1: the table ────────────────────────────────────────────────────


def test_r02_shaped_facts_give_four_rows_in_time_order_with_the_verdicts() -> None:
    text, lines = render._claims_block(render.claim_facts(R02), "de")
    rows = [ln for ln in lines if ln.kind == "claim"]
    assert len(rows) == 4 and [ln.kind for ln in lines[:2]] == ["heading", "heading"]
    assert lines[0].text.startswith("| Wer | Behauptung | Urteil der Sprecherin | Beleg |")
    assert [ln.fact_ids[0] for ln in rows] == [
        R02[3].item_key,
        R02[0].item_key,
        R02[1].item_key,
        R02[2].item_key,
    ]
    assert "| 06:41 |" in rows[1].text and "unbelegt" in rows[1].text
    assert "äußerst selten" in rows[2].text and rows[2].text.startswith("| Donald Trump |")
    assert "widerlegt" in rows[3].text and "| 08:10 |" in rows[3].text
    assert "Vorwurf" in rows[0].text and "| 06:06 |" in rows[0].text
    assert text.count("\n") == 5


def test_the_verdict_cell_is_the_label_plus_the_presenters_shortest_clause() -> None:
    assert render.verdict_cell(R02[2], "de") == "widerlegt — die längst widerlegt ist"
    assert (
        render.verdict_cell(R02[1], "de")
        == "Behauptung — laut Untersuchungen ist das äußerst selten"
    )
    plain = _vf("x", certainty="reported", attributed_to="A", quote="Er sagt, es regne morgen.")
    assert render.verdict_cell(plain, "de") == "Behauptung"
    assert support.verdict_clause("Nothing here.", "en") == ""
    assert (
        support.verdict_clause("It is false, he says, and studies show it is rare.", "en")
        == "It is false"
    )


def test_a_routed_kind_and_a_plain_fact_are_not_claims() -> None:
    objection = _vf("too expensive", certainty="reported", attributed_to="Client", kind="objection")
    plain = _vf("the levy is three percent", certainty="fact")
    hedged_unheld = _vf("the levy may rise", certainty="prediction")
    assert render.claim_facts(
        [objection, plain, hedged_unheld, R02[0]], routed_kinds={"objection"}
    ) == [R02[0]]


def _sections(
    facts: list[VerifiedFact], *, family_type: str | None = None
) -> list[render.RenderedSection]:
    return render.render_sections(
        facts,
        role_by_key={},
        language="de",
        family_type=family_type,
        kind_roles={**types.GENERIC_KINDS, "objection": roles.REQUESTS},
    )


def test_a_meeting_writes_the_table_from_two_rows_and_a_narrated_piece_from_one() -> None:
    one = [R02[0], _vf("Der Haushalt wird am Montag beschlossen", 10_000)]
    assert not [s for s in _sections(one) if s.role == roles.CLAIMS]
    narrated = [s for s in _sections(one, family_type="broadcast") if s.role == roles.CLAIMS]
    assert len(narrated) == 1 and narrated[0].title == "Behauptungen"
    assert narrated[0].section_key == "claims"
    two = [s for s in _sections([R02[0], R02[2]]) if s.role == roles.CLAIMS]
    assert len(two) == 1 and sum(1 for ln in two[0].lines if ln.kind == "claim") == 2


# ── T2: provenance ───────────────────────────────────────────────────


def test_provenance_follows_the_render_rule() -> None:
    a = _vf("the levy rises in March", 1000)
    b = _vf("the council meets on Monday", 2000)
    copy = _vf("we will win this vote", 3000, copied=True)
    by_id = {f.item_key: f for f in (a, b, copy)}
    assert (
        render.provenance_of(
            Line(
                "The levy rises in March and the council meets.",
                "summary",
                (a.item_key, b.item_key),
            ),
            by_id,
        )
        == "composed"
    )
    assert (
        render.provenance_of(Line("- In March the levy goes up.", "bullet", (a.item_key,)), by_id)
        == "paraphrase"
    )
    assert (
        render.provenance_of(Line("- we will win this vote", "bullet", (copy.item_key,)), by_id)
        == "verbatim"
    )
    assert (
        render.provenance_of(Line("- The levy rises in March", "bullet", (a.item_key,)), by_id)
        == "verbatim"
    )
    assert render.provenance_of(Line("## Heading", "heading"), by_id) is None
    assert render.provenance_of(Line("- orphan", "bullet", ("nope",)), by_id) is None


def test_every_rendered_line_with_evidence_carries_its_provenance() -> None:
    facts = [*R02, _vf("Die Abstimmung ist am Donnerstag", 1000)]
    sections = _sections(facts, family_type="broadcast")
    for section in sections:
        for ln in section.lines:
            if ln.fact_ids and ln.kind != "heading":
                assert ln.provenance in render.PROVENANCES, (section.role, ln.text)
            else:
                assert ln.provenance is None


def test_the_item_row_carries_provenance_and_a_claim_rows_verdict() -> None:
    by_id = {f.item_key: f for f in R02}
    _text, lines = render._claims_block(render.claim_facts(R02), "de")
    refuted_row = next(ln for ln in lines if ln.fact_ids == (R02[2].item_key,))
    row = generate_note.line_row(refuted_row, "claims", "written", by_id)
    assert row is not None and row["kind"] == "claim" and row["provenance"] == "paraphrase"
    assert row["payload"] == {"verdict": "widerlegt — die längst widerlegt ist"}
    summary = Line("Zwei Dinge auf einmal.", "summary", (R02[0].item_key, R02[1].item_key))
    composed = generate_note.line_row(summary, "gen:overview", "written", by_id)
    assert (
        composed is not None
        and composed["provenance"] == "composed"
        and composed["payload"] is None
    )


# ── T2: the surfaces ─────────────────────────────────────────────────


def test_a_client_version_keeps_the_claims_table() -> None:
    assert types.CLAIMS in client_view.CLIENT_ROLES
    assert roles.role_of("claims") == roles.CLAIMS


def test_the_pdf_prints_a_marker_after_a_marked_line() -> None:
    marks = {"- the levy rises": "(paraphrase)"}
    html = pdf_richtext.render_rich_text(
        "- the levy rises\n- nothing known\n\nA composed sentence.",
        line_mark=lambda raw: marks.get(raw.strip(), "(composed)" if raw.startswith("A ") else ""),
    )
    assert '<li>the levy rises <span class="prov">(paraphrase)</span></li>' in html
    assert "<li>nothing known</li>" in html
    assert 'A composed sentence. <span class="prov">(composed)</span></p>' in html
    assert "prov" not in pdf_richtext.render_rich_text("- the levy rises")


def test_the_view_reads_provenance_and_verdict_from_the_row() -> None:
    from note_service.routers import notes_generation as ng

    assert ng._line_provenance("composed") == "composed" and ng._line_provenance("x") is None
    assert ng._verdict('{"verdict": "widerlegt"}') == "widerlegt" and ng._verdict(None) is None
    assert SimpleNamespace  # the rig tests cover the route itself
