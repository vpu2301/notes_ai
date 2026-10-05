"""The error taxonomy in code (docs/eval/error-taxonomy.md): the one table mapping
checklist checks, scorer metrics and dismiss reasons to codes.
A metric, check or reason with no code fails ``tests/unit/test_notes_gates.py``.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final

# code → (layer, severity, category). Severity: S0 incident, S1 misleads,
# S2 unusable, S3 worse than it should be (the highest the code can reach).
CODES: Final[dict[str, tuple[str, str, str]]] = {
    # A. Transcript
    "T-INJ": ("transcript", "S1", "Injected text"),
    "T-COV": ("transcript", "S2", "Lost speech"),
    "T-LANG": ("transcript", "S1", "Wrong-language handling"),
    "T-ENT": ("transcript", "S1", "Misheard names and terms"),
    "T-DIAR": ("transcript", "S2", "Speaker fragmentation"),
    "T-DISP": ("transcript", "S3", "Display fidelity"),
    "T-ADV": ("transcript", "S1", "Non-content passages transcribed as content"),
    # B. Facts
    "F-INV": ("fact", "S1", "Invented claim"),
    "F-DIST": ("fact", "S1", "Distorted claim"),
    "F-NUM": ("fact", "S1", "Missing or wrong number, date, time"),
    "F-SUBJ": ("fact", "S1", "Unresolved or wrong subject"),
    "F-ATTR": ("fact", "S1", "Wrong or missing attribution"),
    "F-ROLE": ("fact", "S1", "Wrong role"),
    "F-TYPE": ("fact", "S2", "Wrong recording type"),
    "F-COPY": ("fact", "S2", "Quote as fact"),
    "F-DESC": ("fact", "S2", "Description instead of information"),
    "F-DROP": ("fact", "S2", "Real content excluded as noise"),
    "F-COV": ("fact", "S2", "Facts missing (recall)"),
    # C. Document
    "D-ORIENT": ("document", "S2", "No orientation"),
    "D-STRUCT": ("document", "S2", "No or wrong structure"),
    "D-HEAD": ("document", "S3", "Bad headings"),
    "D-SPEC": ("document", "S2", "Unspecific bullets"),
    "D-VOL": ("document", "S2", "Wrong volume"),
    "D-RED": ("document", "S3", "Redundancy"),
    "D-NEST": ("document", "S3", "Missing sub-structure"),
    "D-REF": ("document", "S2", "Missing reference"),
    "D-LABEL": ("document", "S2", "Labels in prose"),
    "D-LANG": ("document", "S3", "Wrong language or register"),
    "D-FORM": ("document", "S3", "Rendering defects"),
    # D. Isolation and process
    "P-ISO": ("process", "S0", "Cross-workspace or cross-user content"),
    "P-MEAS": ("process", "S2", "Unmeasured change"),
    "P-PROMPT": ("process", "S1", "Content-bearing prompt"),
}

# notes_assert check family → codes; a checklist may pin one check's codes
# itself (``"codes": {"must_not_contain[0]": ["T-INJ"]}``).
CHECK_CODES: Final[dict[str, tuple[str, ...]]] = {
    "recording_type": ("F-TYPE",),
    "topics_min": ("D-STRUCT",),
    "speakers": ("D-LABEL",),
    "must_not_contain": ("F-INV", "T-INJ"),
    "must_contain_any": ("F-COV", "T-ENT"),
    "hedged_must_keep": ("F-DIST",),
    "dates": ("F-NUM",),
    "every_line_cited": ("D-REF",),
    "no_copied_lines": ("F-COPY",),
    "no_information_lines": ("F-DESC",),
    "no_marks": ("D-FORM",),
    "figures": ("F-NUM",),
    "figures_cited": ("F-NUM", "D-REF"),
    "presenter_line": ("F-ROLE",),
    "contact_line": ("F-COV",),
    "topics": ("D-NEST", "D-STRUCT"),
    "excluded_reasons": ("T-ADV",),
    "guest_line": ("F-ROLE",),
    "chapters_min": ("D-STRUCT",),
    "overview": ("D-ORIENT",),
    # "lint": {"D-STRUCT": 0} — one check per code, named lint[D-STRUCT];
    # its code is the one in brackets.
    "lint": (),
}

# notes_scoring / notes_eval metric → codes.
METRIC_CODES: Final[dict[str, tuple[str, ...]]] = {
    "unsupported_rate": ("F-INV",),
    "invented_claims": ("F-INV",),
    "example_echo": ("P-PROMPT", "F-INV"),
    "key_fact_recall": ("F-COV",),
    "coverage_ratio": ("F-COV",),
    "recall_by_third": ("F-COV",),
    "recall_by_type": ("F-COV",),
    "excluded_speech": ("F-DROP",),
    "recording_type_acc": ("F-TYPE",),
    "redundancy": ("D-RED",),
    "entity_accuracy": ("T-ENT",),
    "entity_accuracy_knowable": ("T-ENT",),
    "entity_sources": ("T-ENT",),
    "model_tier_precision": ("T-ENT",),
    "hedge_preservation": ("F-DIST",),
    "attribution_rate": ("F-ATTR",),
    "lines_cited": ("D-REF",),
    "key_dates_recall": ("F-NUM",),
    "date_resolution": ("F-NUM",),
    "figure_recall": ("F-NUM",),
    "figure_value_accuracy": ("F-NUM",),
    "qualifier_preservation": ("F-NUM",),
    "presenter_accuracy": ("F-ROLE",),
    "contact_present": ("F-COV",),
    "copied_lines": ("F-COPY",),
    "no_information_lines": ("F-DESC",),
    "first_person_lines": ("D-LANG",),
    # Taxonomy detectors
    "label_lines": ("D-LABEL",),
    "unresolved_subject_rate": ("F-SUBJ",),
    "unspecific_bullet_rate": ("D-SPEC",),
    "words_per_minute": ("D-VOL",),
    "headings_per_10_min": ("D-STRUCT",),
    # Document-standard lint (meeting_doc/doclint.py)
    "lint_findings": (
        "D-ORIENT",
        "D-STRUCT",
        "D-HEAD",
        "D-SPEC",
        "D-VOL",
        "D-REF",
        "D-LABEL",
        "D-LANG",
        "D-FORM",
        "D-RED",
        "D-NEST",
        "F-INV",
        "F-SUBJ",
        "F-COPY",
        "F-DESC",
    ),
    "lint_clean_rate": (
        "D-ORIENT",
        "D-STRUCT",
        "D-HEAD",
        "D-SPEC",
        "D-VOL",
        "D-REF",
        "D-LABEL",
        "D-LANG",
        "D-FORM",
        "D-RED",
        "D-NEST",
        "F-INV",
        "F-SUBJ",
        "F-COPY",
        "F-DESC",
    ),
    # Composition
    "sections_in_band": ("D-STRUCT",),
    "headings_pass": ("D-HEAD",),
    "bullets_specific_share": ("D-SPEC",),
    "children_share": ("D-NEST",),
    "subject_failures": ("F-SUBJ", "D-LABEL"),
    "narrator_attribution_errors": ("F-ATTR",),
    "roles_correct": ("F-ROLE",),
    "orientation_p1_ok": ("D-ORIENT",),
    "lint_first_pass": (
        "D-ORIENT",
        "D-STRUCT",
        "D-SPEC",
        "D-VOL",
        "D-REF",
        "D-LABEL",
        "F-SUBJ",
        "F-COPY",
        "F-DESC",
        "F-INV",
        "F-DIST",
    ),
    "lint_after_regeneration": (
        "D-ORIENT",
        "D-STRUCT",
        "D-SPEC",
        "D-VOL",
        "D-REF",
        "D-LABEL",
        "F-SUBJ",
        "F-COPY",
        "F-DESC",
        "F-INV",
        "F-DIST",
    ),
    "summary_ladder": ("D-ORIENT",),
    # Lint gates
    "lint_unresolved": (
        "D-ORIENT",
        "D-STRUCT",
        "D-HEAD",
        "D-SPEC",
        "D-VOL",
        "D-RED",
        "D-NEST",
        "D-REF",
        "D-LABEL",
        "D-LANG",
        "D-FORM",
        "F-INV",
        "F-DIST",
        "F-SUBJ",
        "F-COPY",
        "F-DESC",
    ),
    "d1_unresolved_s1": ("F-INV", "F-DIST", "F-SUBJ"),
    "d1_unresolved_s2_share": (
        "D-ORIENT",
        "D-STRUCT",
        "D-SPEC",
        "D-VOL",
        "D-REF",
        "D-LABEL",
        "F-COPY",
        "F-DESC",
    ),
    "d1_volume_band": ("D-VOL",),
    "d1_section_band": ("D-STRUCT",),
    "d1_label_or_pronoun_lines": ("D-LABEL", "F-SUBJ"),
    "d1_unspecific_lines": ("D-SPEC",),
    # The document standard §8, read by code
    "rubric_auto_q3": ("D-SPEC",),
    "rubric_auto_q7": ("D-VOL",),
    # The judge column
    "judge_unsupported_rate": ("F-INV", "F-DIST"),
    "judge_problems": ("F-INV", "F-DIST", "F-NUM", "F-ATTR"),
    "deterministic_vs_judge_disagreement": ("P-MEAS",),
    "judge_lines": ("P-MEAS",),
    # The transcript harness (scripts/eval/asr_scoring.py)
    "wer": ("T-ENT", "T-COV", "T-DISP"),
    "entity_error_rate": ("T-ENT",),
    "entity_consistency": ("T-ENT",),
    "entity_variants": ("T-ENT",),
    "number_date_error_rate": ("T-ENT",),
    "halluc_chars_per_nonspeech_min": ("T-INJ",),
    "artefact_hits": ("T-INJ",),
    "speech_coverage": ("T-COV",),
    "unexplained_gaps": ("T-COV",),
    "codeswitch_coverage": ("T-LANG",),
    "translated_segments": ("T-LANG",),
    "nonspeech_marked": ("T-ADV",),
    "nonspeech_content_lines": ("T-ADV",),
    "punctuated_share": ("T-DISP",),
    # The summary criteria
    "participant_precision": ("F-ROLE",),
    "participant_recall": ("F-ROLE",),
    "opinion_attribution": ("F-ATTR",),
    "filler_lines": ("D-RED",),
    "title_ok": ("D-HEAD", "F-INV"),
    "by_third_ratio": ("F-COV",),
    "propagated_from_asr": ("T-ENT",),
    "invented_vs_truth": ("F-INV",),
    # The whole recording is in the note
    "sections_count_ok": ("D-STRUCT",),
    "near_empty_rate": ("F-COV",),
    "one_bullet_sections": ("D-STRUCT",),
    # Reads like a note
    "speaker_shaped_lines": ("D-FORM",),
    "order_inversions": ("D-STRUCT",),
    "redundancy_ok_rate": ("D-RED",),
    # The spelling overlay
    "entity_consistency_raw": ("T-ENT",),
    "entity_error_rate_raw": ("T-ENT",),
    "wrong_merges": ("T-ENT",),
    "wrong_merges_per_10": ("T-ENT",),
    "clusters_applied": ("T-ENT",),
    "clusters_proposed": ("T-ENT",),
}

# Aggregate keys that are not error measurements, each with why it has no
# code; anything else without a code fails tests/unit/test_notes_gates.py.
UNCODED_METRICS: Final[dict[str, str]] = {
    "n": "sample size",
    "directional": "sample-size flag (n < 20)",
    "not_measured": "sample-size flag (n < 3)",
    "word_ts_median_ms": "timing contract (ADR-0037), not a content error",
    "word_ts_p90_ms": "timing contract (ADR-0037), not a content error",
    "words_without_timestamps": "timing contract (ADR-0037), not a content error",
    "rtf": "speed (TR-12)",
    "rtf_p95": "speed (TR-12)",
    "seconds_per_audio_hour": "speed and cost (TR-12)",
    "seconds_per_meeting_hour_p95": "speed (SM-14)",
}


def uncoded_metrics(keys: Iterable[str]) -> list[str]:
    """The keys that have neither a code nor a stated reason for none."""
    return sorted(k for k in keys if k not in METRIC_CODES and k not in UNCODED_METRICS)


# Dismiss reason → the code the weekly report counts it under (`not_said`
# counts as F-INV). scripts/ops/notes_quality.sql carries the same table.
REASON_CODES: Final[dict[str, str]] = {
    "not_said": "F-INV",
    "not_a_decision": "F-DIST",
    "not_a_task": "F-DIST",
    "wrong_owner": "F-ATTR",
    "wrong_date": "F-NUM",
    "duplicate": "D-RED",
    "not_relevant": "F-DESC",
}


def check_codes(name: str, checklist: dict | None = None) -> tuple[str, ...]:
    """The codes of one check result (``must_not_contain[3]``,
    ``overview.names_guest``): the checklist's own, else its family's."""
    own = ((checklist or {}).get("codes") or {}).get(name)
    if own:
        return tuple(own)
    family = name.split("[", 1)[0].split(".", 1)[0]
    if family == "lint" and "[" in name:
        return (name[name.index("[") + 1 : name.rindex("]")],)
    return CHECK_CODES.get(family, ())
