#!/usr/bin/env python3
"""Build a synthetic code-switched ASR case from its tracked ``script.json`` (Sprint B3 T5).

    uv run --project services/asr-worker python scripts/eval/make_codeswitch_fixture.py cs01 cs02 cs03

Each utterance is spoken by macOS TTS in its own language (Anna de, Samantha en, Lesya uk),
the pieces are joined with a short pause, and the exact timings become ``reference.json``
and ``spans.json`` (code-switch regions) in the TQ1 gold format next to ``audio.wav``.
Synthetic speech is not a WER gold set for real recordings; it makes the code-switch
behaviour reproducible. Audio and the generated files stay out of git.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CORPUS = REPO / "tests" / "fixtures" / "eval" / "asr" / "synthetic"
VOICES = {"de": "Anna", "en": "Samantha", "uk": "Lesya"}
RATE = 175
PAUSE_MS = 800
SAMPLE_RATE = 16_000


def _speak(text: str, language: str, out_wav: Path) -> None:
    aiff = out_wav.with_suffix(".aiff")
    subprocess.run(
        ["say", "-v", VOICES[language], "-r", str(RATE), "-o", str(aiff), text], check=True
    )
    subprocess.run(
        ["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", str(aiff), str(out_wav)],
        check=True,
    )


def build(rec_id: str) -> None:
    folder = CORPUS / rec_id
    script = json.loads((folder / "script.json").read_text("utf-8"))
    recording = script["language"]
    reference: list[dict[str, object]] = []
    regions: list[dict[str, object]] = []
    frames = bytearray()
    pause = b"\x00\x00" * (SAMPLE_RATE * PAUSE_MS // 1000)
    with tempfile.TemporaryDirectory() as tmp:
        for k, utt in enumerate(script["utterances"]):
            piece = Path(tmp) / f"{k}.wav"
            _speak(utt["text"], utt["language"], piece)
            with wave.open(str(piece)) as w:
                assert w.getframerate() == SAMPLE_RATE and w.getnchannels() == 1
                data = w.readframes(w.getnframes())
            # A clip spliced into narration follows it almost at once (``pause_before_ms``),
            # so VAD hears one run and chunk LID cannot separate it — the r02 shape.
            if k and "pause_before_ms" in utt:
                frames = frames[: len(frames) - len(pause)]
                frames += b"\x00\x00" * (SAMPLE_RATE * int(utt["pause_before_ms"]) // 1000)
            start_ms = len(frames) * 1000 // (2 * SAMPLE_RATE)
            frames += data
            end_ms = len(frames) * 1000 // (2 * SAMPLE_RATE)
            frames += pause
            reference.append(
                {
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                    "speaker": utt["speaker"],
                    "text": utt["text"],
                    "language": utt["language"],
                }
            )
            if utt["language"] != recording:
                regions.append(
                    {"start_ms": start_ms, "end_ms": end_ms, "language": utt["language"]}
                )
    with wave.open(str(folder / "audio.wav"), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(SAMPLE_RATE)
        out.writeframes(bytes(frames))
    (folder / "reference.json").write_text(
        json.dumps(reference, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    (folder / "spans.json").write_text(
        json.dumps({"code_switch": regions}, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    minutes = len(frames) / (2 * SAMPLE_RATE) / 60
    print(f"{rec_id}: {minutes:.1f} min, {len(reference)} utterances, {len(regions)} foreign runs")


def main(argv: list[str]) -> int:
    if shutil.which("say") is None or shutil.which("afconvert") is None:
        print("needs macOS `say` and `afconvert`", file=sys.stderr)
        return 2
    ids = argv or sorted(p.parent.name for p in CORPUS.glob("*/script.json"))
    for rec_id in ids:
        build(rec_id)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
