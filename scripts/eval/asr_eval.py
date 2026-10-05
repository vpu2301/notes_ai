#!/usr/bin/env python3
"""Sprint TQ1 T3 — the ASR gold-set harness.

    make eval-asr BACKEND=inproc_cpu_asr SPLIT=test        # → docs/eval/asr-<date>-<backend>-<split>.{json,md}
    make eval-asr-assert BACKEND=inproc_cpu_asr            # r03 / r04 regression checklists

    uv run --project services/asr-worker python scripts/eval/asr_eval.py run \\
        --backend dev_mac_asr --split dev [--ids r04,de-003] [--hint-file hint.txt] [--draft]

Every recording goes through ``asr_worker.processor.decode_recording`` — the
function a production job calls: the backend named in ``config/models.yaml``,
then the prompt-echo guard, the coverage pass and the second decode. Nothing
here decodes around it, so a guard TQ2 adds to the worker is measured here
without touching this file.

Language is ``auto`` (what the clients send) unless ``--pin-language``.
No vocabulary hint unless ``--hint-file`` (TQ1 T4 runs with and without).

Output rule (repo rules): the report carries ids, counts and rates. The
transcripts, heard spellings and per-word timing errors go to
``scripts/eval/local/asr-<backend>/`` (gitignored).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any
from uuid import UUID

os.environ.setdefault("MD_ASR_DEVICE", "cpu")
os.environ.setdefault("MD_ASR_COMPUTE_TYPE", "int8")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
os.environ.setdefault("TESTING", "true")

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "services" / "asr-worker" / "src"))
# Sprint TQ3: the spelling overlay is asr-service's; the eval scores the
# view a reader gets, so it applies the same pure functions.
sys.path.insert(0, str(REPO / "services" / "asr-service" / "src"))
sys.path.insert(0, str(REPO / "scripts" / "eval"))

import asr_gold  # noqa: E402
import asr_scoring  # noqa: E402
import coverage_assert  # noqa: E402
from _common import write_report  # noqa: E402

LOCAL = REPO / "scripts" / "eval" / "local"
ASSERTIONS = REPO / "tests" / "fixtures" / "eval" / "asr" / "assertions"
# Headline columns of the markdown report, in TR order.
HEADLINE = (
    ("wer", "TR-01 WER"),
    ("halluc_chars_per_nonspeech_min", "TR-02 halluc chars/min"),
    ("artefact_hits", "TR-02 artefacts"),
    ("speech_coverage", "TR-03 coverage"),
    ("unexplained_gaps", "TR-03 unexplained gaps"),
    ("entity_error_rate", "TR-04 entity err"),
    ("number_date_error_rate", "TR-04 num/date err"),
    ("entity_consistency", "TR-05 consistency"),
    ("codeswitch_coverage", "TR-06 code-switch"),
    ("translated_segments", "TR-06 translated"),
    ("nonspeech_marked", "TR-07 marked"),
    ("word_ts_median_ms", "TR-08 ts median ms"),
    ("word_ts_p90_ms", "TR-08 ts p90 ms"),
    ("punctuated_share", "TR-09 punctuated"),
    ("rtf_p95", "TR-12 rtf p95"),
)


# ── Backend ──────────────────────────────────────────────────────────


def _resolve(backend: str) -> tuple[Any, str]:
    """The backend from the committed registry, in the first env that allows
    it (``hf_eu_asr`` is staging/prod only — the eval may still call it)."""
    from asr_worker.config import settings
    from models import ConfigError, Registry

    last: Exception | None = None
    for env in (settings.registry_env(), "dev", "staging", "prod", "test"):
        try:
            registry = Registry.load(
                settings.models_config, env=env, environ=os.environ, validate=False
            )
            return registry.backend(backend, expect_kind="asr"), env
        except ConfigError as exc:
            last = exc
            if exc.code not in ("backend_not_allowed_in_env", "missing_env"):
                raise
    raise SystemExit(f"backend {backend!r} cannot be resolved here: {last}")


async def _provider(backend: str) -> tuple[Any, dict[str, Any]]:
    from asr_worker.config import settings
    from asr_worker.inference import WhisperEngine
    from models import build_asr_provider

    os.chdir(REPO)  # config/models.yaml is relative to the repo root
    resolved, env = _resolve(backend)
    engine = WhisperEngine() if resolved.kind == "asr_inproc" else None
    provider = build_asr_provider(resolved, inproc_engine=engine)
    started = time.monotonic()
    await provider.warm_up()
    info = {
        "backend": backend,
        "kind": resolved.kind,
        "registry_env": env,
        "model": getattr(provider, "model_name", None) or resolved.model_id,
        "warm_up_seconds": round(time.monotonic() - started, 1),
    }
    if resolved.kind == "asr_inproc":
        info.update(device=settings.asr_device, compute_type=settings.asr_compute_type)
    return provider, info


async def transcribe(
    provider: Any, audio: bytes, *, language: str, hint: str | None, guards: bool = True
) -> tuple[Any, float, float]:
    """``(output, audio_seconds, wall_seconds)`` through the job's path.
    ``guards`` is ``MDX_ASR_GATES_ENABLED`` for this decode (off = dry run:
    diagnostics still say what would have been dropped)."""
    from asr_worker import processor
    from asr_worker.audio_io import decode_to_pcm
    from asr_worker.config import settings

    settings.asr_gates_enabled = guards
    pcm = await decode_to_pcm(audio)
    audio_seconds = pcm.shape[0] / 16_000
    max_infer = max(60.0, audio_seconds * settings.asr_max_inference_seconds_multiplier)
    state = type("EvalState", (), {"engine": provider})()
    started = time.monotonic()
    output = await processor.decode_recording(
        state,
        pcm,
        stereo=None,
        language=language,
        prompt=hint,
        first_frame_offset_ms=None,
        timeout=max_infer,
        deadline=time.monotonic() + max_infer,
        should_cancel=None,
        job_id=UUID(int=0),
    )
    return output, audio_seconds, time.monotonic() - started


def unified_view(output: Any, language: str) -> tuple[Any, Any]:
    """The transcript as the result view serves it: the TQ3 overlay's
    accepted corrections applied (no glossary or calendar in the eval —
    majority only, the hardest case)."""
    from asr_service.domain import entity_unify

    plan = entity_unify.plan(output, language=language)
    accepted = [
        entity_unify.Applied(p.to_text, p.from_forms, p.occurrences)
        for p in plan.proposals
        if p.status == "accepted"
    ]
    return entity_unify.apply(output, accepted), plan


# ── Local (gitignored) artefacts ─────────────────────────────────────


def _write_local(backend: str, rec_id: str, output: Any, row: dict[str, Any]) -> None:
    folder = LOCAL / f"asr-{backend}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{rec_id}.txt").write_text(
        "\n".join(
            f"[{s.start_ms // 1000:>5}s]{' [' + s.language + ']' if s.language else ''} {s.text}"
            for s in output.segments
        )
        + "\n",
        encoding="utf-8",
    )
    (folder / f"{rec_id}.output.json").write_text(
        output.model_dump_json(indent=1), encoding="utf-8"
    )
    (folder / f"{rec_id}.local.json").write_text(
        json.dumps(row.get("_local", {}), ensure_ascii=False, indent=1), encoding="utf-8"
    )


def _write_draft(rec_id: str, output: Any) -> Path:
    """A reference draft for the labeller: the backend's segments in the
    reference format, speaker ``?``. The labeller edits it from the audio."""
    folder = LOCAL / "asr-draft"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{rec_id}.reference.json"
    draft = [
        {
            "start_ms": s.start_ms,
            "end_ms": max(s.end_ms, s.start_ms + 1),
            "speaker": s.speaker or "?",
            "text": s.text,
            "language": s.language or output.language,
        }
        for s in output.segments
        if s.text.strip()
    ]
    path.write_text(json.dumps(draft, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path


# ── Assertions ───────────────────────────────────────────────────────


def assertion_files() -> dict[str, dict[str, Any]]:
    """Manifest id → checklist, for checklists that name a gold recording."""
    out: dict[str, dict[str, Any]] = {}
    for path in sorted(ASSERTIONS.glob("*.assertions.json")):
        checklist = json.loads(path.read_text("utf-8"))
        if checklist.get("recording"):
            out[checklist["recording"]] = checklist
    return out


# ── Report ───────────────────────────────────────────────────────────


def _group(rows: dict[str, dict[str, Any]], manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {"all": list(rows.values())}
    for rec_id, row in rows.items():
        m = manifest[rec_id]
        groups.setdefault(m.language, []).append(row)
        if m.has_code_switch:
            groups.setdefault("code_switch", []).append(row)
    out = {name: asr_scoring.aggregate(items) for name, items in groups.items()}
    for lang in asr_scoring.LANGUAGES:
        out.setdefault(lang, asr_scoring.aggregate([]))
    return out


def _corpus_label(corpus: Path) -> str:
    try:
        return str(corpus.resolve().relative_to(REPO))
    except ValueError:
        return "outside-repo"


def _fmt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.3f}" if value < 10 else f"{value:.0f}"
    return str(value)


def markdown(payload: dict[str, Any]) -> str:
    lines = [
        f"# ASR eval — {payload['backend']} — {payload['split']} ({payload['date']})",
        "",
        f"Model `{payload['provider']['model']}`, git `{payload['git']}`, corpus manifest "
        f"`{payload['corpus_manifest_sha256'][:12]}`, hint `{payload['hint']}`, language "
        f"`{payload['language_mode']}`. Numbers and ids only.",
        "",
        "| group | n | " + " | ".join(label for _k, label in HEADLINE) + " |",
        "|---|---|" + "---|" * len(HEADLINE),
    ]
    for name in ("de", "uk", "en", "code_switch", "all"):
        agg = payload["by_language"].get(name)
        if agg is None:
            continue
        if agg["not_measured"] and name != "all":
            lines.append(
                f"| {name} | {agg['n']} | not measured (n < 3) |" + " |" * (len(HEADLINE) - 1)
            )
            continue
        flag = " (directional)" if agg["directional"] else ""
        lines.append(
            f"| {name}{flag} | {agg['n']} | "
            + " | ".join(_fmt(agg.get(k)) for k, _l in HEADLINE)
            + " |"
        )
    if payload.get("by_language_guards_off"):
        lines += ["", "## Guards off → on (same backend, same audio)", ""]
        lines += ["| group | metric | off | on |", "|---|---|---|---|"]
        for name in ("de", "uk", "en", "all"):
            off = payload["by_language_guards_off"].get(name)
            on = payload["by_language"].get(name)
            if not off or not on or (on.get("not_measured") and name != "all"):
                continue
            for key, label in HEADLINE:
                lines.append(f"| {name} | {label} | {_fmt(off.get(key))} | {_fmt(on.get(key))} |")
    if payload.get("assertions"):
        lines += ["", "## Regression checklists", ""]
        for rec, results in payload["assertions"].items():
            lines.append(f"- **{rec}**: " + ", ".join(f"{n} {s}" for n, s in results))
    lines += [
        "",
        "Directional: n < 20 per language. Not measured: n < 3 (never a pass).",
        "WER on speech regions after `asr_scoring.normalise`; hallucination counts",
        "music, jingle, silence and noise regions, not ad reads.",
        "",
    ]
    return "\n".join(lines)


async def run(args: argparse.Namespace) -> int:
    corpus = Path(args.corpus)
    manifest = asr_gold.load_manifest(corpus)
    rows_by_id = {r.id: r for r in manifest.recordings}
    wanted = [r for r in manifest.recordings if args.split in (r.split, "all")]
    if args.ids:
        ids = set(args.ids.split(","))
        wanted = [r for r in manifest.recordings if r.id in ids]
    if not wanted:
        print(
            f"no recordings in {corpus} for split={args.split} ids={args.ids or '-'}",
            file=sys.stderr,
        )
        return 3
    hint = Path(args.hint_file).read_text("utf-8").strip() if args.hint_file else None
    provider, info = await _provider(args.backend)
    checklists = assertion_files()
    rows: dict[str, dict[str, Any]] = {}
    before_rows: dict[str, dict[str, Any]] = {}
    results: dict[str, list[tuple[str, str]]] = {}
    skipped: dict[str, str] = {}
    for rec in wanted:
        audio = asr_gold.audio_path(corpus, rec.id)
        if audio is None:
            skipped[rec.id] = "not_fetched"
            print(f"  {rec.id:<12} skipped: audio not fetched", flush=True)
            continue
        language = rec.language if args.pin_language else "auto"
        if args.guards == "both" and not args.draft:
            off, off_audio_s, off_wall_s = await transcribe(
                provider, audio.read_bytes(), language=language, hint=hint, guards=False
            )
            with contextlib.suppress(FileNotFoundError):
                before_rows[rec.id] = asr_scoring.score_recording(
                    reference=asr_gold.load_reference(corpus, rec.id),
                    spans=asr_gold.load_spans(corpus, rec.id),
                    alignment=asr_gold.load_alignment(corpus, rec.id),
                    hyp=off,
                    language=rec.language,
                    audio_seconds=off_audio_s,
                    wall_seconds=off_wall_s,
                )
        output, audio_s, wall_s = await transcribe(
            provider,
            audio.read_bytes(),
            language=language,
            hint=hint,
            guards=args.guards != "off" or args.draft,
        )
        if args.draft:
            print(f"  {rec.id:<12} draft → {_write_draft(rec.id, output)}", flush=True)
            continue
        try:
            reference = asr_gold.load_reference(corpus, rec.id)
        except FileNotFoundError:
            skipped[rec.id] = "no_reference"
            print(f"  {rec.id:<12} skipped: no reference.json", flush=True)
            continue
        spans = asr_gold.load_spans(corpus, rec.id)
        # Sprint TQ3: entities are scored on the applied view (what every
        # reader sees); the raw artefact's numbers are kept beside them.
        view, plan = unified_view(output, rec.language)
        row = asr_scoring.score_recording(
            reference=reference,
            spans=spans,
            alignment=asr_gold.load_alignment(corpus, rec.id),
            hyp=view,
            language=rec.language,
            audio_seconds=audio_s,
            wall_seconds=wall_s,
        )
        raw_entities = asr_scoring.entity_errors(spans, output, rec.language)
        raw_consistency = asr_scoring.entity_consistency(spans, output, rec.language)
        row["entities_wrong_raw"] = raw_entities["entities_wrong"]
        row["entity_consistency_raw"] = (
            sum(v["consistency"] for v in raw_consistency.values()) / len(raw_consistency)
            if raw_consistency
            else None
        )
        row.update(asr_scoring.merge_quality(plan, spans))
        _write_local(args.backend, rec.id, view, row)
        if rec.id in checklists:
            results[rec.id] = coverage_assert.statuses(checklists[rec.id]["assertions"], view)
        diags = output.diagnostics
        row["dropped_segments"] = len(diags.dropped_segments)
        row["dropped_by_reason"] = dict(Counter(d.reason for d in diags.dropped_segments))
        row["dropped_artefacts"] = dict(
            Counter(d.artefact for d in diags.dropped_segments if d.artefact)
        )
        row["gate_unavailable"] = dict(diags.gate_unavailable)
        row["language_id"] = diags.language_id
        rows[rec.id] = row
        print(
            f"  {rec.id:<12} {rec.language} wer={_fmt(row['wer'])} halluc={row['halluc_chars']}"
            f" artefacts={row['artefact_hits']} rtf={_fmt(row['rtf'])}",
            flush=True,
        )
    if args.draft:
        return 0
    manifest_bytes = (corpus / "manifest.json").read_bytes()
    public_rows = {k: {kk: vv for kk, vv in v.items() if kk != "_local"} for k, v in rows.items()}
    payload = {
        "split": args.split,
        "corpus": _corpus_label(corpus),
        "corpus_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "provider": info,
        "language_mode": "pinned" if args.pin_language else "auto",
        "hint": f"given ({len(hint.split(','))} terms)" if hint else "none",
        "guards": args.guards,
        "by_language": _group(rows, rows_by_id),
        "by_language_guards_off": _group(before_rows, rows_by_id) if before_rows else None,
        "recordings": public_rows,
        "skipped": skipped,
        "assertions": results,
    }
    suffix = f"-{args.split}" + (f"-{args.label}" if args.label else "")
    path = write_report("asr", args.backend, payload, suffix=suffix)
    full = json.loads(path.read_text("utf-8"))
    path.with_suffix(".md").write_text(markdown(full), encoding="utf-8")
    print(f"wrote {path} (+ .md)")
    return 0


async def assert_run(args: argparse.Namespace) -> int:
    """The regression checklists that name a gold recording. Exit 1 on an
    unexpected FAIL; 3 when a checklist's recording is not available (not
    measured is never a pass)."""
    corpus = Path(args.corpus)
    manifest = {r.id: r for r in asr_gold.load_manifest(corpus).recordings}
    checklists = assertion_files()
    provider = None
    failed = missing = False
    for rec_id, checklist in checklists.items():
        audio = asr_gold.audio_path(corpus, rec_id) if rec_id in manifest else None
        if audio is None:
            print(f"{rec_id}: NOT RUN — not in {corpus} (manifest row or fetched audio missing)")
            missing = True
            continue
        if provider is None:
            provider, _info = await _provider(args.backend)
        output, _a, _w = await transcribe(provider, audio.read_bytes(), language="auto", hint=None)
        view, _plan = unified_view(output, manifest[rec_id].language)
        for name, status in coverage_assert.statuses(checklist["assertions"], view):
            until = coverage_assert.expected_failures(checklist["assertions"]).get(name)
            print(f"{rec_id}: {name} {status}" + (f" (until {until})" if until else ""))
            failed |= status == "FAIL"
    if failed:
        return 1
    if missing and not args.allow_missing:
        return 3
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="score a backend on a split")
    r.add_argument("--backend", required=True)
    r.add_argument("--split", default="test", choices=["dev", "test", "all"])
    r.add_argument("--corpus", default=str(asr_gold.DEFAULT_CORPUS))
    r.add_argument("--ids", help="comma-separated manifest ids (overrides --split)")
    r.add_argument("--hint-file", help="vocabulary hint sent as the prompt (TQ1 T4 with/without)")
    r.add_argument(
        "--pin-language", action="store_true", help="send the manifest language, not auto"
    )
    r.add_argument("--label", default="", help="report file suffix, e.g. hint")
    r.add_argument(
        "--draft", action="store_true", help="write reference drafts for labelling; no scoring"
    )
    r.add_argument(
        "--guards",
        default="on",
        choices=["on", "off", "both"],
        help="TQ2 gates (MDX_ASR_GATES_ENABLED); both = decode twice, report off and on",
    )
    a = sub.add_parser("assert", help="run the r03/r04 regression checklists")
    a.add_argument("--backend", required=True)
    a.add_argument("--corpus", default=str(asr_gold.DEFAULT_CORPUS))
    a.add_argument("--allow-missing", action="store_true")
    args = ap.parse_args(argv)
    return asyncio.run(run(args) if args.cmd == "run" else assert_run(args))


if __name__ == "__main__":
    sys.exit(main())
