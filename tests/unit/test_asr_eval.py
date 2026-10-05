"""The ASR gold-set harness: normaliser, metrics, gold format, checklists, nightly
comparison and CI content gate. Synthetic text only.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from asr_models import (
    Coverage,
    CoverageGap,
    Diagnostics,
    Segment,
    TranscriptionMetadata,
    TranscriptionOutput,
    WordTiming,
)

REPO = Path(__file__).resolve().parents[2]
EVAL = REPO / "scripts" / "eval"
sys.path.insert(0, str(EVAL))


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, EVAL / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


asr_scoring = _load("asr_scoring")
asr_gold = _load("asr_gold")
compare_asr = _load("compare_asr")
coverage_assert = _load("coverage_assert")
taxonomy = _load("taxonomy")


# ── Builders ─────────────────────────────────────────────────────────


def _seg(
    start_ms: int, text: str, *, ms_per_word: int = 400, language: str | None = None
) -> Segment:
    words = []
    t = start_ms
    for w in text.split():
        words.append(WordTiming(text=w, start_ms=t, end_ms=t + ms_per_word - 50, probability=0.9))
        t += ms_per_word
    return Segment(
        text=text,
        start_ms=start_ms,
        end_ms=max(t, start_ms + 1),
        words=words,
        avg_confidence=0.9,
        language=language,
    )


def _out(
    *segments: Segment, language: str = "de", coverage: Coverage | None = None
) -> TranscriptionOutput:
    return TranscriptionOutput(
        language=language,
        segments=list(segments),
        metadata=TranscriptionMetadata(
            model="test", vad_seconds_speech=0, infer_seconds=0, beam_size=1
        ),
        diagnostics=Diagnostics(coverage=coverage),
    )


def _ref(start_ms: int, end_ms: int, text: str, language: str = "de") -> dict[str, Any]:
    return {
        "start_ms": start_ms,
        "end_ms": end_ms,
        "speaker": "A",
        "text": text,
        "language": language,
    }


# ── Normaliser: ten pairs per language ───────────────────────────────

GERMAN = [
    ("Wir sind zweiundzwanzig Leute.", "wir sind 22 leute"),
    ("Das kostet dreihundertfünfzig Euro", "das kostet 350 euro"),
    ("am zweiundzwanzigsten Juni", "am 22 juni"),
    ("zweitausendsechsundzwanzig", "2026"),
    ("Äh, ähm, wir haben das E-Mail-Team", "wir haben das emailteam"),
    ("3,5 %", "3.5 prozent"),
    ("1.000 Nutzer", "1000 nutzer"),
    ("drei komma fünf", "3.5"),
    ("ein Meeting mit einer Kollegin", "ein meeting mit einer kollegin"),
    ("Die Straße, am dritten Mai!", "die strasse am 3 mai"),
]
ENGLISH = [
    ("Twenty-two people came.", "22 people came"),
    ("It costs two hundred and fifty three dollars", "it costs 253 dollars"),
    ("In nineteen ninety nine we", "in 1999 we"),
    ("twenty twenty-six", "2026"),
    ("the first of May", "the 1 of may"),
    ("the 1st of May", "the 1 of may"),
    ("Uh, we, um, agreed.", "we agreed"),
    ("3.5% growth", "3.5 percent growth"),
    ("1,000 users", "1000 users"),
    ("Don't worry, it's fine", "don't worry it's fine"),
]
UKRAINIAN = [
    ("Двадцять два учасники", "22 учасники"),
    ("дві тисячі двадцять шостого року", "2026 року"),
    ("двадцять друге червня", "22 червня"),
    ("22-го червня", "22 червня"),
    ("Ем, п’ятсот гривень", "500 гривень"),
    ("будь-який варіант", "будьякий варіант"),
    ("третій пункт", "3 пункт"),
    ("10 000 користувачів", "10000 користувачів"),
    ("3,5 відсотка", "3.5 відсотків"),
    ("з п'ятьма колегами", "з 5 колегами"),
]


@pytest.mark.parametrize(("text", "expected"), GERMAN)
def test_german_normalisation(text: str, expected: str) -> None:
    assert asr_scoring.normalise(text, "de") == expected


@pytest.mark.parametrize(("text", "expected"), ENGLISH)
def test_english_normalisation(text: str, expected: str) -> None:
    assert asr_scoring.normalise(text, "en") == expected


@pytest.mark.parametrize(("text", "expected"), UKRAINIAN)
def test_ukrainian_normalisation(text: str, expected: str) -> None:
    assert asr_scoring.normalise(text, "uk") == expected


def test_a_word_that_starts_like_a_number_stays_a_word() -> None:
    assert (
        asr_scoring.normalise("Achtung, Einsatz, Vierteljahr", "de")
        == "achtung einsatz vierteljahr"
    )


# ── WER ──────────────────────────────────────────────────────────────


def test_wer_on_a_known_pair() -> None:
    # 6 reference words; one substitution, one deletion → 2/6.
    reference = [_ref(0, 3000, "Wir treffen uns am zweiten Mai")]
    hyp = _out(_seg(0, "Wir trafen uns zweiten Mai"))
    counts = asr_scoring.wer_counts(reference, hyp, [])
    assert counts["ref_words"] == 6
    assert (counts["sub"], counts["del"], counts["ins"]) == (1, 1, 0)
    assert asr_scoring.wer_of(counts) == pytest.approx(2 / 6)


def test_number_words_and_digits_are_not_an_error() -> None:
    reference = [_ref(0, 3000, "Der Termin ist am 22. Juni")]
    hyp = _out(_seg(0, "Der Termin ist am zweiundzwanzigsten Juni"))
    assert asr_scoring.wer_of(asr_scoring.wer_counts(reference, hyp, [])) == 0.0


def test_words_inside_non_speech_are_not_counted_as_wer() -> None:
    reference = [_ref(0, 2000, "Guten Morgen")]
    hyp = _out(_seg(0, "Guten Morgen"), _seg(10_000, "Untertitelung des ZDF"))
    non_speech = [{"start_ms": 9000, "end_ms": 20_000, "kind": "jingle"}]
    assert asr_scoring.wer_of(asr_scoring.wer_counts(reference, hyp, non_speech)) == 0.0


# ── TR-02 ────────────────────────────────────────────────────────────


def test_hallucination_inside_a_non_speech_region() -> None:
    hyp = _out(_seg(0, "Guten Morgen"), _seg(60_000, "Vielen Dank."))
    non_speech = [{"start_ms": 60_000, "end_ms": 120_000, "kind": "music"}]
    out = asr_scoring.hallucination(non_speech, hyp)
    assert out == {"nonspeech_ms": 60_000, "halluc_chars": len("VielenDank.")}
    agg = asr_scoring.aggregate([{**out, "sub": 0, "del": 0, "ins": 0, "ref_words": 1}])
    assert agg["halluc_chars_per_nonspeech_min"] > 0


def test_an_ad_read_is_speech_not_hallucination() -> None:
    hyp = _out(_seg(0, "Dieser Podcast wird unterstützt von"))
    out = asr_scoring.hallucination([{"start_ms": 0, "end_ms": 30_000, "kind": "ad"}], hyp)
    assert out == {"nonspeech_ms": 0, "halluc_chars": 0}


def test_artefact_phrase_is_one_hit() -> None:
    hyp = _out(_seg(0, "Guten Morgen zusammen"), _seg(5000, "Untertitelung des ZDF, 2020"))
    assert asr_scoring.artefact_hits(hyp, []) == 1


def test_a_spoken_thank_you_is_not_an_artefact_outside_non_speech() -> None:
    hyp = _out(_seg(0, "Vielen Dank."), _seg(60_000, "Vielen Dank."))
    non_speech = [{"start_ms": 59_000, "end_ms": 90_000, "kind": "silence"}]
    assert asr_scoring.artefact_hits(hyp, non_speech) == 1


# ── TR-03 ────────────────────────────────────────────────────────────


def test_unexplained_gaps_are_long_gaps_of_unknown_cause() -> None:
    cov = Coverage(
        speech_ms=100_000,
        transcribed_ms=95_000,
        gaps=[
            CoverageGap(start_ms=0, end_ms=4000, cause="unknown"),
            CoverageGap(start_ms=10_000, end_ms=11_000, cause="unknown"),
            CoverageGap(start_ms=20_000, end_ms=30_000, cause="other_language"),
        ],
    )
    assert asr_scoring.coverage(_out(coverage=cov)) == {
        "speech_ms": 100_000,
        "transcribed_ms": 95_000,
        "unexplained_gaps": 1,
    }


# ── TR-04 / TR-05 ────────────────────────────────────────────────────


def test_consistency_of_a_five_variant_entity_is_one_fifth() -> None:
    heard = ["Handala", "Hand aller", "Andala", "Handela", "Handler"]
    segments = [_seg(k * 20_000, f"Wir sprechen über {v} heute") for k, v in enumerate(heard)]
    spans = {
        "entities": [
            {
                "start_ms": k * 20_000 + 1200,
                "end_ms": k * 20_000 + 2000,
                "text": "Handala",
                "type": "other",
            }
            for k in range(5)
        ]
    }
    out = asr_scoring.entity_consistency(spans, _out(*segments), "de")
    assert out["Handala"]["consistency"] == pytest.approx(0.2)
    assert out["Handala"]["variants"] == 5


def test_entity_error_rate_counts_misheard_names_within_two_seconds() -> None:
    hyp = _out(_seg(0, "Peter Welchering sagt"), _seg(30_000, "und Tara Bonjad meint"))
    spans = {
        "entities": [
            {"start_ms": 0, "end_ms": 800, "text": "Peter Welchering", "type": "person"},
            {"start_ms": 30_400, "end_ms": 31_200, "text": "Tara Boniat", "type": "person"},
        ]
    }
    assert asr_scoring.entity_errors(spans, hyp, "de") == {"entities": 2, "entities_wrong": 1}


def test_number_and_date_spans_compare_normalised_values() -> None:
    hyp = _out(_seg(0, "am zweiundzwanzigsten Juni kamen 350 Leute"))
    spans = {
        "numbers": [
            {"start_ms": 0, "end_ms": 1000, "text": "22.", "kind": "date"},
            {"start_ms": 1000, "end_ms": 2000, "text": "dreihundertfünfzig", "kind": "number"},
            {"start_ms": 1000, "end_ms": 2000, "text": "400", "kind": "number"},
        ]
    }
    assert asr_scoring.number_date_errors(spans, hyp, "de") == {"numbers": 3, "numbers_wrong": 1}


# ── TR-06 ────────────────────────────────────────────────────────────


def test_code_switch_kept_and_translated_segments() -> None:
    reference = [
        _ref(0, 3000, "Der Sprecher sagt", "de"),
        _ref(3000, 6000, "we will respond with force", "en"),
    ]
    spans = {"code_switch": [{"start_ms": 3000, "end_ms": 6000, "language": "en"}]}
    kept = _out(
        _seg(0, "Der Sprecher sagt"), _seg(3000, "we will respond with force", language="en")
    )
    assert asr_scoring.codeswitch(reference, spans, kept) == {
        "codeswitch_regions": 1,
        "codeswitch_covered": 1,
        "translated_segments": 0,
    }
    translated = _out(_seg(0, "Der Sprecher sagt"), _seg(3000, "wir werden mit Gewalt antworten"))
    assert asr_scoring.codeswitch(reference, spans, translated) == {
        "codeswitch_regions": 1,
        "codeswitch_covered": 0,
        "translated_segments": 1,
    }


# ── TR-07 / TR-08 / TR-09 ────────────────────────────────────────────


def test_non_speech_markers_count_and_content_inside_is_counted() -> None:
    from asr_models import NoiseRegion

    hyp = _out(_seg(0, "Hallo"))
    hyp = hyp.model_copy(
        update={"noise": [NoiseRegion(start_ms=9500, end_ms=19_000, kind="music")]}
    )
    non_speech = [{"start_ms": 9000, "end_ms": 20_000, "kind": "jingle"}]
    assert asr_scoring.nonspeech_marked(non_speech, hyp)["nonspeech_marked"] == 1


def test_non_speech_without_markers_is_unmarked_and_content_inside_is_counted() -> None:
    hyp = _out(_seg(0, "Hallo"), _seg(10_000, "Untertitelung des ZDF"))
    non_speech = [{"start_ms": 9000, "end_ms": 20_000, "kind": "jingle"}]
    assert asr_scoring.nonspeech_marked(non_speech, hyp) == {
        "nonspeech_regions": 1,
        "nonspeech_marked": 0,
        "nonspeech_content_lines": 1,
    }


def test_word_timing_error_against_the_alignment() -> None:
    hyp = _out(_seg(1000, "eins zwei drei"))  # starts 1000, 1400, 1800
    alignment = [
        {"text": "eins", "start_ms": 1100, "end_ms": 1300},
        {"text": "zwei", "start_ms": 1400, "end_ms": 1700},
        {"text": "drei", "start_ms": 2100, "end_ms": 2300},
    ]
    out = asr_scoring.word_timing(alignment, hyp)
    assert out["word_ts_errors_ms"] == [100, 0, 300]
    assert out["words_without_timestamps"] == 0


def test_punctuation_share_reads_long_segments() -> None:
    hyp = _out(
        _seg(0, "Das ist ein langer Satz mit acht Wörtern darin."),
        _seg(9000, "das ist ein langer satz ohne jedes satzzeichen hier"),
        _seg(20_000, "kurz"),
    )
    assert asr_scoring.punctuation(hyp) == {"long_segments": 2, "punctuated_segments": 1}


def test_score_and_aggregate_carry_numbers_only() -> None:
    reference = [_ref(0, 3000, "Handala ist ein Symbol")]
    hyp = _out(_seg(0, "Handala ist ein Symbol"))
    row = asr_scoring.score_recording(
        reference=reference,
        spans={"entities": [{"start_ms": 0, "end_ms": 400, "text": "Handala", "type": "other"}]},
        alignment=None,
        hyp=hyp,
        language="de",
        audio_seconds=60,
        wall_seconds=6,
    )
    public = {k: v for k, v in row.items() if k != "_local"}
    assert "Handala" not in json.dumps(public) and "Symbol" not in json.dumps(public)
    agg = asr_scoring.aggregate([row])
    assert agg["wer"] == 0.0 and agg["rtf"] == 0.1
    assert agg["n"] == 1 and agg["directional"] and agg["not_measured"]
    assert taxonomy.uncoded_metrics(agg) == []


def test_a_metric_without_a_taxonomy_code_fails_the_gate() -> None:
    assert taxonomy.uncoded_metrics(["wer", "halluc_chars_per_nonspeech_min"]) == []
    assert taxonomy.uncoded_metrics(["wer", "mystery_rate"]) == ["mystery_rate"]


# ── Gold format ──────────────────────────────────────────────────────


def _row(**kw: Any) -> dict[str, Any]:
    base = {
        "id": "de-001",
        "language": "de",
        "kinds": ["internal_meeting"],
        "minutes": 30,
        "speakers": 3,
        "split": "dev",
        "consent_ref": "C-2026-001",
    }
    return {**base, **kw}


def test_manifest_refuses_a_row_without_provenance_and_a_title_as_id() -> None:
    with pytest.raises(Exception, match="consent_ref or licence"):
        asr_gold.ManifestRow.model_validate(_row(consent_ref=None))
    with pytest.raises(Exception, match="pattern"):
        asr_gold.ManifestRow.model_validate(_row(id="Handala Episode mit Peter"))
    with pytest.raises(Exception, match="Extra inputs"):
        asr_gold.ManifestRow.model_validate(_row(title="Weekly sync"))


def test_the_empty_committed_manifest_reports_its_shortfall() -> None:
    problems = asr_gold.validate(REPO / "eval" / "asr" / "v1", content=False)
    assert "composition: recordings 0 < 14" in problems
    assert "composition: regression case r04 missing" in problems


def test_content_checks_find_fillers_and_a_missing_second_pass(tmp_path: Path) -> None:
    corpus = tmp_path / "v1"
    (corpus / "de-001").mkdir(parents=True)
    rows = [_row(split="test", has_non_speech=True, non_speech_seconds=40)]
    (corpus / "manifest.json").write_text(json.dumps({"version": 1, "recordings": rows}))
    (corpus / "de-001" / "audio.wav").write_bytes(b"RIFF")
    (corpus / "de-001" / "reference.json").write_text(
        json.dumps([_ref(0, 2000, "Äh, guten Morgen"), _ref(2000, 4000, "Wir beginnen")])
    )
    (corpus / "de-001" / "spans.json").write_text(
        json.dumps({"non_speech": [{"start_ms": 10_000, "end_ms": 50_000, "kind": "music"}]})
    )
    problems = asr_gold.content_problems(corpus, asr_gold.load_manifest(corpus).recordings[0])
    assert "de-001: 1 reference segments carry a filler (verbatim-lite drops them)" in problems
    assert "de-001: test split needs 2 reference passes, has 0" in problems
    assert "de-001: reference.rttm missing" in problems


# ── Regression checklists ────────────────────────────────────────────


def test_r04_checklist_marks_what_later_sprints_fix() -> None:
    checklist = coverage_assert.load("r04_de_handala_podcast")
    today = _out(
        _seg(0, "Heute über Hand aller und Andala"),
        _seg(60_000, "Untertitelung des ZDF, 2020"),
        _seg(90_000, "Handala ist eine Figur"),
    )
    statuses = dict(coverage_assert.statuses(checklist["assertions"], today))
    # A ZDF credit in the transcript fails the run.
    assert statuses["must_not_contain[0]"] == "FAIL"
    # Five spelling variants in the view fail the run.
    assert statuses["entity_variants_max[Handala]"] == "FAIL"
    assert statuses["must_contain_before_ms[0]"] == "PENDING"
    fixed = _out(_seg(0, "Heute über Handala"), _seg(90_000, "Handala ist eine Figur"))
    statuses = dict(coverage_assert.statuses(checklist["assertions"], fixed))
    assert statuses["entity_variants_max[Handala]"] == "PASS"
    assert statuses["must_not_contain[0]"] == "PASS"


def test_every_asr_checklist_check_has_a_code() -> None:
    for path in sorted(
        (REPO / "tests" / "fixtures" / "eval" / "asr" / "assertions").glob("*.json")
    ):
        checklist = json.loads(path.read_text("utf-8"))
        if "recording" not in checklist:
            continue
        for name, _ok in coverage_assert.check(checklist["assertions"], _out()):
            assert checklist["codes"].get(name), (path.name, name)
        for name in coverage_assert.pending(checklist["assertions"]):
            assert checklist["codes"].get(name), (path.name, name)


# ── Nightly comparison ───────────────────────────────────────────────


def _report(uk_wer: float) -> dict[str, Any]:
    agg = {
        "n": 4,
        "not_measured": False,
        "wer": 0.1,
        "halluc_chars_per_nonspeech_min": 1.0,
        "artefact_hits": 0,
        "speech_coverage": 0.97,
        "unexplained_gaps": 0,
    }
    return {
        "backend": "inproc_cpu_asr",
        "split": "test",
        "corpus_manifest_sha256": "abc",
        "by_language": {
            "de": dict(agg),
            "uk": {**agg, "wer": uk_wer},
            "en": dict(agg),
            "all": dict(agg),
        },
    }


def test_a_uk_report_one_and_a_half_points_worse_fails_the_nightly(tmp_path: Path) -> None:
    base, worse = tmp_path / "base.json", tmp_path / "cur.json"
    base.write_text(json.dumps(_report(0.20)))
    worse.write_text(json.dumps(_report(0.215)))
    assert compare_asr.main(["--baseline", str(base), "--current", str(worse)]) == 1
    within = tmp_path / "ok.json"
    within.write_text(json.dumps(_report(0.209)))
    assert compare_asr.main(["--baseline", str(base), "--current", str(within)]) == 0


def test_the_nightly_refuses_a_comparison_across_corpora(tmp_path: Path) -> None:
    other = _report(0.2)
    other["corpus_manifest_sha256"] = "def"
    with pytest.raises(compare_asr.IncomparableError):
        compare_asr.compare(_report(0.2), other)


def test_tr02_may_not_worsen_at_all() -> None:
    cur = _report(0.2)
    cur["by_language"]["de"]["artefact_hits"] = 1
    assert compare_asr.compare(_report(0.2), cur) == [
        "de.artefact_hits: 0 → 1 (worse by 1.0000, allowed 0.0)"
    ]


# ── CI content gate ──────────────────────────────────────────────────


def _gate(*paths: str) -> int:
    return subprocess.run(
        ["bash", str(REPO / "scripts" / "ci" / "check-no-eval-audio.sh"), "--paths", *paths],
        capture_output=True,
        check=False,
    ).returncode


def test_ci_fails_on_tracked_gold_content() -> None:
    assert (
        _gate("eval/asr/v1/manifest.json", "eval/asr/v1/README.md", "eval/speakers/v1/rttm/a.rttm")
        == 0
    )
    assert _gate("eval/asr/v1/r04/reference.json") == 1
    assert _gate("eval/notes/v2/gold.json") == 1
    assert _gate("eval/notes/v2/review-1.csv") == 1
    assert _gate("eval/asr/v1/r04/reference.rttm") == 1
    assert _gate("eval/asr/v1/r04/audio.m4a") == 1


def test_the_regression_drill_turns_an_equal_report_into_a_failure(tmp_path: Path) -> None:
    base = tmp_path / "base.json"
    base.write_text(json.dumps(_report(0.20)))
    assert compare_asr.main(["--baseline", str(base), "--current", str(base)]) == 0
    assert (
        compare_asr.main(
            ["--baseline", str(base), "--current", str(base), "--inject-wer-pp", "1.5"]
        )
        == 1
    )


def test_wrong_merges_count_clusters_that_rewrite_another_gold_entity() -> None:
    from types import SimpleNamespace

    good = SimpleNamespace(status="accepted", to_text="Welchering", occurrences=({"t": 1000},))
    bad = SimpleNamespace(status="accepted", to_text="Miller", occurrences=({"t": 20_000},))
    plan = SimpleNamespace(proposals=[good, bad])
    spans = {
        "entities": [
            {"start_ms": 1000, "end_ms": 1500, "text": "Peter Welchering", "type": "person"},
            {"start_ms": 20_000, "end_ms": 20_500, "text": "Anna Müller", "type": "person"},
        ]
    }
    assert asr_scoring.merge_quality(plan, spans) == {
        "clusters_applied": 2,
        "clusters_proposed": 0,
        "wrong_merges": 1,
    }
