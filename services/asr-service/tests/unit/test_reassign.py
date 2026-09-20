# ruff: noqa: F811 — the imported `rig` fixture is injected by name.
"""Turn-level correction (Sprint 30): reassign, reset, fold order.

Runs on the Sprint 28 speaker-edit rig: an in-memory repository scoped by
tenant the way RLS scopes it, over a four-segment transcript
(S1 "Hello there." · S2 "Hi." · S3 "Yes." · S1 "Good.").
"""

from __future__ import annotations

import json
import random
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from asr_service.domain.speaker_edits import SpeakerEdit, apply_edits, fold_label

from .test_speaker_edits import _TENANT_A, _TENANT_B, _merge, _seg, rig  # noqa: F401


def _reassign(
    rig: SimpleNamespace, job: UUID, indices: list[int], to: str | None, rev: int = 1
) -> Any:
    return rig.client.post(
        f"/asr/jobs/{job}/speakers/reassign",
        json={"result_rev": rev, "segment_indices": indices, "to": to},
    )


def _result(rig: SimpleNamespace, job: UUID) -> dict[str, Any]:
    return rig.client.get(f"/asr/jobs/{job}/result").json()


def _reassigned(rig: SimpleNamespace) -> list[dict[str, Any]]:
    return [e["payload"] for e in rig.audit.events if e["kind"] == "asr.turn_reassigned"]


def _turns(result: dict[str, Any]) -> list[tuple[str | None, list[int]]]:
    return [(t["speaker"], t["segment_indices"]) for t in result["turns"]]


def test_moving_a_reply_to_an_existing_speaker(rig: SimpleNamespace) -> None:
    job = rig.repo.add_job(_TENANT_A)
    before = rig.store.body

    resp = _reassign(rig, job, [1], "SPEAKER_1")

    assert resp.status_code == 200, resp.text
    assert resp.json()["created_label"] is None
    result = _result(rig, job)
    assert _turns(result) == [("SPEAKER_1", [0, 1]), ("SPEAKER_3", [2]), ("SPEAKER_1", [3])]
    # SPEAKER_2 lost its only reply: gone from roster, names and stats.
    assert result["speakers"] == ["SPEAKER_1", "SPEAKER_3"]
    assert [s["label"] for s in result["speaker_stats"]] == ["SPEAKER_1", "SPEAKER_3"]
    assert rig.store.body == before, "the stored artifact is byte-identical"
    [event] = [e for e in rig.audit.events if e["kind"] == "asr.turn_reassigned"]
    assert event["payload"] == {"segments": 1, "to": "existing"}


def test_a_person_the_system_missed_gets_a_new_label(rig: SimpleNamespace) -> None:
    job = rig.repo.add_job(_TENANT_A)

    resp = _reassign(rig, job, [0], "new")

    assert resp.status_code == 200, resp.text
    assert resp.json()["created_label"] == "SPEAKER_4"
    result = _result(rig, job)
    assert result["speakers"] == ["SPEAKER_1", "SPEAKER_2", "SPEAKER_3", "SPEAKER_4"]
    assert result["turns"][0]["speaker"] == "SPEAKER_4"
    assert result["speaker_names"]["SPEAKER_4"] == "Speaker 4"
    assert result["edits"][-1]["creates_label"] is True
    assert _reassigned(rig)[-1] == {"segments": 1, "to": "new"}


def test_moving_to_unknown_unattributes_and_drops_an_emptied_label(rig: SimpleNamespace) -> None:
    job = rig.repo.add_job(_TENANT_A)

    assert _reassign(rig, job, [2], None).status_code == 200

    result = _result(rig, job)
    assert "SPEAKER_3" not in result["speakers"]
    assert (None, [2]) in _turns(result)
    assert _reassigned(rig)[-1] == {"segments": 1, "to": "none"}


def test_a_stale_revision_is_409_and_writes_nothing(rig: SimpleNamespace) -> None:
    job = rig.repo.add_job(_TENANT_A)

    resp = _reassign(rig, job, [1], "SPEAKER_1", rev=2)

    assert resp.status_code == 409
    assert resp.json()["code"] == "stale_result_rev"
    assert resp.json()["current_rev"] == 1
    assert _result(rig, job)["edits"] == []


