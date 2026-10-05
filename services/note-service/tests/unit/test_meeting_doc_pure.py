"""Two pure rules: agenda extraction and line anchoring.

No DB, no app — text in, structure out.
"""

from __future__ import annotations

from note_service.domain.meeting_doc.agenda import agenda_lines
from note_service.domain.meeting_doc.user_notes import (
    UserLine,
    Window,
    anchor_lines,
    coverage_states,
    line_key,
    split_lines,
    with_times,
)

# ── Agenda from a calendar description ──────────────────────────────


def test_agenda_from_a_bulleted_description_drops_the_dial_in() -> None:
    description = (
        "Hi all, quick sync before the release.\n"
        "\n"
        "Agenda:\n"
        "- Q3 pipeline review\n"
        "- Pricing for the Berlin account\n"
        "- Hiring plan for Q4\n"
        "\n"
        "Join Zoom Meeting\n"
        "https://zoom.us/j/1234567890\n"
        "Meeting ID: 123 456 7890\n"
        "Passcode: 4711\n"
        "One tap mobile: +49 30 12345678\n"
    )
    assert agenda_lines(description) == (
        "Q3 pipeline review",
        "Pricing for the Berlin account",
        "Hiring plan for Q4",
    )


def test_agenda_reads_a_numbered_list_without_a_heading() -> None:
    assert agenda_lines("1. Budget\n2. Timeline\n3. Owners") == (
        "Budget",
        "Timeline",
        "Owners",
    )


def test_agenda_reads_html_descriptions() -> None:
    # Google hands descriptions over with markup in them.
    html = "<p>Agenda:</p><ul><li>Renewal terms</li><li>Support SLA</li></ul>"
    assert agenda_lines(html) == ("Renewal terms", "Support SLA")


def test_no_list_means_no_agenda() -> None:
    # An invite that is a link and a room number invents nothing.
    assert agenda_lines("Let's catch up. https://meet.google.com/abc-defg-hij") == ()
    assert agenda_lines("") == ()
    assert agenda_lines(None) == ()


def test_a_single_bullet_is_not_a_list() -> None:
    assert agenda_lines("- Just the one thing") == ()


def test_agenda_caps_lines_and_length() -> None:
    long_topic = "x" * 400
    lines = agenda_lines("\n".join(f"- {i} {long_topic}" for i in range(40)))
    assert len(lines) == 20
    assert all(len(line) <= 160 for line in lines)


def test_agenda_drops_signatures_and_footers() -> None:
    assert agenda_lines(
        "Agenda:\n- Renewal terms\n- Support SLA\n--\nSent from my iPhone\nUnsubscribe\n"
    ) == ("Renewal terms", "Support SLA")


# ── The author's lines ──────────────────────────────────────────────


def test_split_lines_keeps_the_text_verbatim_and_drops_duplicates() -> None:
    lines = split_lines("- Ask about budget\n\n  Tom hesitated here  \n- ask about budget.")
    assert [line.text for line in lines] == ["- Ask about budget", "  Tom hesitated here"]
    # Bullet, case, trailing period and spacing do not change identity.
    assert lines[0].line_key == line_key("Ask about budget")


def test_split_lines_caps() -> None:
    assert len(split_lines("\n".join(f"line {i}" for i in range(600)))) == 500


def _windows() -> list[Window]:
    return [
        Window(0, 0, 60_000, "Welcome everyone, let us start with the roadmap."),
        Window(1, 60_000, 120_000, "The budget for next year is fourteen thousand euros."),
        Window(2, 120_000, 180_000, "Hiring: two engineers in Berlin before December."),
    ]


def test_a_timed_line_anchors_to_what_was_said_before_it() -> None:
    # Typed at 2:10 — the budget window (1:00–2:00) is behind it and is
    # what the author was reacting to.
    lines = [UserLine(text="budget 40k?", line_key="k1", position=0, offset_ms=130_000)]
    anchors = anchor_lines(lines, _windows())
    assert 1 in anchors["k1"]


def test_a_line_without_a_time_falls_back_to_the_words() -> None:
    lines = [UserLine(text="hiring in Berlin", line_key="k1", position=0)]
    assert anchor_lines(lines, _windows())["k1"][0] == 2


def test_a_line_about_nothing_that_was_said_anchors_nowhere() -> None:
    lines = [UserLine(text="remember to water the plants", line_key="k1", position=0)]
    assert anchor_lines(lines, _windows())["k1"] == ()


def test_a_timed_line_outside_every_window_falls_back_to_the_words() -> None:
    # Typed long after the recording stopped (pasted in later).
    lines = [UserLine(text="hiring in Berlin", line_key="k1", position=0, offset_ms=9_000_000)]
    assert anchor_lines(lines, _windows())["k1"] == (2,)


def test_no_windows_means_no_anchors_rather_than_an_error() -> None:
    lines = [UserLine(text="anything", line_key="k1", position=0)]
    assert anchor_lines(lines, [])["k1"] == ()


def test_with_times_joins_the_sidecar() -> None:
    lines = split_lines("first\nsecond")
    timed = with_times(lines, {lines[0].line_key: 4_000})
    assert timed[0].offset_ms == 4_000
    assert timed[1].offset_ms is None


def test_every_line_gets_exactly_one_coverage_state() -> None:
    lines = split_lines("budget 40k\nplants")
    states = coverage_states(lines, supported={lines[0].line_key})
    assert states == {lines[0].line_key: "supported", lines[1].line_key: "unsupported"}
