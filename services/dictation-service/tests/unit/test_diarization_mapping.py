"""Neutral speaker naming (pure logic, no models).

Diarization labels stay anonymous (S1/S2/UNKNOWN); display names are
the SPEAKER_1..N defaults until the client supplies its own via
``set_speaker_mapping``. There is no server-side identity inference.
"""

from __future__ import annotations

from dictation_service.diarization.mapping import (
    DEFAULT_SPEAKER_NAMES,
    SpeakerNaming,
    default_name,
)


def test_default_names_are_neutral() -> None:
    assert default_name("S1") == "SPEAKER_1"
    assert default_name("S2") == "SPEAKER_2"
    assert default_name("S17") == "SPEAKER_17"
    assert default_name("UNKNOWN") == "UNKNOWN"
    assert DEFAULT_SPEAKER_NAMES == {"S1": "SPEAKER_1", "S2": "SPEAKER_2"}


def test_fresh_naming_serves_the_defaults() -> None:
    naming = SpeakerNaming()
    assert naming.manual is False
    assert naming.name_for("S1") == "SPEAKER_1"
    assert naming.name_for("S2") == "SPEAKER_2"
    assert naming.name_for(None) is None
    # Labels outside the seeded defaults still get a neutral name.
    assert naming.name_for("S3") == "SPEAKER_3"
    current = naming.current
    assert current.mapping == DEFAULT_SPEAKER_NAMES
    assert current.manual is False


def test_set_names_is_authoritative() -> None:
    naming = SpeakerNaming()
    naming.set_names({"S1": "Alice", "S2": "Bob"})
    assert naming.manual is True
    assert naming.name_for("S1") == "Alice"
    assert naming.name_for("S2") == "Bob"
    assert naming.current.mapping == {"S1": "Alice", "S2": "Bob"}
    assert naming.current.manual is True


def test_partial_naming_keeps_defaults_for_unnamed_labels() -> None:
    naming = SpeakerNaming()
    naming.set_names({"S1": "Alice"})
    assert naming.name_for("S1") == "Alice"
    assert naming.name_for("S2") == "SPEAKER_2"


def test_empty_names_are_ignored() -> None:
    naming = SpeakerNaming()
    naming.set_names({"S1": ""})
    assert naming.name_for("S1") == "SPEAKER_1"


def test_current_is_a_snapshot_not_a_view() -> None:
    naming = SpeakerNaming()
    snapshot = naming.current
    snapshot.mapping["S1"] = "corrupted"
    assert naming.name_for("S1") == "SPEAKER_1"
