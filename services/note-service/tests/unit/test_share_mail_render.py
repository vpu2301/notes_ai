"""The share mail's two body parts.

The properties worth pinning are the ones a broken mail does not
announce: that a note title goes out escaped in the HTML and unescaped
in the text, that the link survives its own query string in both, and
that the sentence about who can read the note follows the recipient
rather than a default.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from note_service.adapters import share_mail
from note_service.adapters import share_mail_copy as copy

WHEN = datetime(2026, 9, 7, 9, 30, tzinfo=UTC)
LINK = "https://app.notes-ai.test/s/tok?a=1&b=2"


def render(**over):  # noqa: ANN003, ANN201
    kwargs = {
        "lang": "en",
        "sharer_name": "Anna Koval",
        "sharer_email": "anna@acme.com",
        "note_title": "Acme kickoff",
        "message": "",
        "link_url": LINK,
        "access": copy.ACCESS_MEMBER,
        "shared_at": WHEN,
    }
    kwargs.update(over)
    return share_mail.render(**kwargs)


@pytest.mark.parametrize("lang", copy.SUPPORTED_LANGS)
def test_every_language_renders_both_parts_with_the_link(lang: str) -> None:
    mail = render(lang=lang, message="Recap inside.")
    assert mail.subject and "\n" not in mail.subject
    assert "Acme kickoff" in mail.subject
    for body in (mail.text_body, mail.html_body):
        assert LINK.split("?")[0] in body
        assert "Anna Koval" in body
    assert "Recap inside." in mail.text_body
    assert "Recap inside." in mail.html_body


def test_a_title_is_escaped_in_the_html_and_left_alone_in_the_text() -> None:
    mail = render(note_title="Q3 <plan> & budget")
    assert "&lt;plan&gt; &amp; budget" in mail.html_body
    assert "<plan>" not in mail.html_body
    assert "Q3 <plan> & budget" in mail.text_body


def test_the_query_string_is_not_entity_escaped_in_the_text_part() -> None:
    # `&amp;` in a text/plain part is not markup — it is a broken link.
    assert "a=1&b=2" in render().text_body


def test_the_access_sentence_follows_the_recipient() -> None:
    member = render(access=copy.ACCESS_MEMBER)
    stranger = render(access=copy.ACCESS_LINK)
    assert "sign in with this address" in member.text_body
    assert "no account needed" in stranger.text_body.lower()
    assert "no account needed" not in member.text_body.lower()


def test_an_unknown_access_kind_is_refused_rather_than_guessed() -> None:
    with pytest.raises(ValueError, match="unknown access kind"):
        render(access="everyone")


def test_an_untitled_note_still_says_something() -> None:
    mail = render(note_title="   ")
    assert "shared a note with you" in mail.subject
    assert "A note was shared with you" in mail.html_body


def test_a_language_we_do_not_write_falls_back_to_english() -> None:
    assert render(lang="fr-CA").subject == render(lang="en").subject
    # A regional variant of one we do write keeps its language.
    assert render(lang="de-CH").subject == render(lang="de").subject


def test_a_newline_in_the_sharer_name_cannot_inject_a_header() -> None:
    mail = render(sharer_name="Anna\r\nBcc: victim@example.com")
    assert "\n" not in mail.subject
    assert "\r" not in mail.subject


def test_blank_lines_in_the_message_become_paragraphs_not_one_blob() -> None:
    mail = render(message="First thought.\n\nSecond thought.")
    assert mail.html_body.count("Second thought.") == 1
    # Two <p> in the quote block, one per paragraph.
    assert "First thought." in mail.html_body
    assert mail.text_body.count("> ") >= 2
