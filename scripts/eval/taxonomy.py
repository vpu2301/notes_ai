"""The error taxonomy in code (docs/eval/error-taxonomy.md).

Every defect in a transcript or a note has a code. This module is the one
table the eval tools read: which codes a checklist check, a scorer metric
or a person's dismiss reason stands for. A metric, check or reason with no
code fails ``tests/unit/test_notes_gates.py``; a defect that fits no code
gets a new one here and in the document, together.
"""

from __future__ import annotations

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

# notes_assert check family → codes. A checklist may name the codes of
# one check itself (``"codes": {"must_not_contain[0]": ["T-INJ"]}``) — a
# forbidden string can be an injection, a trailer or an invented claim.
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
    # Taxonomy detectors (2026-09-27)
    "label_lines": ("D-LABEL",),
    "unresolved_subject_rate": ("F-SUBJ",),
    "unspecific_bullet_rate": ("D-SPEC",),
    "words_per_minute": ("D-VOL",),
    "headings_per_10_min": ("D-STRUCT",),
    # The judge column
    "judge_unsupported_rate": ("F-INV", "F-DIST"),
    "judge_problems": ("F-INV", "F-DIST", "F-NUM", "F-ATTR"),
    "deterministic_vs_judge_disagreement": ("P-MEAS",),
    "judge_lines": ("P-MEAS",),
}

# A person's dismiss reason (notes_corrections.DismissReason) → the one
# code the weekly report counts it under. `not_said` cannot tell an
# invented line (F-INV) from injected transcript text (T-INJ); it counts as
# F-INV. The SQL in scripts/ops/notes_quality.sql carries the same table.
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
    return CHECK_CODES.get(family, ())