def test_a_merge_after_a_reassign_carries_the_moved_turns(rig: SimpleNamespace) -> None:
    job = rig.repo.add_job(_TENANT_A)
    assert _reassign(rig, job, [1], "SPEAKER_3").status_code == 200

    assert _merge(rig, job, "SPEAKER_3", "SPEAKER_1").status_code == 200

    assert {t["speaker"] for t in _result(rig, job)["turns"]} == {"SPEAKER_1"}


def test_a_reassign_after_a_merge_targets_the_surviving_label(rig: SimpleNamespace) -> None:
    job = rig.repo.add_job(_TENANT_A)
    assert _merge(rig, job, "SPEAKER_3", "SPEAKER_1").status_code == 200

    resp = _reassign(rig, job, [1], "SPEAKER_3")

    assert resp.status_code == 200, resp.text
    result = _result(rig, job)
    assert result["edits"][-1]["to_label"] == "SPEAKER_1"
    assert result["speakers"] == ["SPEAKER_1"]


@pytest.mark.parametrize(
    ("indices", "to", "code"),
    [
        ([4], "SPEAKER_1", "bad_segment_index"),
        ([-1], "SPEAKER_1", "bad_segment_index"),
        (list(range(501)), "SPEAKER_1", "too_many_segments"),
        ([1], "SPEAKER_7", "unknown_label"),
    ],
)
def test_reassign_rejections(rig: SimpleNamespace, indices: list[int], to: str, code: str) -> None:
    job = rig.repo.add_job(_TENANT_A)

    resp = _reassign(rig, job, indices, to)

    assert resp.status_code == 422
    assert resp.json()["code"] == code


