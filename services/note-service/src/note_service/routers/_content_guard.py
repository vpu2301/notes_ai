"""Shared write-path guard: sprint-13 field-metadata validation.

Used by every route that accepts a full ``NoteContent`` body
(create / draft PUT / amend). Raises RFC-9457-style 422s mirroring the
finalize-validation contract: ``code`` is the first problem's code
(``field_metadata_invalid`` | ``choice_value_unknown``) and
``problems`` lists every section-addressed failure.
"""

from __future__ import annotations

from fastapi import HTTPException, status

from note_models import NoteContent

from ..domain.content_metadata import check_content_metadata


async def ensure_valid_field_metadata(conn: object, *, content: NoteContent) -> None:
    problems = await check_content_metadata(conn, content=content)
    if problems:
        exc = HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Note content failed field-metadata validation.",
        )
        exc.problem_extras = {  # type: ignore[attr-defined]
            "code": problems[0].code,
            "problems": [p.as_dict() for p in problems],
        }
        raise exc
