"""User-visible timings from client events (sprint 3, B4). Pure.

- ``time_to_transcript_seconds`` (and speaker labels, notes) = the display event's client wall
  time corrected by its stored offset, minus ``submitted_at`` (a server time).
- ``user_wait_seconds`` = the final displayed result − the stop/import, on the client's own
  clock when one device saw both (the offset cancels); across two devices on server-corrected
  times, flagged ``cross_device``.
A negative result means the clocks disagree beyond correction: stored as null + ``error``,
never as a made-up zero."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

_DISPLAY = {
    "time_to_transcript_seconds": "transcript_displayed",
    "time_to_speaker_labels_seconds": "speaker_labels_displayed",
    "time_to_notes_seconds": "notes_displayed",
}
_STARTS = ("recording_stopped", "import_submitted")
# The final result a user waits for, best first.
_ENDS = ("notes_displayed", "speaker_labels_displayed", "transcript_displayed")


@dataclass(frozen=True)
class Event:
    event: str
    client: str
    client_wall_utc: datetime
    estimated_clock_offset_ms: int

    @property
    def corrected(self) -> datetime:
        return self.client_wall_utc + timedelta(milliseconds=self.estimated_clock_offset_ms)


def derive(
    events: Iterable[Event], submitted_at: datetime | None
) -> tuple[dict[str, Any], dict[str, str]]:
    """``(fields, reasons)`` for the run; a field without events is left out (stays as is)."""
    first: dict[str, Event] = {}
    for e in sorted(events, key=lambda e: e.client_wall_utc):
        first.setdefault(e.event, e)
    fields: dict[str, Any] = {}
    reasons: dict[str, str] = {}

    def put(name: str, seconds: float | None) -> None:
        if seconds is None:
            return
        if seconds < 0:
            fields[name] = None
            reasons[name] = "error"
        else:
            fields[name] = round(seconds, 3)

    if submitted_at is not None:
        for name, event in _DISPLAY.items():
            if event in first:
                put(name, (first[event].corrected - submitted_at).total_seconds())
    start = next((first[e] for e in _STARTS if e in first), None)
    end = next((first[e] for e in _ENDS if e in first), None)
    if start is not None and end is not None:
        same = start.client == end.client
        delta = (
            end.client_wall_utc - start.client_wall_utc if same else end.corrected - start.corrected
        )
        put("user_wait_seconds", delta.total_seconds())
        fields["user_wait_cross_device"] = not same
    return fields, reasons
