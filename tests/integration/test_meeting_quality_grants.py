"""Migration 0067 on a live database: funnel_reader (the admin dashboard's
role) reads the quality numbers and is refused every content column."""

from __future__ import annotations

import os

import asyncpg
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DB_INTEGRATION") != "1", reason="needs the dev database"
)
READER_DSN = os.environ.get(
    "FUNNEL_READER_DSN", "postgresql://funnel_reader:funnel_reader@localhost:5432/notes"
)

ALLOWED = [
    "SELECT quality, language, model, detected_language, error_kind, entity_unify_status,"
    " corrections_rev FROM transcription_jobs LIMIT 1",
    "SELECT job_id, backend, model_id, prompt_version, windows_failed, error_kind"
    " FROM note_generations LIMIT 1",
    "SELECT job_id, source, status, confidence FROM transcript_corrections LIMIT 1",
]
REFUSED = [
    "SELECT vocabulary_hint FROM transcription_jobs LIMIT 1",
    "SELECT speaker_names FROM transcription_jobs LIMIT 1",
    "SELECT error_detail FROM transcription_jobs LIMIT 1",
    "SELECT failed_ranges FROM note_generations LIMIT 1",
    "SELECT to_text FROM transcript_corrections LIMIT 1",
    "SELECT from_forms FROM transcript_corrections LIMIT 1",
    "SELECT occurrences FROM transcript_corrections LIMIT 1",
    "UPDATE transcription_jobs SET quality = NULL WHERE false",
]


async def test_reader_sees_numbers_and_never_content() -> None:
    conn = await asyncpg.connect(READER_DSN)
    try:
        for sql in ALLOWED:
            await conn.fetch(sql)
        for sql in REFUSED:
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await conn.fetch(sql)
    finally:
        await conn.close()
