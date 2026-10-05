"""Capture counters. Counts only; no label carries content or a line key."""

from __future__ import annotations

from typing import Final

from opentelemetry import metrics

_meter = metrics.get_meter("mdx.note.meeting")

meetings_started = _meter.create_counter(
    "mdx_note_meetings_started_total",
    description="Notes opened at record start (labels: meeting_type, has_calendar)",
    unit="1",
)
transcripts_attached = _meter.create_counter(
    "mdx_note_meeting_transcripts_attached_total",
    description="Transcripts attached to a live meeting note (label: device_same)",
    unit="1",
)
user_lines = _meter.create_counter(
    "mdx_note_user_lines_total",
    description="Captures by how much the author typed (label: bucket)",
    unit="1",
)
user_line_state = _meter.create_counter(
    "mdx_note_user_line_state_total",
    description="User lines the recording did or did not back up (label: state)",
    unit="1",
)
states_swept = _meter.create_counter(
    "mdx_note_meeting_state_swept_total",
    description="Captures reclaimed as no_audio by the sweeper",
    unit="1",
)

# "Did the author type at all, a little, or properly", as labels.
_BUCKETS: Final = ((0, "0"), (2, "1-2"), (9, "3-9"))


def line_bucket(count: int) -> str:
    for ceiling, label in _BUCKETS:
        if count <= ceiling:
            return label
    return "10+"
