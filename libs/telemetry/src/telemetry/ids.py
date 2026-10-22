"""Run and recording identifiers (CORRELATION.md §1–2).

``recording_id`` is ``transcription_jobs.id``: one upload makes exactly one job row, and every
later artefact (rediarize revisions, notes, regenerations) references it. No parallel id."""

from __future__ import annotations

from uuid import UUID, uuid4


def new_run_id() -> UUID:
    return uuid4()


def recording_id_for_job(job_id: UUID) -> UUID:
    """The recording a transcription job belongs to: the job itself."""
    return job_id