def test_a_ninth_live_speaker_is_refused(
    rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from asr_service.routers import jobs

    monkeypatch.setattr(jobs, "MAX_LIVE_SPEAKERS", 3)
    job = rig.repo.add_job(_TENANT_A)

    resp = _reassign(rig, job, [0], "new")  # S1 keeps segment 3 → four live speakers

    assert resp.status_code == 422
    assert resp.json()["code"] == "too_many_speakers"


def test_the_same_move_twice_is_one_edit(rig: SimpleNamespace) -> None:
    job = rig.repo.add_job(_TENANT_A)

    first = _reassign(rig, job, [1, 1], "SPEAKER_1")
    again = _reassign(rig, job, [1], "SPEAKER_1")

    assert first.json()["edit_id"] == again.json()["edit_id"]
    assert len(_result(rig, job)["edits"]) == 1


def test_undo_restores_a_moved_turn(rig: SimpleNamespace) -> None:
    job = rig.repo.add_job(_TENANT_A)
    edit_id = _reassign(rig, job, [1], "SPEAKER_1").json()["edit_id"]

    assert rig.client.delete(f"/asr/jobs/{job}/speakers/edits/{edit_id}").status_code == 204

    assert _result(rig, job)["speakers"] == ["SPEAKER_1", "SPEAKER_2", "SPEAKER_3"]


def test_reset_reverts_every_live_edit_and_is_idempotent(rig: SimpleNamespace) -> None:
    job = rig.repo.add_job(_TENANT_A)
    _reassign(rig, job, [1], "SPEAKER_1")
    _merge(rig, job, "SPEAKER_3", "SPEAKER_1")

    first = rig.client.post(f"/asr/jobs/{job}/speakers/edits/reset")
    again = rig.client.post(f"/asr/jobs/{job}/speakers/edits/reset")

    assert (first.status_code, again.status_code) == (204, 204)
    result = _result(rig, job)
    assert result["edits"] == []
    assert result["speakers"] == ["SPEAKER_1", "SPEAKER_2", "SPEAKER_3"]
    resets = [e for e in rig.audit.events if e["kind"] == "asr.speaker_edits_reset"]
    assert [e["payload"] for e in resets] == [{"count": 2}], "an empty reset is not audited"


def test_another_tenant_can_neither_reassign_nor_reset(rig: SimpleNamespace) -> None:
    job = rig.repo.add_job(_TENANT_A)
    rig.current["tid"] = _TENANT_B

    assert _reassign(rig, job, [1], "SPEAKER_1").status_code == 404
    assert rig.client.post(f"/asr/jobs/{job}/speakers/edits/reset").status_code == 404
    rig.current["tid"] = _TENANT_A
    assert _result(rig, job)["edits"] == []


def test_audit_payloads_carry_no_text_or_names(rig: SimpleNamespace) -> None:
    job = rig.repo.add_job(_TENANT_A)
    rig.client.put(f"/asr/jobs/{job}/speakers", json={"names": {"SPEAKER_1": "Anna Keller"}})
    _reassign(rig, job, [1], "new")
    rig.client.post(f"/asr/jobs/{job}/speakers/edits/reset")

    dumped = json.dumps([e["payload"] for e in rig.audit.events])
    for content in ("Anna", "Hello", "Hi.", "Yes."):
        assert content not in dumped


# ── Fold order (pure) ─────────────────────────────────────────────────


def _edit(seq: int, kind: str, **kw: Any) -> SpeakerEdit:
    return SpeakerEdit(
        uuid4(),
        kind,
        kw.get("frm"),
        kw.get("to"),
        kw.get("indices", []),
        1,
        seq,
        datetime.now(UTC),
        creates_label=kw.get("creates", False),
    )


def test_fold_is_seq_ordered_whatever_order_edits_arrive_in() -> None:
    """Property: the same edits in any list order fold to the same labels."""
    rng = random.Random(30)
    labels = ["SPEAKER_1", "SPEAKER_2", "SPEAKER_3", "SPEAKER_4"]
    for _ in range(200):
        segments = [_seg(rng.choice([*labels, None]), i, i + 1) for i in range(8)]
        edits = []
        for seq in range(1, rng.randint(1, 6) + 1):
            if rng.random() < 0.5:
                frm, to = rng.sample(labels, 2)
                edits.append(_edit(seq, "merge", frm=frm, to=to))
            else:
                edits.append(
                    _edit(
                        seq,
                        "reassign",
                        to=rng.choice([*labels, None]),
                        indices=rng.sample(range(8), rng.randint(1, 3)),
                    )
                )
        expected = [s.speaker for s in apply_edits(segments, edits)]
        shuffled = edits[:]
        rng.shuffle(shuffled)
        assert [s.speaker for s in apply_edits(segments, shuffled)] == expected


def test_a_served_segment_is_labelled_by_its_host_artifact_segment() -> None:
    """Review finding: a move of a lone "." (served alone while NLP was
    down) must not drag its host sentence along once NLP folds it in."""
    edit = _edit(1, "reassign", to="SPEAKER_2", indices=[1])

    host = _seg("SPEAKER_1", 0, 1).model_copy(
        update={"artifact_index": 0, "artifact_indices": [0, 1]}
    )
    assert apply_edits([host], [edit])[0].speaker == "SPEAKER_1"
    assert fold_label("SPEAKER_1", 1, [edit]) == "SPEAKER_2"


def test_a_segment_moved_to_unknown_is_not_folded_back_into_its_neighbours(
    rig: SimpleNamespace,
) -> None:
    """Review finding: A, B, A with B moved to Unknown used to read as one A turn."""
    job = rig.repo.add_job(_TENANT_A)
    assert _merge(rig, job, "SPEAKER_3", "SPEAKER_1").status_code == 200  # S1 S2 S1 S1

    assert _reassign(rig, job, [1], None).status_code == 200

    assert _turns(_result(rig, job)) == [("SPEAKER_1", [0]), (None, [1]), ("SPEAKER_1", [2, 3])]


def test_a_moved_turn_is_no_longer_uncertain() -> None:
    edit = _edit(1, "reassign", to="SPEAKER_2", indices=[0])
    seg = _seg("SPEAKER_1", 0, 1).model_copy(
        update={"artifact_index": 0, "speaker_uncertain": True}
    )

    moved = apply_edits([seg], [edit])[0]

    assert (moved.speaker, moved.speaker_uncertain) == ("SPEAKER_2", False)


def test_an_undone_new_speaker_takes_its_name_along_and_is_never_reused(
    rig: SimpleNamespace,
) -> None:
    """Review finding: SPEAKER_4 named "Anna", undone, then a different
    person moved to "new" came back as SPEAKER_4 — and as "Anna"."""
    job = rig.repo.add_job(_TENANT_A)
    first = _reassign(rig, job, [0], "new").json()
    assert first["created_label"] == "SPEAKER_4"
    rig.client.put(f"/asr/jobs/{job}/speakers", json={"names": {"SPEAKER_4": "Anna"}})
    assert (
        rig.client.delete(f"/asr/jobs/{job}/speakers/edits/{first['edit_id']}").status_code == 204
    )

    again = _reassign(rig, job, [2], "new").json()

    assert again["created_label"] == "SPEAKER_5"
    assert "Anna" not in _result(rig, job)["speaker_names"].values()


def test_reset_takes_back_names_a_merge_copied(rig: SimpleNamespace) -> None:
    job = rig.repo.add_job(_TENANT_A)
    rig.client.put(f"/asr/jobs/{job}/speakers", json={"names": {"SPEAKER_3": "Anna"}})
    _merge(rig, job, "SPEAKER_3", "SPEAKER_1")  # copies "Anna" onto SPEAKER_1

    assert rig.client.post(f"/asr/jobs/{job}/speakers/edits/reset").status_code == 204

    names = _result(rig, job)["speaker_names"]
    assert (names["SPEAKER_1"], names["SPEAKER_3"]) == ("Speaker 1", "Anna")


def test_a_retry_naming_a_merged_away_label_is_still_one_edit(rig: SimpleNamespace) -> None:
    job = rig.repo.add_job(_TENANT_A)
    _merge(rig, job, "SPEAKER_3", "SPEAKER_1")

    first = _reassign(rig, job, [1], "SPEAKER_3").json()
    again = _reassign(rig, job, [1], "SPEAKER_3").json()

    assert first["edit_id"] == again["edit_id"]


def test_a_note_building_read_is_not_an_opening(
    rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from asr_service.routers import jobs

    marked: list[UUID] = []

    async def mark(conn: object, *, job_id: UUID) -> bool:
        marked.append(job_id)
        return True

    monkeypatch.setattr(jobs.repository, "mark_result_read", mark)
    job = rig.repo.add_job(_TENANT_A)

    rig.client.get(f"/asr/jobs/{job}/result", headers={"X-MDX-Read-Purpose": "note_build"})
    assert marked == []
    rig.client.get(f"/asr/jobs/{job}/result")
    assert marked == [job]


# ── Sprint 31: name provenance ────────────────────────────────────────


def test_clearing_a_channel_name_is_remembered_and_sources_persist(rig: SimpleNamespace) -> None:
    from asr_service.domain.repository import merge_name_sources

    job = rig.repo.add_job(_TENANT_A)
    row = next(v for (t, j), v in rig.repo.jobs.items() if j == job)
    row["speaker_names"] = {"SPEAKER_1": "Volodymyr"}
    row["speaker_name_sources"] = {"SPEAKER_1": "channel"}

    # ✕ on the channel name: PUT without that label, the other name kept.
    resp = rig.client.put(
        f"/asr/jobs/{job}/speakers",
        json={"names": {"SPEAKER_2": "Olena"}, "sources": {"SPEAKER_2": "picklist"}},
    )

    assert resp.status_code == 200
    assert row["speaker_name_sources"] == {"SPEAKER_1": "cleared", "SPEAKER_2": "picklist"}
    result = _result(rig, job)
    assert result["speaker_name_sources"] == {"SPEAKER_1": "cleared", "SPEAKER_2": "picklist"}
    # Pure rules: a later typed rename of the cleared label is the person's.
    assert merge_name_sources(
        {"SPEAKER_1": "cleared"}, names={"SPEAKER_1": "Vova"}, sources={}
    ) == {"SPEAKER_1": "typed"}
