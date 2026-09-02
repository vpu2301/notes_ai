"""The note follows the transcript's language (auto-detected jobs)."""

from __future__ import annotations

import pytest

from note_service.routers import notes_from_transcript as rft


class _Conn:
    pass


@pytest.fixture
def catalogue(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[str]]:
    # Language → candidate "ids" (the shape is irrelevant to the helper).
    cat = {"en": ["meeting_notes"], "uk": ["meeting_notes_uk"]}

    async def _load(conn, *, language):  # noqa: ANN001
        return cat.get(language, [])

    monkeypatch.setattr(rft.template_match, "load_candidates", _load)
    return cat


async def test_templates_in_the_transcripts_language_win(catalogue: dict[str, list[str]]) -> None:
    candidates, language = await rft._candidates_for_language(_Conn(), "uk")  # type: ignore[arg-type]
    assert (candidates, language) == (["meeting_notes_uk"], "uk")


async def test_language_without_templates_falls_back_to_english(
    catalogue: dict[str, list[str]],
) -> None:
    # A German recording under an auto-detected job: no de catalogue yet.
    candidates, language = await rft._candidates_for_language(_Conn(), "de")  # type: ignore[arg-type]
    assert (candidates, language) == (["meeting_notes"], "en")


async def test_empty_english_catalogue_stays_empty(catalogue: dict[str, list[str]]) -> None:
    catalogue["en"].clear()
    candidates, language = await rft._candidates_for_language(_Conn(), "en")  # type: ignore[arg-type]
    assert (candidates, language) == ([], "en")
