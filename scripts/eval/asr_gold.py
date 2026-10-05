#!/usr/bin/env python3
"""Sprint TQ1 T2/T3 — the ASR gold set ``eval/asr/v1``: format and checks.

    python scripts/eval/asr_gold.py validate eval/asr/v1            # manifest + composition
    python scripts/eval/asr_gold.py validate eval/asr/v1 --content  # + local reference files
    python scripts/eval/asr_gold.py fetch eval/asr/v1               # bucket → local (eval role)

What lives where:

- **git**: ``manifest.json`` and ``README.md`` only. The manifest carries ids,
  languages, minutes, kinds, consent references — never a name or a title.
- **bucket** (``s3://notes-eval/asr/v1/<id>/``, private, SSE-KMS, eval role):
  ``audio.<ext>``, ``reference.json``, ``spans.json``, ``reference.rttm`` and
  the cached ``alignment.json``. Fetched to ``eval/asr/v1/<id>/`` locally,
  which ``.gitignore`` and ``scripts/ci/check-no-eval-audio.sh`` keep out of
  git.

``validate`` prints problems (one per line, ids and field names only) and
exits 1 when there are any. A composition shortfall is a problem: the
sprint's gold set is 14 recordings in a stated mix, and until it exists the
tool says so rather than passing.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

REPO = Path(__file__).resolve().parents[2]
DEFAULT_CORPUS = REPO / "eval" / "asr" / "v1"
BUCKET_ENV = "MDX_EVAL_ASR_URI"
DEFAULT_BUCKET = "s3://notes-eval/asr/v1"

Language = Literal["de", "uk", "en"]
Kind = Literal["client_call", "internal_meeting", "interview", "podcast", "lecture", "voice_memo"]
NonSpeechKind = Literal["music", "jingle", "silence", "ad", "noise"]
EntityType = Literal["person", "company", "product", "place", "other"]

# Sprint TQ1 T2: the minimum the first gold set must hold.
COMPOSITION: dict[str, int] = {
    "recordings": 14,
    "de": 5,
    "uk": 4,
    "en": 3,
    "code_switch": 2,
    "over_45_min": 3,
    "non_speech_30s": 4,
    "split_dev": 5,
    "split_test": 9,
}
REQUIRED_KINDS = ("client_call", "internal_meeting", "interview", "podcast")
# The two podcast regression cases the audits are about; their ids are fixed.
REGRESSION_IDS = ("r03", "r04")
# The labelling policy's fillers: a reference that still carries one was not
# labelled to verbatim-lite (docs/eval/asr-labelling.md §2).
POLICY_FILLERS = re.compile(r"(?<!\w)(äh|ähm|öhm|uh|um|uhm|erm|ем|еее)(?!\w)", re.IGNORECASE)
# An id is a label, not a description: lowercase, digits, dashes, short.
ID_PATTERN = r"^[a-z0-9][a-z0-9-]{1,23}$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ManifestRow(_Strict):
    id: str = Field(pattern=ID_PATTERN)
    language: Language
    kinds: list[Kind] = Field(min_length=1)
    minutes: float = Field(gt=0, le=240)
    speakers: int = Field(ge=1, le=20)
    split: Literal["dev", "test"]
    consent_ref: str | None = Field(default=None, pattern=r"^C-\d{4}-\d{3}$")
    licence: str | None = None
    public: bool = False
    has_non_speech: bool = False
    non_speech_seconds: float = Field(default=0, ge=0)
    has_code_switch: bool = False
    code_switch_languages: list[Language] = Field(default_factory=list)
    # Human passes over the reference: 2 by different people on the test split.
    reference_passes: int = Field(default=0, ge=0, le=5)
    audio_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _provenance(self) -> ManifestRow:
        if self.public and not self.licence:
            raise ValueError("a public recording states its licence")
        # Third-party broadcasts kept for internal eval (r03, r04) state the
        # basis in `licence`; recordings of people state their consent.
        if not self.public and not (self.consent_ref or self.licence):
            raise ValueError("a non-public recording names its consent_ref or licence")
        if self.has_code_switch and not self.code_switch_languages:
            raise ValueError("has_code_switch names the second language(s)")
        return self


class Manifest(_Strict):
    version: Literal[1]
    notes: str = ""
    recordings: list[ManifestRow]


class RefSegment(_Strict):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    speaker: str = Field(min_length=1)
    text: str = Field(min_length=1)
    language: Language


class EntitySpan(_Strict):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    text: str = Field(min_length=1)  # canonical spelling; groups mentions
    type: EntityType
    language: Language | None = None
    accept: list[str] = Field(default_factory=list)  # inflected forms (Welcherings)


class NumberSpan(_Strict):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    text: str = Field(min_length=1)
    kind: Literal["number", "date"]
    language: Language | None = None
    accept: list[str] = Field(default_factory=list)


class NonSpeechRegion(_Strict):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    kind: NonSpeechKind


class CodeSwitchRegion(_Strict):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    language: Language


class Spans(_Strict):
    entities: list[EntitySpan] = Field(default_factory=list)
    numbers: list[NumberSpan] = Field(default_factory=list)
    non_speech: list[NonSpeechRegion] = Field(default_factory=list)
    code_switch: list[CodeSwitchRegion] = Field(default_factory=list)


class AlignedWord(_Strict):
    text: str
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)


# ── Loading ──────────────────────────────────────────────────────────


def load_manifest(corpus: Path) -> Manifest:
    return Manifest.model_validate_json((corpus / "manifest.json").read_text("utf-8"))


def recording_dir(corpus: Path, rec_id: str) -> Path:
    return corpus / rec_id


def audio_path(corpus: Path, rec_id: str) -> Path | None:
    hits = sorted(recording_dir(corpus, rec_id).glob("audio.*"))
    return hits[0] if hits else None


def load_reference(corpus: Path, rec_id: str) -> list[dict[str, Any]]:
    raw = json.loads((recording_dir(corpus, rec_id) / "reference.json").read_text("utf-8"))
    return [RefSegment.model_validate(s).model_dump() for s in raw]


def load_spans(corpus: Path, rec_id: str) -> dict[str, Any]:
    path = recording_dir(corpus, rec_id) / "spans.json"
    if not path.exists():
        return Spans().model_dump()
    return Spans.model_validate_json(path.read_text("utf-8")).model_dump()


def load_alignment(corpus: Path, rec_id: str) -> list[dict[str, Any]] | None:
    path = recording_dir(corpus, rec_id) / "alignment.json"
    if not path.exists():
        return None
    return [AlignedWord.model_validate(w).model_dump() for w in json.loads(path.read_text("utf-8"))]


# ── Checks ───────────────────────────────────────────────────────────


def composition_problems(rows: list[ManifestRow]) -> list[str]:
    counts: Counter[str] = Counter()
    counts["recordings"] = len(rows)
    for r in rows:
        counts[r.language] += 1
        counts["code_switch"] += r.has_code_switch
        counts["over_45_min"] += r.minutes > 45
        counts["non_speech_30s"] += r.has_non_speech and r.non_speech_seconds >= 30
        counts[f"split_{r.split}"] += 1
    problems = [
        f"composition: {key} {counts[key]} < {minimum}"
        for key, minimum in COMPOSITION.items()
        if counts[key] < minimum
    ]
    kinds = {k for r in rows for k in r.kinds}
    problems += [f"composition: no recording of kind {k}" for k in REQUIRED_KINDS if k not in kinds]
    ids = {r.id for r in rows}
    problems += [
        f"composition: regression case {i} missing" for i in REGRESSION_IDS if i not in ids
    ]
    return problems


def _timeline_problems(rec_id: str, items: list[Any], what: str, limit_ms: int) -> list[str]:
    out = []
    for k, it in enumerate(items):
        if it.end_ms <= it.start_ms:
            out.append(f"{rec_id}: {what}[{k}] ends before it starts")
        if it.end_ms > limit_ms:
            out.append(f"{rec_id}: {what}[{k}] ends after the recording")
    return out


def content_problems(corpus: Path, row: ManifestRow) -> list[str]:
    rec = row.id
    folder = recording_dir(corpus, rec)
    if not folder.is_dir():
        return [f"{rec}: not fetched (run `asr_gold.py fetch`)"]
    problems: list[str] = []
    if audio_path(corpus, rec) is None:
        problems.append(f"{rec}: audio missing")
    limit = int(row.minutes * 60_000) + 5_000
    try:
        raw = json.loads((folder / "reference.json").read_text("utf-8"))
        ref = [RefSegment.model_validate(s) for s in raw]
    except FileNotFoundError:
        return [*problems, f"{rec}: reference.json missing"]
    except (ValidationError, json.JSONDecodeError) as exc:
        return [*problems, f"{rec}: reference.json invalid ({type(exc).__name__})"]
    problems += _timeline_problems(rec, ref, "reference", limit)
    if any(b.start_ms < a.start_ms for a, b in zip(ref, ref[1:], strict=False)):
        problems.append(f"{rec}: reference segments out of time order")
    fillers = sum(1 for s in ref if POLICY_FILLERS.search(s.text))
    if fillers:
        problems.append(
            f"{rec}: {fillers} reference segments carry a filler (verbatim-lite drops them)"
        )
    languages = {s.language for s in ref}
    if row.language not in languages:
        problems.append(f"{rec}: no reference segment in the manifest language")
    if row.has_code_switch and not (languages - {row.language}):
        problems.append(f"{rec}: has_code_switch but every reference segment is {row.language}")
    try:
        spans = Spans.model_validate_json((folder / "spans.json").read_text("utf-8"))
    except FileNotFoundError:
        problems.append(f"{rec}: spans.json missing")
        spans = Spans()
    except ValidationError as exc:
        problems.append(f"{rec}: spans.json invalid ({exc.error_count()} errors)")
        spans = Spans()
    for what, items in (
        ("entities", spans.entities),
        ("numbers", spans.numbers),
        ("non_speech", spans.non_speech),
        ("code_switch", spans.code_switch),
    ):
        problems += _timeline_problems(rec, items, what, limit)
    ns_seconds = sum(r.end_ms - r.start_ms for r in spans.non_speech) / 1000
    if row.has_non_speech and not spans.non_speech:
        problems.append(f"{rec}: has_non_speech but spans.json marks no region")
    if abs(ns_seconds - row.non_speech_seconds) > 5:
        problems.append(
            f"{rec}: non_speech_seconds {row.non_speech_seconds} ≠ spans {ns_seconds:.0f}"
        )
    if row.has_code_switch and not spans.code_switch:
        problems.append(f"{rec}: has_code_switch but spans.json marks no region")
    if not (folder / "reference.rttm").exists():
        problems.append(f"{rec}: reference.rttm missing")
    if row.split == "test" and row.reference_passes < 2:
        problems.append(f"{rec}: test split needs 2 reference passes, has {row.reference_passes}")
    return problems


def validate(corpus: Path, *, content: bool) -> list[str]:
    try:
        manifest = load_manifest(corpus)
    except FileNotFoundError:
        return [f"{corpus}/manifest.json missing"]
    except ValidationError as exc:
        return [f"manifest: {e['loc']} {e['msg']}" for e in exc.errors()]
    problems: list[str] = []
    ids = [r.id for r in manifest.recordings]
    problems += [f"manifest: duplicate id {i}" for i, n in Counter(ids).items() if n > 1]
    problems += composition_problems(manifest.recordings)
    if content:
        for row in manifest.recordings:
            problems += content_problems(corpus, row)
    return problems


def fetch(corpus: Path) -> int:
    """Mirror the bucket prefix into the local corpus folder (needs the eval
    role's credentials in the environment, as ``fetch_speaker_corpus.py``)."""
    bucket = os.environ.get(BUCKET_ENV, DEFAULT_BUCKET)
    if "eval" not in bucket or not bucket.rstrip("/").endswith("asr/v1"):
        print(f"refused: {bucket} is not the ASR eval prefix", file=sys.stderr)
        return 2
    manifest = load_manifest(corpus)
    for row in manifest.recordings:
        dest = recording_dir(corpus, row.id)
        dest.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "aws",
                "s3",
                "sync",
                f"{bucket.rstrip('/')}/{row.id}/",
                str(dest),
                "--only-show-errors",
            ],
            check=True,
        )
        os.chmod(dest, 0o700)
    print(f"fetched {len(manifest.recordings)} recordings into {corpus}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate")
    v.add_argument("corpus", type=Path, nargs="?", default=DEFAULT_CORPUS)
    v.add_argument("--content", action="store_true", help="also check the fetched reference files")
    f = sub.add_parser("fetch")
    f.add_argument("corpus", type=Path, nargs="?", default=DEFAULT_CORPUS)
    args = ap.parse_args(argv)
    if args.cmd == "fetch":
        return fetch(args.corpus)
    problems = validate(args.corpus, content=args.content)
    for p in problems:
        print(p)
    print(f"{len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
