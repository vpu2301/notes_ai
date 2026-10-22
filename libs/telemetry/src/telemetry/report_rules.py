"""Bottleneck hypotheses as data (telemetry sprint 4): each rule names the facts it reads, the
thresholds that make it fire and the sentence it prints. ``report.py`` computes the facts; a
rule whose fact is missing prints "Not assessable" instead of guessing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Op = Literal[">", ">=", "=="]


@dataclass(frozen=True)
class Condition:
    fact: str
    op: Op
    threshold: float | str


@dataclass(frozen=True)
class Rule:
    id: str
    # All must hold for the rule to fire.
    conditions: tuple[Condition, ...]
    # Formatted with the facts (``str.format``; ``<fact>_pct`` is a share as the report prints
    # it); printed after "Hypothesis: ".
    text: str

    @property
    def inputs(self) -> tuple[str, ...]:
        return tuple(c.fact for c in self.conditions)


GIB = 1024**3

RULES: tuple[Rule, ...] = (
    Rule(
        id="asr_device_configured",
        conditions=(Condition("device_asr_observation", "==", "configured"),),
        text="ASR backend may be running on CPU — unverified (device_asr is {device_asr}, "
        "configured, not observed).",
    ),
    Rule(
        id="diarization_device_configured",
        conditions=(Condition("device_diarization_observation", "==", "configured"),),
        text="diarization backend may be running on CPU — unverified (device_diarization is "
        "{device_diarization}, configured, not observed).",
    ),
    Rule(
        id="asr_dominates",
        conditions=(Condition("rtf", ">=", 0.8), Condition("asr_primary_share", ">", 0.6)),
        text="ASR dominates (rtf {rtf:.3f}, asr_primary {asr_primary_share_pct} of wall); "
        "consider a smaller model, quantization or a lower beam.",
    ),
    Rule(
        id="reprocessing",
        conditions=(Condition("reprocessing_ratio", ">", 1.3),),
        text="recovery passes re-transcribe {reprocessed_share_pct} of the audio "
        "(reprocessing ratio {reprocessing_ratio:.3f}).",
    ),
    Rule(
        id="cold_model_init",
        conditions=(Condition("cold_model_init_share", ">", 0.1),),
        text="model loading takes {cold_model_init_share_pct} of wall (cold model_init); "
        "keep models warm.",
    ),
    Rule(
        id="unknown_speakers",
        conditions=(Condition("unknown_speaker_share", ">", 0.3),),
        text="diarization quality: {unknown_speaker_share_pct} of speech has no known speaker.",
    ),
    Rule(
        id="swap_growth",
        conditions=(Condition("swap_delta_bytes", ">", GIB),),
        text="memory pressure; models may be paging (swap grew {swap_delta_gib:.2f} GiB "
        "during the run).",
    ),
)


def holds(condition: Condition, value: float | str) -> bool:
    if condition.op == "==":
        return value == condition.threshold
    if isinstance(value, str) or isinstance(condition.threshold, str):
        return False
    if condition.op == ">":
        return value > condition.threshold
    return value >= condition.threshold
