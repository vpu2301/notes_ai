"""Label → display-name mapping; neutral ``SPEAKER_N`` defaults until the client names speakers."""

from __future__ import annotations

from dataclasses import dataclass, field

UNKNOWN = "UNKNOWN"

DEFAULT_SPEAKER_NAMES: dict[str, str] = {
    "S1": "SPEAKER_1",
    "S2": "SPEAKER_2",
}


def default_name(label: str) -> str:
    """``S<n>`` → ``SPEAKER_<n>``; anything else passes through unchanged."""
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
    """Per-session label → display-name state; unnamed labels keep their defaults."""

    names: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_SPEAKER_NAMES))
    manual: bool = False

    def name_for(self, label: str | None) -> str | None:
        if label is None:
            return None
        return self.names.get(label, default_name(label))

    def set_names(self, mapping: dict[str, str]) -> None:
        """Apply the client's naming; authoritative until the next mapping."""
        self.names.update({k: v for k, v in mapping.items() if v})
        self.manual = True

    @property
    def current(self) -> SpeakerMapping:
        return SpeakerMapping(mapping=dict(self.names), manual=self.manual)
