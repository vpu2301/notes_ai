#!/usr/bin/env python3
"""DEP-S0 smoke eval: five synthetic meetings through one chat backend.

    make eval-smoke BACKEND=dev_mac        # founder's Mac (ENV=dev)
    ENV=staging make eval-smoke BACKEND=hf_eu

Per meeting the backend must return a schema-valid JSON object with a
summary, ≥ N action items and ≥ 1 decision, where every `evidence` quote is
a verbatim substring of the transcript (the S2 provenance invariant, checked
early). A quote that is not in the transcript is a hallucination; the run
fails if any meeting has one. Latency and token counts are recorded to
docs/eval/smoke-<date>-<backend>.json. No prompt or transcript text is logged.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

from _common import REPO, load_registry, write_report

MEETINGS = REPO / "tests" / "fixtures" / "eval" / "meetings"

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "language": {
            "type": "string",
            "description": "ISO 639-1 code of the meeting language, e.g. en, de, uk",
        },
        "action_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "owner": {"type": "string"},
                    "due": {"type": "string"},
                    "evidence": {"type": "string"},
                },
                "required": ["text", "owner", "evidence"],
            },
        },
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"text": {"type": "string"}, "evidence": {"type": "string"}},
                "required": ["text", "evidence"],
            },
        },
    },
    "required": ["summary", "language", "action_items", "decisions"],
}

SYSTEM = (
    "You extract structured meeting notes. Write the summary, action items and decisions "
    "in the language the meeting was held in. Every `evidence` field must be an exact, "
    "verbatim quote (5-20 words) copied from the transcript — never paraphrase evidence. "
    "Do not invent people, dates or facts that are not in the transcript."
)


def _prompt(meeting: dict[str, Any]) -> str:
    lines = [
        f"[{t['speaker']} {t['t_start_ms'] // 1000}s] {t['text']}" for t in meeting["transcript"]
    ]
    return "Transcript:\n" + "\n".join(lines) + "\n\nReturn the JSON object now."


_TURN_PREFIX = re.compile(r"^\s*\[?SPEAKER_\d+\s+\d+s\]?\s*:?\s*")
_LANGUAGE_NAMES = {
    "english": "en",
    "german": "de",
    "deutsch": "de",
    "ukrainian": "uk",
    "українська": "uk",
}


def _norm(text: str) -> str:
    return " ".join(text.replace("’", "'").split()).lower()


def _quote(text: str) -> str:
    """Models copy the `[SPEAKER_1 22s]` turn prefix and wrap quotes in “ ”; neither is a hallucination."""
    return _norm(_TURN_PREFIX.sub("", text).strip().strip("\"'“”„«»‘’ "))


def _lang(value: Any) -> str:
    v = str(value or "").strip().lower()
    return _LANGUAGE_NAMES.get(v, v[:2])


def _check(meeting: dict[str, Any], obj: dict[str, Any]) -> tuple[list[str], int]:
    transcript = _norm(" ".join(t["text"] for t in meeting["transcript"]))
    problems: list[str] = []
    quotes = [i.get("evidence", "") for i in obj.get("action_items", [])] + [
        d.get("evidence", "") for d in obj.get("decisions", [])
    ]
    hallucinated = 0
    for q in quotes:
        if not q or _quote(q) not in transcript:
            hallucinated += 1
    if hallucinated:
        problems.append(
            f"{hallucinated}/{len(quotes)} evidence quotes not found verbatim in transcript"
        )
    expect = meeting.get("expect", {})
    if len(obj.get("action_items", [])) < expect.get("min_action_items", 1):
        problems.append(
            f"only {len(obj.get('action_items', []))} action items (expected ≥ {expect.get('min_action_items', 1)})"
        )
    if not obj.get("decisions"):
        problems.append("no decisions extracted")
    blob = _norm(json.dumps(obj, ensure_ascii=False))
    missing = [m for m in expect.get("must_mention", []) if _norm(m) not in blob]
    if missing:
        problems.append(f"output never mentions {missing}")
    if _lang(obj.get("language")) != meeting["language"]:
        problems.append(f"language {obj.get('language')!r} != {meeting['language']!r}")
    return problems, hallucinated


async def run(backend_name: str, max_tokens: int, extra_body: dict[str, Any] | None = None) -> int:
    from models import ProviderError, build_chat_provider

    registry = load_registry()
    resolved = registry.backend(backend_name, expect_kind="chat")
    provider = build_chat_provider(resolved)
    if extra_body:
        # Experiment-only override of the backend's request_overrides
        # (config/models.yaml is the source of truth for a real run).
        provider.request_overrides = {**getattr(provider, "request_overrides", {}), **extra_body}  # type: ignore[attr-defined]
    print(
        f"backend={resolved.name} model={resolved.model_id} processor={resolved.processor.name if resolved.processor else '-'} mode={resolved.caps.structured_output}"
    )
    t0 = time.monotonic()
    await provider.probe()
    print(
        f"probe ok in {time.monotonic() - t0:.1f}s (structured mode: {getattr(provider, 'structured_mode', '-')})"
    )

    results: list[dict[str, Any]] = []
    failed = 0
    total_quotes = 0
    total_halluc = 0
    for path in sorted(MEETINGS.glob("*.json")):
        meeting = json.loads(path.read_text(encoding="utf-8"))
        row: dict[str, Any] = {"meeting": meeting["id"], "language": meeting["language"]}
        try:
            result = await provider.complete(
                _prompt(meeting), SCHEMA, max_tokens=max_tokens, system=SYSTEM
            )
        except ProviderError as exc:
            row.update({"ok": False, "error_kind": str(exc.kind), "error": exc.message[:160]})
            failed += 1
            results.append(row)
            print(f"  {meeting['id']:<26} FAIL {exc.kind}: {exc.message[:100]}")
            continue
        obj = result.json if isinstance(result.json, dict) else {}
        problems, halluc = _check(meeting, obj)
        n_quotes = len(obj.get("action_items", [])) + len(obj.get("decisions", []))
        total_quotes += n_quotes
        total_halluc += halluc
        row.update(
            {
                "ok": not problems,
                "problems": problems,
                "latency_ms": result.latency_ms,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "action_items": len(obj.get("action_items", [])),
                "decisions": len(obj.get("decisions", [])),
                "evidence_quotes": n_quotes,
                "hallucinated_quotes": halluc,
                "model_id": result.model_id,
                "structured_mode": result.structured_mode,
            }
        )
        if problems:
            failed += 1
        results.append(row)
        status = "ok  " if not problems else "FAIL"
        print(
            f"  {meeting['id']:<26} {status} {result.latency_ms / 1000:6.1f}s  in={result.input_tokens} out={result.output_tokens}  items={row['action_items']} decisions={row['decisions']}"
            + (f"  {'; '.join(problems)}" if problems else "")
        )
    await provider.aclose()

    ok_rows = [r for r in results if r.get("latency_ms") is not None]
    summary = {
        "meetings": len(results),
        "failed": failed,
        "hallucination_rate": (total_halluc / total_quotes) if total_quotes else None,
        "latency_ms_p50": sorted(r["latency_ms"] for r in ok_rows)[len(ok_rows) // 2]
        if ok_rows
        else None,
        "latency_ms_max": max((r["latency_ms"] for r in ok_rows), default=None),
        "model_id": resolved.model_id,
        "structured_mode": getattr(provider, "structured_mode", None),
        "processor": resolved.processor.model_dump() if resolved.processor else None,
    }
    report = write_report(
        "smoke", backend_name, {"summary": summary, "results": results, "max_tokens": max_tokens}
    )
    print(
        f"\n{len(results) - failed}/{len(results)} meetings passed; hallucination rate {summary['hallucination_rate']}; report → {report.relative_to(REPO)}"
    )
    return 1 if failed else 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--backend", required=True, help="backend name from config/models.yaml (dev_mac, hf_eu, …)"
    )
    ap.add_argument("--max-tokens", type=int, default=1500)
    ap.add_argument(
        "--extra-body",
        default=None,
        help='JSON merged into every request, e.g. \'{"reasoning_effort": "none"}\'',
    )
    args = ap.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    extra = json.loads(args.extra_body) if args.extra_body else None
    return asyncio.run(run(args.backend, args.max_tokens, extra))


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main())
