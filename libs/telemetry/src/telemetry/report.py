"""The diagnostics report (telemetry sprint 4): one run's stored record → Markdown.

Pure: no clock, no randomness, no model call. Inputs are re-sorted (spans by start then id,
LLM calls by their span's start then id, missing measurements alphabetically), numbers have one
format each (``%.2f`` seconds, ``%.3f`` rtf, integers with thousands separators), so identical
records give byte-identical reports whatever order they were read in.

Shares of wall time are computed from the union of a stage's span intervals on the critical
path, never from a sum of siblings: spans nest and overlap. A redelivered pickup of a finished
job (``redelivered_after_finish``) and everything under it is off the critical path.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from .report_rules import GIB, RULES, holds
from .schema import LlmCall, RunExport, SpanRecord

INCOMPLETE = "Telemetry for this run is incomplete."
WALL_NOTE = (
    "Wall time is the critical path; stage durations below are not additive where stages overlap."
)
_DASH = "—"


# ── formatting ──


def _s(value: float | None) -> str:
    return _DASH if value is None else f"{value:.2f} s"


def _rtf(value: float | None) -> str:
    return _DASH if value is None else f"{value:.3f}"


def _int(value: int | None) -> str:
    return _DASH if value is None else f"{value:,}"


def _pct(value: float | None) -> str:
    return _DASH if value is None else f"{value * 100:.1f} %"


def _bytes(value: int | None) -> str:
    return _DASH if value is None else f"{value:,} B ({value / GIB:.2f} GiB)"


def _text(value: Any) -> str:
    if value is None:
        return _DASH
    # A pipe would end a table cell.
    return str(value).replace("|", "\\|").replace("\n", " ")


def _missing(value: str, reason: str | None) -> str:
    return f"{value} ({reason})" if reason and value == _DASH else value


def _when(value: datetime | None) -> str:
    return _DASH if value is None else value.isoformat()


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(row) + " |" for row in rows]
    return out


# ── the record, prepared ──


def _attrs(span: SpanRecord) -> dict[str, Any]:
    return span.attributes


def _reasons(span: SpanRecord) -> dict[str, str]:
    reasons = span.attributes.get("_reasons")
    return reasons if isinstance(reasons, dict) else {}


def _duration(span: SpanRecord) -> float | None:
    if span.start_monotonic_ns is not None and span.end_monotonic_ns is not None:
        return (span.end_monotonic_ns - span.start_monotonic_ns) / 1e9
    if span.start_wall_utc is not None and span.end_wall_utc is not None:
        return (span.end_wall_utc - span.start_wall_utc).total_seconds()
    return None


def _start_key(span: SpanRecord) -> tuple[str, str]:
    return (_when(span.start_wall_utc), str(span.span_id))


@dataclass
class _Run:
    export: RunExport
    spans: list[SpanRecord]
    by_id: dict[UUID, SpanRecord]
    children: dict[UUID | None, list[SpanRecord]]
    off_path: set[UUID]
    calls: list[LlmCall]
    wall: float | None

    @property
    def run(self) -> Any:
        return self.export.processing_run

    def on_path(self, span: SpanRecord) -> bool:
        return (
            span.span_id not in self.off_path
            and span.stage != "other"
            and not span.is_parallel_with
            and span.status != "skipped"
        )

    def stage_spans(self, stage: str) -> list[SpanRecord]:
        return [s for s in self.spans if s.stage == stage and s.span_id not in self.off_path]

    def union_seconds(self, spans: list[SpanRecord]) -> float:
        intervals = sorted(
            (s.start_wall_utc, s.end_wall_utc)
            for s in spans
            if s.start_wall_utc is not None and s.end_wall_utc is not None
        )
        total = 0.0
        cur_start: datetime | None = None
        cur_end: datetime | None = None
        for start, end in intervals:
            if cur_end is None or start > cur_end:
                if cur_start is not None and cur_end is not None:
                    total += (cur_end - cur_start).total_seconds()
                cur_start, cur_end = start, end
            elif end > cur_end:
                cur_end = end
        if cur_start is not None and cur_end is not None:
            total += (cur_end - cur_start).total_seconds()
        return total

    def share(self, spans: list[SpanRecord]) -> float | None:
        if not self.wall:
            return None
        return self.union_seconds([s for s in spans if self.on_path(s)]) / self.wall


def _prepare(export: RunExport) -> _Run:
    spans = sorted(export.spans, key=_start_key)
    by_id = {s.span_id: s for s in spans}
    children: dict[UUID | None, list[SpanRecord]] = {}
    for s in spans:
        parent = s.parent_span_id if s.parent_span_id in by_id else None
        children.setdefault(parent, []).append(s)
    off_path: set[UUID] = set()

    def mark(span: SpanRecord) -> None:
        off_path.add(span.span_id)
        for child in children.get(span.span_id, []):
            mark(child)

    for s in spans:
        if s.attributes.get("redelivered_after_finish"):
            mark(s)
    starts = {s.span_id: _start_key(s) for s in spans}
    calls = sorted(
        export.llm_calls,
        key=lambda c: (starts.get(c.span_id, ("~", "")), str(c.llm_call_id)),
    )
    return _Run(
        export=export, spans=spans, by_id=by_id, children=children, off_path=off_path,
        calls=calls, wall=export.processing_run.processing_wall_seconds,
    )  # fmt: skip


# ── missing measurements ──


def missing_measurements(export: RunExport) -> list[dict[str, str]]:
    """Every field that is ``None`` with its reason: ``{group, item, field, reason}``, sorted."""
    out: list[dict[str, str]] = []
    run = export.processing_run
    for field, reason in run.null_reasons.items():
        out.append({"group": "run", "item": "run", "field": field, "reason": reason})
    if export.run_context is None:
        out.append(
            {"group": "context", "item": "context", "field": "run_context", "reason": "unavailable"}
        )
    else:
        for field, reason in export.run_context.null_reasons.items():
            out.append({"group": "context", "item": "context", "field": field, "reason": reason})
    for span in export.spans:
        for field, why in _reasons(span).items():
            out.append({"group": span.stage, "item": span.name, "field": field, "reason": str(why)})
    for call in export.llm_calls:
        for field, reason in call.null_reasons.items():
            item = f"{call.purpose} (attempt {call.attempt})"
            out.append({"group": "llm_call", "item": item, "field": field, "reason": reason})
    unique = {(m["group"], m["item"], m["field"], m["reason"]): m for m in out}
    return [unique[k] for k in sorted(unique)]


# ── sections ──


def _identity(r: _Run) -> list[str]:
    run, ctx = r.run, r.export.run_context
    cr = ctx.null_reasons if ctx else {}
    out = ["## 1. Run identity", ""]
    out += _table(
        ["Field", "Value"],
        [
            ["recording_id", str(run.recording_id)],
            ["processing_run_id", str(run.processing_run_id)],
            ["kind", run.kind + (f" ({run.reprocess_scope})" if run.reprocess_scope else "")],
            ["trigger", run.trigger],
            ["status", run.status],
            ["error category", _text(run.error_category)],
            ["attempt", _int(run.attempts)],
            ["telemetry schema version", _int(run.telemetry_schema_version)],
            ["app commit", _missing(_text(ctx.app_commit if ctx else None), cr.get("app_commit"))],
            ["app build", _missing(_text(ctx.app_build if ctx else None), cr.get("app_build"))],
        ],
    )
    out += ["", "### Hardware & environment", ""]
    if ctx is None:
        out.append("No run context was recorded.")
    else:
        os_text = " ".join(v for v in (ctx.os_name, ctx.os_version) if v) or None
        out += _table(
            ["Field", "Value"],
            [
                ["OS", _missing(_text(os_text), cr.get("os_name"))],
                ["arch", _missing(_text(ctx.arch), cr.get("arch"))],
                ["chip", _missing(_text(ctx.chip_model), cr.get("chip_model"))],
                ["memory", _missing(_bytes(ctx.memory_total_bytes), cr.get("memory_total_bytes"))],
                ["execution mode", ctx.execution_mode],
                [
                    "container limit",
                    _missing(_bytes(ctx.container_mem_limit), cr.get("container_mem_limit")),
                ],
            ],
        )
    out += ["", "### Effective models & backends", ""]
    rows = _models(r)
    if rows:
        out += _table(
            ["Kind", "Backend", "Name", "Revision", "Quantization", "Compute type", "Device",
             "Device source"],
            rows,
        )  # fmt: skip
    else:
        out.append("No model was used in this run.")
    return out


def _device(value: Any) -> tuple[str, str]:
    if isinstance(value, dict) and "value" in value:
        return _text(value.get("value")), _text(value.get("observation"))
    if value is None:
        return _DASH, _DASH
    return _text(value), "configured"


def _models(r: _Run) -> list[list[str]]:
    rows: dict[tuple[str, ...], list[str]] = {}
    for s in r.spans:
        a = _attrs(s)
        if s.stage == "model_init":
            device, source = _device(a.get("device"))
            row = [_text(a.get("model_kind")), _text(a.get("backend")), _text(a.get("model_name")),
                   _text(a.get("model_revision")), _text(a.get("quantization")),
                   _text(a.get("compute_type")), device, source]  # fmt: skip
        elif s.stage in ("diarization_load", "diarization_infer"):
            device, source = _device(a.get("device"))
            row = ["diarization", _text(a.get("backend")), _text(a.get("model")), _DASH, _DASH,
                   _DASH, device, source]  # fmt: skip
        else:
            continue
        rows.setdefault(tuple(row), row)
    ctx = r.export.run_context
    llm_device, llm_source = _device(
        ctx.device_llm.model_dump() if ctx and ctx.device_llm else None
    )
    for c in r.calls:
        row = ["llm", _text(c.backend), _text(c.model), _DASH, _DASH, _DASH, llm_device,
               llm_source]  # fmt: skip
        rows.setdefault(tuple(row), row)
    return [rows[k] for k in sorted(rows)]


def _timing(r: _Run) -> list[str]:
    run = r.run
    nr = run.null_reasons

    def row(label: str, field: str, fmt: Any) -> list[str]:
        return [label, _missing(fmt(getattr(run, field)), nr.get(field))]

    rows = [
        row("audio duration", "audio_duration_seconds", _s),
        row("processing_wall_seconds", "processing_wall_seconds", _s),
        row("rtf", "rtf", _rtf),
        row("speedup", "speedup", _rtf),
        row("user_wait_seconds", "user_wait_seconds", _s),
        row("time_to_transcript_seconds", "time_to_transcript_seconds", _s),
        row("time_to_speaker_labels_seconds", "time_to_speaker_labels_seconds", _s),
        row("time_to_notes_seconds", "time_to_notes_seconds", _s),
    ]
    out = ["## 2. End-to-end timing", ""] + _table(["Metric", "Value"], rows)
    if run.user_wait_cross_device:
        out += ["", "user_wait_seconds spans two devices; their clocks were corrected by the "
                "server-measured offsets."]  # fmt: skip
    return out + ["", WALL_NOTE]


def _stages(r: _Run) -> list[str]:
    run = r.run
    rows: list[list[str]] = []
    parallel_used = False

    def walk(span: SpanRecord, depth: int) -> None:
        nonlocal parallel_used
        name = "· " * depth + _text(span.name)
        if span.is_parallel_with:
            peers = sorted(_text(r.by_id[p].name) for p in span.is_parallel_with if p in r.by_id)
            name += f" (parallel with {', '.join(peers) or 'other work'})"
        duration = _duration(span)
        if span.is_parallel_with:
            share = _DASH + "¹"
            parallel_used = True
        elif r.on_path(span) and duration is not None and r.wall:
            share = _pct(duration / r.wall)
        else:
            share = _DASH
        offset = (
            f"{(span.start_wall_utc - run.submitted_at).total_seconds():+.2f} s"
            if span.start_wall_utc is not None
            else _DASH
        )
        rows.append([span.stage, name, _int(span.attempt), span.status, _s(duration), share,
                     offset])  # fmt: skip
        for child in r.children.get(span.span_id, []):
            walk(child, depth + 1)

    for root in r.children.get(None, []):
        walk(root, 0)
    out = ["## 3. Stage table", ""]
    if not rows:
        return out + ["No spans were recorded."]
    out += _table(
        ["Stage", "Span", "Attempt", "Status", "Duration", "Share of wall",
         "Start offset from submission"],
        rows,
    )  # fmt: skip
    if parallel_used:
        out += ["", "¹ Runs in parallel with other work; not part of the critical-path share."]
    if r.off_path:
        out += ["", "Spans under a redelivered pickup of a finished job are off the critical path."]
    return out


def _asr(r: _Run) -> list[str]:
    run = r.run
    out = ["## 4. ASR breakdown", "", "### VAD", ""]
    vad = r.stage_spans("vad")
    if vad:
        rows = []
        for s in vad:
            a = _attrs(s)
            lengths = [float(x) for x in a.get("run_lengths_seconds") or []]
            rows.append([
                _text(s.name), _s(a.get("speech_seconds")), _int(a.get("run_count")),
                _s(min(lengths)) if lengths else _DASH,
                _s(statistics.median(lengths)) if lengths else _DASH,
                _s(max(lengths)) if lengths else _DASH,
            ])  # fmt: skip
        out += _table(["Span", "Speech", "Runs", "Min run", "Median run", "Max run"], rows)
    else:
        out.append("No VAD span was recorded.")

    out += ["", "### Language checks", ""]
    lid = r.stage_spans("language_detection")
    if lid:
        calls = sum(int(_attrs(s).get("call_count") or 0) for s in lid)
        rows = []
        for s in lid:
            a = _attrs(s)
            detected = a.get("detected") or []
            conf = ", ".join(
                f"{d.get('lang')} {float(d.get('confidence') or 0):.3f}"
                for d in detected
                if isinstance(d, dict)
            )
            rows.append([_text(s.name), _s(a.get("audio_seconds")), _s(_duration(s)),
                         _text(a.get("decided_language")), _text(conf or None)])  # fmt: skip
        out += [f"Language checks: {calls:,}.", ""]
        out += _table(["Span", "Audio", "Wall", "Decided", "Confidences"], rows)
    else:
        out.append("No language check was recorded.")

    out += ["", "### Primary passes", ""]
    primary = r.stage_spans("asr_primary")
    chunks = [s for s in primary if r.children.get(s.span_id) is None] or primary
    if chunks:
        rows = []
        for s in chunks:
            a = _attrs(s)
            audio = a.get("audio_processed_seconds")
            wall = a.get("wall_seconds") if a.get("wall_seconds") is not None else _duration(s)
            rows.append([_text(s.name), _text(a.get("backend")), _s(audio), _s(wall),
                         _rtf(wall / audio if wall is not None and audio else None)])  # fmt: skip
        out += _table(["Pass", "Backend", "Audio", "Wall", "rtf"], rows)
    else:
        out.append("No primary pass was recorded.")

    out += ["", "### Recovery passes", ""]
    recovery = r.stage_spans("asr_recovery")
    if recovery:
        rows = []
        for s in recovery:
            a = _attrs(s)
            rows.append([_text(s.name), _text(a.get("trigger_reason")),
                         _s(a.get("audio_reprocessed_seconds")), _s(a.get("wall_seconds")),
                         _int(a.get("recovered_words"))])  # fmt: skip
        out += _table(["Pass", "Trigger", "Audio reprocessed", "Wall", "Recovered words"], rows)
    else:
        out.append("No recovery pass ran.")

    out += ["", "### Totals", ""]
    ratio = _reprocessing_ratio(r)
    out += _table(
        ["Metric", "Value"],
        [
            ["asr_audio_processed_seconds (sum over passes)",
             _missing(_s(run.asr_audio_processed_seconds),
                      run.null_reasons.get("asr_audio_processed_seconds"))],
            ["audio duration", _missing(_s(run.audio_duration_seconds),
                                        run.null_reasons.get("audio_duration_seconds"))],
            ["reprocessing ratio", _rtf(ratio[0]) if ratio[0] is not None
             else _missing(_DASH, ratio[1])],
        ],
    )  # fmt: skip
    return out


def _reprocessing_ratio(r: _Run) -> tuple[float | None, str | None]:
    run = r.run
    if run.asr_audio_processed_seconds is None:
        return None, run.null_reasons.get("asr_audio_processed_seconds", "not_measured")
    if not run.audio_duration_seconds:
        return None, run.null_reasons.get("audio_duration_seconds", "not_measured")
    return run.asr_audio_processed_seconds / run.audio_duration_seconds, None


def _overlap(a: list[SpanRecord], b: list[SpanRecord], r: _Run) -> float:
    return r.union_seconds(a) + r.union_seconds(b) - r.union_seconds(a + b)


def _diarization(r: _Run) -> list[str]:
    out = ["## 5. Diarization", ""]
    load, infer = r.stage_spans("diarization_load"), r.stage_spans("diarization_infer")
    if not load and not infer:
        return out + ["Diarization did not run."]
    rows = []
    for s in load + infer:
        a = _attrs(s)
        device, source = _device(a.get("device"))
        seconds = a.get("load_seconds") if s.stage == "diarization_load" else a.get("infer_seconds")
        rows.append([
            s.stage.removeprefix("diarization_"), s.status, _s(seconds), _text(a.get("state")),
            _text(a.get("backend")), _text(a.get("model")), f"{device} ({source})",
            _int(a.get("speakers_detected")), _pct(a.get("unknown_speaker_share")),
        ])  # fmt: skip
    out += _table(
        ["Step", "Status", "Seconds", "State", "Backend", "Model", "Device", "Speakers",
         "Unknown-speaker share"],
        rows,
    )  # fmt: skip
    overlap = _overlap(load + infer, r.stage_spans("asr_primary"), r)
    out += ["", f"Overlap with ASR: {overlap:.2f} s"
            + (" (sequential)." if overlap == 0 else " (parallel).")]  # fmt: skip
    return out


def _llm(r: _Run) -> list[str]:
    out = ["## 6. LLM usage", ""]
    if not r.calls:
        return out + ["No LLM call in this run."]
    estimated = False
    rows = []

    def tok(value: int | None, c: LlmCall, field: str) -> str:
        nonlocal estimated
        if value is None:
            return _missing(_DASH, c.null_reasons.get(field))
        if c.token_source == "estimated":
            estimated = True
            return f"{value:,}*"
        return f"{value:,}"

    for c in r.calls:
        rows.append([
            c.purpose, f"{_text(c.provider)} / {_text(c.model)} / {_text(c.backend)}",
            _int(c.attempt), c.status,
            _missing(_s(c.time_to_first_token_seconds),
                     c.null_reasons.get("time_to_first_token_seconds")),
            _s(c.total_latency_seconds), tok(c.input_tokens, c, "input_tokens"), tok(c.cached_input_tokens, c, "cached_input_tokens"),
            tok(c.reasoning_tokens, c, "reasoning_tokens"), tok(c.output_tokens, c, "output_tokens"),
            _missing(_text(None if c.generation_tokens_per_second is None
                           else f"{c.generation_tokens_per_second:.2f}"),
                     c.null_reasons.get("generation_tokens_per_second")),
        ])  # fmt: skip

    def total(field: str) -> str:
        values = [getattr(c, field) for c in r.calls if getattr(c, field) is not None]
        return f"{sum(values):,}" if values else _DASH

    latency = [c.total_latency_seconds for c in r.calls if c.total_latency_seconds is not None]
    rows.append(["**total**", "", _int(len(r.calls)), "", "",
                 _s(sum(latency)) if latency else _DASH, total("input_tokens"),
                 total("cached_input_tokens"), total("reasoning_tokens"), total("output_tokens"),
                 ""])  # fmt: skip
    out += _table(
        ["Purpose", "Provider / model / backend", "Attempt", "Status", "TTFT", "Latency",
         "Input", "Cached", "Reasoning", "Output", "tok/s"],
        rows,
    )  # fmt: skip
    notes = sorted({c.token_accounting_note for c in r.calls if c.token_accounting_note})
    out += [
        "",
        "Token accounting: " + ("; ".join(notes) if notes else "as reported by the provider."),
    ]
    if estimated:
        out += ["", "\\* estimated, not reported by the provider."]
    return out


def _memory(r: _Run) -> list[str]:
    run, ctx = r.run, r.export.run_context
    missing = missing_measurements(r.export)
    out = ["## 7. Memory & resources, missing measurements", ""]
    if missing:
        out += [INCOMPLETE, ""]
    rows: list[list[str]] = []
    if ctx is not None:
        cr = ctx.null_reasons

        def pair(label: str, start: str, end: str, fmt: Any) -> list[str]:
            return [label,
                    _missing(fmt(getattr(ctx, start)), cr.get(start)) + " → "
                    + _missing(fmt(getattr(ctx, end)), cr.get(end))]  # fmt: skip

        rows += [
            pair("process RSS", "process_rss_start", "process_rss_end", _bytes),
            pair("swap used", "swap_used_start", "swap_used_end", _bytes),
            pair("memory pressure", "memory_pressure_start", "memory_pressure_end", _text),
        ]
    activity = ", ".join(
        sorted(f"{a.kind}:{a.backend}" for a in run.other_model_activity)
    )  # fmt: skip
    nr = run.null_reasons
    rows += [
        ["concurrent runs at start", _missing(_int(run.concurrent_runs_at_start),
                                              nr.get("concurrent_runs_at_start"))],
        ["other model activity", activity or "none"],
        ["telemetry overhead", _missing(_s(run.telemetry_overhead_seconds),
                                        nr.get("telemetry_overhead_seconds"))],
        ["telemetry buffer peak", _missing(_text(None if run.telemetry_buffer_peak_bytes is None
                                                 else f"{run.telemetry_buffer_peak_bytes:,} B"),
                                           nr.get("telemetry_buffer_peak_bytes"))],
    ]  # fmt: skip
    out += _table(["Resource", "Value"], rows)
    out += ["", "### Missing measurements", ""]
    if not missing:
        return out + ["None."]
    group: str | None = None
    for m in missing:
        if m["group"] != group:
            group = m["group"]
            out += [f"- **{group}**"]
        out += [f"  - {m['item']}: `{m['field']}` ({m['reason']})"]
    return out


# ── facts, measured and hypotheses ──


def _facts(r: _Run) -> tuple[dict[str, Any], dict[str, str]]:
    run, ctx = r.run, r.export.run_context
    values: dict[str, Any] = {}
    reasons: dict[str, str] = {}

    def put(name: str, value: Any, reason: str | None) -> None:
        if value is None:
            reasons[name] = reason or "not_measured"
        else:
            values[name] = value

    wall_reason = run.null_reasons.get("processing_wall_seconds", "not_measured")
    put("rtf", run.rtf, run.null_reasons.get("rtf"))
    primary = r.stage_spans("asr_primary")
    put("asr_primary_share", r.share(primary) if primary else None,
        wall_reason if not r.wall else "not_measured")  # fmt: skip
    ratio, ratio_reason = _reprocessing_ratio(r)
    put("reprocessing_ratio", ratio, ratio_reason)
    if ratio is not None:
        values["reprocessed_share"] = max(0.0, ratio - 1)
    cold = [s for s in r.stage_spans("model_init") if _attrs(s).get("state") == "cold"]
    cold += [s for s in r.stage_spans("diarization_load") if _attrs(s).get("state") == "cold"]
    put("cold_model_init_share", (r.share(cold) or 0.0) if r.wall else None, wall_reason)
    shares = [
        float(_attrs(s)["unknown_speaker_share"])
        for s in r.stage_spans("diarization_infer")
        if _attrs(s).get("unknown_speaker_share") is not None
    ]
    infer = r.stage_spans("diarization_infer")
    put("unknown_speaker_share", max(shares) if shares else None,
        "not_applicable" if not infer
        else str(_reasons(infer[0]).get("unknown_speaker_share", "not_measured")))  # fmt: skip
    if ctx is None:
        for name in (
            "swap_delta_bytes",
            "device_asr_observation",
            "device_diarization_observation",
        ):
            reasons[name] = "unavailable"
        return values, reasons
    if ctx.swap_used_start is not None and ctx.swap_used_end is not None:
        values["swap_delta_bytes"] = ctx.swap_used_end - ctx.swap_used_start
        values["swap_delta_gib"] = values["swap_delta_bytes"] / GIB
    else:
        reasons["swap_delta_bytes"] = ctx.null_reasons.get(
            "swap_used_start", ctx.null_reasons.get("swap_used_end", "not_measured")
        )
    for kind in ("asr", "diarization"):
        device = getattr(ctx, f"device_{kind}")
        if device is None:
            reasons[f"device_{kind}_observation"] = ctx.null_reasons.get(
                f"device_{kind}", "unavailable"
            )
        else:
            values[f"device_{kind}_observation"] = device.observation
            values[f"device_{kind}"] = device.value
    return values, reasons


def hypotheses(r: _Run) -> tuple[list[str], list[str]]:
    """The fired and not-assessable lines, and the ids of the rules checked that did not fire."""
    values, reasons = _facts(r)
    out: list[str] = []
    quiet: list[str] = []
    for rule in RULES:
        missing = [f for f in rule.inputs if f not in values]
        if missing:
            field = missing[0]
            out.append(
                f"Not assessable: {field} unavailable ({reasons.get(field, 'not_measured')})"
                f" — rule `{rule.id}`."
            )
        elif all(holds(c, values[c.fact]) for c in rule.conditions):
            shown = values | {f"{k}_pct": _pct(v) for k, v in values.items() if k.endswith("share")}
            out.append("Hypothesis: " + rule.text.format(**shown))
        else:
            quiet.append(rule.id)
    return out, quiet


def _bottleneck(r: _Run) -> list[str]:
    run = r.run
    out = ["## 8. Bottleneck summary", "", "### Measured", ""]
    stages = sorted({s.stage for s in r.spans if r.on_path(s)})
    durations = [(r.union_seconds([s for s in r.stage_spans(st) if r.on_path(s)]), st)
                 for st in stages]  # fmt: skip
    top = sorted(durations, key=lambda d: (-d[0], d[1]))[:3]
    if top:
        parts = [f"{st} {secs:.2f} s ({_pct(secs / r.wall) if r.wall else _DASH})"
                 for secs, st in top]  # fmt: skip
        out.append("- Top critical-path stages: " + "; ".join(parts) + ".")
    else:
        out.append("- Top critical-path stages: none recorded.")
    ratio, ratio_reason = _reprocessing_ratio(r)
    out.append(f"- Reprocessing ratio: {_rtf(ratio)}" + (f" ({ratio_reason})." if ratio is None
                                                          else "."))  # fmt: skip
    cold = [s for s in r.stage_spans("model_init") + r.stage_spans("diarization_load")
            if _attrs(s).get("state") == "cold"]  # fmt: skip
    if cold:
        out.append(
            "- Cold loads: "
            + "; ".join(f"{_text(s.name)} {_s(_attrs(s).get('load_seconds'))}" for s in cold)
            + "."
        )
    else:
        out.append("- Cold loads: none.")
    queue = [s for s in r.stage_spans("queue") if r.on_path(s)]
    waits = [float(_attrs(s)["queue_wait_seconds"]) for s in queue
             if _attrs(s).get("queue_wait_seconds") is not None]  # fmt: skip
    out.append(f"- Queue wait: {_s(sum(waits)) if waits else _DASH}"
               + ("." if waits else " (not_measured)."))  # fmt: skip
    llm = r.stage_spans("llm_call")
    out.append(f"- LLM latency share of wall: {_pct(r.share(llm)) if llm else 'no LLM call'}.")
    if run.time_to_notes_seconds is not None and run.processing_wall_seconds is not None:
        out.append(
            f"- UI delay (time_to_notes − processing_wall): "
            f"{run.time_to_notes_seconds - run.processing_wall_seconds:.2f} s."
        )
    else:
        field = ("time_to_notes_seconds" if run.time_to_notes_seconds is None
                 else "processing_wall_seconds")  # fmt: skip
        out.append(
            f"- UI delay (time_to_notes − processing_wall): {_DASH} "
            f"({field} {run.null_reasons.get(field, 'not_measured')})."
        )
    out += ["", "### Hypotheses", ""]
    lines, quiet = hypotheses(r)
    found = [line for line in lines if line.startswith("Hypothesis:")]
    out += [f"- {line}" for line in lines]
    if not found:
        out += ["", "No rule fired."]
    if quiet:
        out += ["", "Checked, did not fire: " + ", ".join(f"`{q}`" for q in quiet) + "."]
    return out


def render_report(record: RunExport) -> str:
    """The Markdown diagnostics report for one run. Deterministic for a given record."""
    r = _prepare(record)
    run = r.run
    sections = [
        [f"# Diagnostics — recording {run.recording_id}", "",
         f"Run `{run.processing_run_id}` · {run.kind} · {run.status}"],
        _identity(r), _timing(r), _stages(r), _asr(r), _diarization(r), _llm(r), _memory(r),
        _bottleneck(r),
    ]  # fmt: skip
    return "\n\n".join("\n".join(lines) for lines in sections) + "\n"


def stage_shares(record: RunExport) -> dict[str, float]:
    """Each critical-path stage's share of wall time (union of its spans), as the report's
    stage table and bottleneck summary count it. Empty when wall time is unknown."""
    r = _prepare(record)
    if not r.wall:
        return {}
    stages = sorted({s.stage for s in r.spans if r.on_path(s)})
    return {st: r.union_seconds([s for s in r.stage_spans(st) if r.on_path(s)]) / r.wall
            for st in stages}  # fmt: skip
