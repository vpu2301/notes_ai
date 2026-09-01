"""GET /v1/search/tips — what search does and does not do (sprint 15).

ADR-0021 accepted `simple` FTS with no stemming and promised the honest
user-facing explanation this sprint. The FE renders this content
verbatim so its copy can never drift from backend behaviour (the
core-service /note-structures motivation — but typed models, not bare
dicts). Static, versioned with the code: when search behaviour changes,
the tips change in the same PR.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict

from auth import Claims

from ..deps import requires_any

router = APIRouter(prefix="/v1/search", tags=["search"])


class SearchTip(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    title: str
    body: str


class SearchTipsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: Literal["uk", "en"]
    tips: list[SearchTip]


_TIPS: dict[str, list[SearchTip]] = {
    "uk": [
        SearchTip(
            key="no_stemming",
            title="Пошук за точною формою слова",
            body=(
                "Пошук не відмінює слова: «зустріч» не знайде «зустрічі». "
                "Шукайте за основою слова або спробуйте кілька форм."
            ),
        ),
        SearchTip(
            key="synonyms",
            title="Синоніми та абревіатури розкриваються автоматично",
            body=(
                "Абревіатури автоматично розширюються до повних форм і "
                "навпаки: «КП» знайде «комерційна пропозиція». Знайдені "
                "розширення показуються під полем пошуку. Вимкнути можна "
                "параметром «точний пошук» (expand=false)."
            ),
        ),
        SearchTip(
            key="filters_and",
            title="Фільтри поєднуються через «І»",
            body=(
                "Автор, статус і дати звужують результат одночасно: кожен "
                "доданий фільтр зменшує список."
            ),
        ),
        SearchTip(
            key="whole_words",
            title="Пошук за цілими словами",
            body=(
                "Запит збігається з цілими словами тексту, а не з частинами: "
                "«марк» не знайде «маркетинг». Спробуйте повне слово або "
                "кілька його форм."
            ),
        ),
    ],
    "en": [
        SearchTip(
            key="no_stemming",
            title="Search matches exact word forms",
            body=(
                "Search does not stem words: 'meeting' will not match "
                "'meetings'. Search by the word stem yourself or try "
                "several forms."
            ),
        ),
        SearchTip(
            key="synonyms",
            title="Synonyms and abbreviations expand automatically",
            body=(
                "Abbreviations expand to full forms and back: 'QBR' finds "
                "'quarterly business review'. Applied expansions are shown "
                "under the search box; disable with exact search "
                "(expand=false)."
            ),
        ),
        SearchTip(
            key="filters_and",
            title="Filters compose with AND",
            body=(
                "Author, status and dates narrow the result together: every "
                "added filter shrinks the list."
            ),
        ),
        SearchTip(
            key="whole_words",
            title="Whole-word matching",
            body=(
                "Queries match whole words, not fragments: 'mark' will not "
                "find 'marketing'. Try the full word or several of its forms."
            ),
        ),
    ],
}


@router.get("/tips", response_model=SearchTipsResponse)
async def get_search_tips(
    claims: Annotated[
        Claims,
        Depends(requires_any(("note.read", "note"), ("stats.read", "tenant"))),
    ],
    language: Annotated[Literal["uk", "en"], Query()] = "uk",
) -> SearchTipsResponse:
    return SearchTipsResponse(language=language, tips=_TIPS[language])
