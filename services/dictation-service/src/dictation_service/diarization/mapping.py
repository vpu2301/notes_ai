"""Neutral speaker naming for conversation (meeting) sessions.

Diarization emits anonymous labels (``S1``/``S2``/``UNKNOWN``). This
module owns the label → display-name mapping. There is NO server-side
inference of who a speaker is: every label renders under a neutral
``SPEAKER_1..N`` default until the client names it via the
``set_speaker_mapping`` wire message, which is authoritative from the
moment received.
"""

from __future__ import annotations

from dataclasses import dataclass, field

UNKNOWN = "UNKNOWN"

#: Neutral default display names for the raw diarization labels.
DEFAULT_SPEAKER_NAMES: dict[str, str] = {
    "S1": "SPEAKER_1",
    "S2": "SPEAKER_2",
}


def default_name(label: str) -> str:
    """Neutral display name for a raw diarization label.

    ``S<n>`` → ``SPEAKER_<n>``; anything else (``UNKNOWN`` included)
    passes through unchanged.
    """
    if len(label) >= 2 and label[0] == "S" and label[1:].isdigit():
        return f"SPEAKER_{label[1:]}"
    return label


@dataclass(frozen=True)
class SpeakerMapping:
    """A snapshot of the current label → display-name mapping."""

    mapping: dict[str, str]
    manual: bool = False


@dataclass
class SpeakerNaming:
    """Per-session label → display-name state.

    Starts with the neutral ``SPEAKER_1..N`` defaults. ``set_names``
    (driven by the client's ``set_speaker_mapping``) replaces entries
    and marks the mapping manual; unnamed labels keep their defaults.
    """

    names: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_SPEAKER_NAMES))
    manual: bool = False

    def name_for(self, label: str | None) -> str | None:
        if label is None:
            return None
        return self.names.get(label, default_name(label))

    def set_names(self, mapping: dict[str, str]) -> None:
        """Apply the client's naming. Authoritative and permanent until
        the client sends another mapping."""
        self.names.update({k: v for k, v in mapping.items() if v})
        self.manual = True

    @property
    def current(self) -> SpeakerMapping:
        return SpeakerMapping(mapping=dict(self.names), manual=self.manual)
