"""Sprint SQ3 — reads like a note: nothing renders that was not written,
every participant with a role, no line that adds nothing, a title from the
whole recording. Tests follow the work order's table."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from note_service.domain import note_title
from note_service.domain.meeting_doc import (
    compose,
    doclint,
    overview,
    pipeline,
    render,
    roles,
    roles_table,
    schema,
    support,
)
from note_service.domain.meeting_doc.doclint import LintContext
from note_service.domain.meeting_doc.render import Line, RenderedSection
from note_service.domain.meeting_doc.verify import Person, VerifiedFact
from note_service.domain.meeting_doc.windows import Turn
from note_service.jobs.generate_note import _title_context

MIN = 60_000


def _fact(text: str, start_ms: int, **kw: Any) -> VerifiedFact:
    return VerifiedFact(
        kind=kw.pop("kind", schema.KEY_POINT),
        text=text,
        quote=kw.pop("quote", "so wurde es in dem Gespräch erzählt"),
        turn=0,
        start_ms=start_ms,
        end_ms=start_ms + 1_000,
        speaker_label=kw.pop("speaker_label", "SPEAKER_1"),
        speaker_name=None,
        **kw,
    )


def _ctx(facts: list[VerifiedFact], minutes: float = 10) -> LintContext:
    return LintContext(
        language="de",
        speech_ms=int(minutes * MIN),
        recording_type="podcast_broadcast",
        facts={f.item_key: f for f in facts},
    )


# ── T1 nothing renders that was not written ─────────────────────────


@pytest.mark.parametrize("language", ["de", "en", "uk"])
@pytest.mark.parametrize(
    "certainty", ["prediction", "estimate", "proposal", "allegation", "opinion"]
)
def test_a_paragraph_gets_the_dash_and_a_bullet_keeps_the_colon(
    language: str, certainty: str
) -> None:
    fact = _fact("Iran griff im Jahr 2023 an", 0, certainty=certainty)
    phrase = support.CERTAINTY_PHRASES[language][certainty]
    paragraph = render.patch_claim("Iran griff 2023 an.", [fact], language, paragraph=True)
    bullet = render.patch_claim("Iran griff 2023 an.", [fact], language)
    assert paragraph == f"{phrase} — Iran griff 2023 an."
    assert bullet == f"{phrase}: Iran griff 2023 an."
    assert not doclint.speaker_shaped(Line(paragraph, "summary"))


def test_a_speaker_shaped_paragraph_fails_lint_and_is_repaired_with_a_dash() -> None:
    fact = _fact("Iran griff im Jahr 2023 an", 0)
    top = RenderedSection(
        roles.OVERVIEW_KEY,
        roles.SUMMARY,
        "Vorwurf: Iran griff 2023 an.",
        lines=(Line("Vorwurf: Iran griff 2023 an.", "summary", (fact.item_key,)),),
        facts=(fact,),
    )
    ctx = _ctx([fact])
    found = {f.rule for f in doclint.check([top], ctx)}
    assert "form.paragraph_colon_prefix" in found
    repaired, done = doclint.repair([top], ctx)
    texts = [ln.text for s in repaired for ln in s.lines]
    assert "Vorwurf — Iran griff 2023 an." in texts
    assert done["D-FORM"] >= 1
    assert not any(doclint.speaker_shaped(ln) for s in repaired for ln in s.lines)


def test_bullets_and_links_are_not_speaker_shaped() -> None:
    assert not doclint.speaker_shaped(Line("- Vorwurf: x y", "bullet"))
    assert not doclint.speaker_shaped(Line("https://example.org: x", "summary"))
    assert not doclint.speaker_shaped(Line("Es sprechen Anna und Ben.", "framing"))


def test_render_writes_no_presenter_paragraph() -> None:
    intro = _fact(
        "Felix stellt sich vor",
        0,
        kind=schema.INTRODUCTION,
        person=Person(name="Felix Holtermann", role="Reporter", organisation="Handelsblatt",
                      standing="guest"),
    )  # fmt: skip
    sections = render.render_sections(
        [intro], role_by_key={}, language="de", framing="Podcast-Folge.", presenter_lines=True
    )
    assert all(not ln.text.startswith(("Gast:", "Präsentiert von:", "Vorgestellt:"))
               for s in sections for ln in s.lines)  # fmt: skip


# ── T2 every participant, one line, with a role ─────────────────────


def _speaker(label: str, share: float, role: str, name: str | None = None,
             person: Person | None = None) -> roles_table.Speaker:  # fmt: skip
    return roles_table.Speaker(label, share, 10, 0.1, role, name, person)


def _table(*speakers: roles_table.Speaker) -> roles_table.RolesTable:
    return roles_table.RolesTable(speakers={s.label: s for s in speakers})


def test_the_r04_shaped_roster_names_three_people_once_each() -> None:
    """Narrator, expert and interviewee — the shape r04 has (synthetic
    names; the real recording stays out of the repo)."""
    expert = Person(name="Paul Weber", role="Experte für Cybersicherheit", organisation="")
    guest = Person(name="Mina Sadr", role="", organisation="Universität Bonn")
    table = _table(
        _speaker("S1", 0.55, roles_table.NARRATOR),
        _speaker("S2", 0.30, roles_table.EXPERT, "Paul Weber", expert),
        _speaker("S3", 0.12, roles_table.INTERVIEWEE, "Mina Sadr", guest),
        _speaker("S4", 0.01, roles_table.CLIP),
    )
    speakers, guests, others = compose.speakers_of(table, "de")
    text = overview.first_paragraph(
        language="de", recording_type="podcast_broadcast", subject="Hacker",
        speakers=speakers, guests=guests, others=others,
    )  # fmt: skip
    assert speakers == ["Erzähler/in", "Paul Weber (Experte für Cybersicherheit)"]
    assert others == ["Mina Sadr (Interviewpartner/in bei Universität Bonn)"]
    assert text.count("Paul Weber") == 1 and text.count("Mina Sadr") == 1
    assert text.index("Erzähler/in") < text.index("Paul Weber") < text.index("Mina Sadr")


def test_each_role_and_the_unnamed() -> None:
    host = _speaker("H", 0.4, roles_table.HOST, "Anna Berg")
    guest = _speaker("G", 0.3, roles_table.GUEST, "Felix Holtermann",
                     Person(name="Felix Holtermann", organisation="Handelsblatt"))  # fmt: skip
    quiet = _speaker("Q", 0.2, roles_table.PARTICIPANT)
    tiny = _speaker("T", 0.02, roles_table.PARTICIPANT)
    named = _speaker("N", 0.08, roles_table.PARTICIPANT, "Ben Ott")
    speakers, guests, others = compose.speakers_of(_table(host, guest, quiet, tiny, named), "de")
    assert speakers == ["Anna Berg (Moderator/in)"]
    assert guests == ["Felix Holtermann (Handelsblatt)"]
    assert others == ["Ben Ott", "eine weitere Person"]  # tiny is under 5 %
    _s, _g, en = compose.speakers_of(
        _table(quiet, _speaker("R", 0.2, roles_table.PARTICIPANT)), "en"
    )
    assert en == ["2 other people"]


def test_no_label_is_ever_written_for_a_person() -> None:
    table = _table(_speaker("SPEAKER_2", 0.3, roles_table.PARTICIPANT, "Speaker 2"))
    listed = [w for part in compose.speakers_of(table, "de") for w in part]
    assert listed == ["eine weitere Person"]


def test_an_introduction_with_an_expert_word_is_an_expert() -> None:
    turns = [Turn(n, "S1" if n % 3 else "S2", None, "Wir sprechen heute.", n * 10_000,
                  n * 10_000 + 9_000) for n in range(30)]  # fmt: skip
    intro = _fact("Paul stellt sich vor", 0, kind=schema.INTRODUCTION, speaker_label="S2",
                  person=Person(name="Paul Weber", role="Experte", self_introduction=True))  # fmt: skip
    table = roles_table.build(turns, [intro], "podcast_broadcast")
    assert table.role_of("S2") == roles_table.EXPERT
    assert roles_table.standing(intro, table) == "guest"


# ── T3 no line that adds nothing; introduce before describe ─────────


def _topic(title: str, lines: list[tuple[str, VerifiedFact]]) -> RenderedSection:
    rendered = tuple(Line(f"- {t}", "bullet", (f.item_key,)) for t, f in lines)
    return RenderedSection(
        roles.generated_key(title), roles.TOPICS, "\n".join(ln.text for ln in rendered),
        facts=tuple(f for _t, f in lines), title=title, lines=rendered,
    )  # fmt: skip


def test_a_subset_line_is_removed_and_the_specific_one_stays() -> None:
    a = _fact("Peter Thiel gründet 2004 Palantir in Palo Alto", 0)
    b = _fact("Thiel gründet Palantir", 60_000)
    section = _topic("Palantir und Peter Thiel", [(a.text, a), (b.text, b)])
    ctx = _ctx([a, b])
    assert "line.subset" in {f.rule for f in doclint.check([section], ctx)}
    repaired, _done = doclint.repair([section], ctx)
    texts = [ln.text for s in repaired for ln in s.lines]
    assert f"- {a.text}" in texts and f"- {b.text}" not in texts


def _with_ladder(facts: list[VerifiedFact]) -> RenderedSection:
    first, middle, last = overview.CONNECTIVES["de"]
    leads = [first, middle, last]
    lines = tuple(
        Line(f"{leads[n]} {f.text}.", "summary", (f.item_key,)) for n, f in enumerate(facts)
    )
    return RenderedSection(
        roles.OVERVIEW_KEY, roles.SUMMARY, "\n".join(ln.text for ln in lines),
        lines=lines, facts=tuple(facts),
    )  # fmt: skip


def test_a_ladder_that_cites_only_bullet_facts_is_removed() -> None:
    facts = [_fact(f"Alex Karp verkauft {1990 + n} Anteile an {n + 3} Investoren", n * MIN)
             for n in range(3)]  # fmt: skip
    sections = [_with_ladder(facts), _topic("Anteile von Alex Karp", [(f.text, f) for f in facts])]
    ctx = _ctx(facts)
    assert doclint._redundant_ladder(sections)
    assert "orient.ladder_redundant" in {f.rule for f in doclint.check(sections, ctx)}
    out = doclint._drop_filler(sections, ctx, doclint.Counter())
    top = next(s for s in out if s.section_key == roles.OVERVIEW_KEY)
    assert not doclint._ladder(top)


def test_a_ladder_with_a_new_fact_is_kept() -> None:
    facts = [_fact(f"Alex Karp verkauft {1990 + n} Anteile an {n + 3} Investoren", n * MIN)
             for n in range(3)]  # fmt: skip
    sections = [
        _with_ladder(facts),
        _topic("Anteile von Alex Karp", [(f.text, f) for f in facts[:2]]),
    ]
    assert not doclint._redundant_ladder(sections)


def test_the_introduction_comes_before_the_description() -> None:
    intro = _fact("Paul Weber wurde vorgestellt", 120_000, kind=schema.INTRODUCTION,
                  person=Person(name="Paul Weber", role="Experte"))  # fmt: skip
    told = _fact("Weber beschrieb den Angriff", 60_000)
    by_id = {f.item_key: f for f in (intro, told)}
    bullets: list[pipeline.Bullet] = [
        ("Weber beschrieb den Angriff auf die Server", [told.item_key], []),
        ("Paul Weber wurde als Experte vorgestellt", [intro.item_key], []),
    ]
    ordered = pipeline.introduce_first(bullets, by_id)
    assert ordered[0][1] == [intro.item_key]


# ── T4 title from the whole recording ───────────────────────────────


def test_a_type_word_title_is_rejected() -> None:
    assert doclint.type_words_only("Podcast-Folge")
    assert doclint.type_words_only("Episode eines Podcasts über eine Besprechung")
    assert not doclint.type_words_only("Handala: Irans Hacker und die Kindergärten")
    ctx = LintContext(language="de", speech_ms=0, title="Podcast-Folge")
    assert "title.generic" in {f.rule for f in doclint.check([], ctx)}
    result = {"language": "de", "text": "Podcast Folge über eine Besprechung " * 10}
    assert note_title.unsupported("Podcast-Folge über eine Besprechung", result) == "lint"


def test_thirds_sampling_on_6000_words() -> None:
    words = [f"w{i}" for i in range(6_000)]
    kept = note_title.sample({"text": " ".join(words)}).replace("…", "").split()
    thirds = {min(2, int(w[1:]) * 3 // 6_000) for w in kept}
    assert thirds == {0, 1, 2}
    assert len(kept) == note_title.SAMPLE_WORDS


def test_title_context_takes_facts_from_each_third() -> None:
    facts = [_fact(f"Fakt {n} über Palantir im Jahr {2000 + n}", n * MIN) for n in range(9)]
    document = SimpleNamespace(
        brief={"themes": ["Palantir", "Daten"]}, facts=facts, stats={"language": "de"}
    )
    themes, chosen = _title_context(document)
    assert themes == ["Palantir", "Daten"]
    assert len(chosen) == note_title.CONTEXT_FACTS
    picked = [int(t.split()[1]) for t in chosen]
    assert {n * 3 // 9 for n in picked} == {0, 1, 2}
    block = note_title.context_block(themes, chosen)
    assert block.startswith("Themes: Palantir; Daten")
