"""Build the synthetic test set (asr-perf-sprints Sprint A) with macOS ``say``.

    uv run python tools/asr_bench/make_tts_set.py [--only en-2m ...]

Each ``tts_set/<id>.json`` is a scripted conversation: speakers mapped to voices (or to a
voice per language), turns of ``[speaker, language, text]``. Writes to ``~/asr-perf-audio/``:
``<id>.flac`` (16 kHz mono), ``refs/<id>.truth.json`` (the scripted text per turn with its
speaker, language and time span) and, when a turn is not in the recording's language,
``<id>.switches.json`` with each foreign passage's span. Pauses between turns are seeded,
so a rebuild gives the same file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bench  # noqa: E402

SET = Path(__file__).resolve().parent / "tts_set"
RATE = 16000
LEAD_S = 0.5
SAME_SPEAKER_PAUSE_S = 0.25
# A little slower than the voices' default (~180 wpm): closer to people talking in a meeting.
WPM = "165"


def _voice(spec: dict, speaker: str, lang: str) -> str:
    v = spec["voices"][speaker]
    return v[lang] if isinstance(v, dict) else v


def _speak(text: str, voice: str, pitch: float | None, out: Path, tmp: Path) -> bytes:
    aiff = tmp / "turn.aiff"
    subprocess.run(["say", "-v", voice, "-r", WPM, "-o", str(aiff), text], check=True)
    # A pitch factor < 1 lowers the voice at the same tempo: a second speaker from one voice.
    filters = [f"asetrate=22050*{pitch},aresample=22050,atempo={1 / pitch}"] if pitch else []
    cmd = ["ffmpeg", "-loglevel", "error", "-y", "-i", str(aiff)]
    if filters:
        cmd += ["-af", ",".join(filters)]
    subprocess.run([*cmd, "-ac", "1", "-ar", str(RATE), "-sample_fmt", "s16", str(out)], check=True)
    with wave.open(str(out)) as w:
        return w.readframes(w.getnframes())


def build(rec: str, spec: dict, dest: Path) -> dict:
    rng = random.Random(rec)
    pcm = bytearray(b"\0\0" * int(LEAD_S * RATE))
    segments, switches = [], []
    prev = None
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        for speaker, lang, text in spec["turns"]:
            if prev is not None:
                pause = SAME_SPEAKER_PAUSE_S if speaker == prev else rng.uniform(0.5, 1.6)
                pcm += b"\0\0" * int(pause * RATE)
            start = len(pcm) // 2
            voice = _voice(spec, speaker, lang)
            pcm += _speak(text, voice, spec.get("pitch", {}).get(speaker), tmp / "turn.wav", tmp)
            end = len(pcm) // 2
            seg = {
                "text": text,
                "speaker": speaker,
                "language": lang,
                "start_ms": start * 1000 // RATE,
                "end_ms": end * 1000 // RATE,
                "words": [],
            }
            segments.append(seg)
            if lang != spec["language"]:
                switches.append({"start_s": start / RATE, "end_s": end / RATE, "lang": lang})
            prev = speaker
        pcm += b"\0\0" * int(LEAD_S * RATE)
        wav = tmp / "all.wav"
        with wave.open(str(wav), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(bytes(pcm))
        flac = dest / f"{rec}.flac"
        subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-y", "-i", str(wav), "-c:a", "flac", str(flac)],
            check=True,
        )
    (dest / "refs").mkdir(exist_ok=True)
    truth = {"language": spec["language"], "segments": segments}
    (dest / "refs" / f"{rec}.truth.json").write_text(json.dumps(truth, ensure_ascii=False))
    if switches:
        (dest / f"{rec}.switches.json").write_text(json.dumps(switches, indent=1))
    return {
        "id": rec,
        "duration_s": round(len(pcm) / 2 / RATE, 2),
        "sha256": hashlib.sha256(flac.read_bytes()).hexdigest(),
        "turns": len(segments),
        "speakers": len({s["speaker"] for s in segments}),
        "words": sum(len(s["text"].split()) for s in segments),
        "switches": [round(s["end_s"] - s["start_s"], 2) for s in switches],
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--only", nargs="+")
    a = p.parse_args()
    dest = bench.AUDIO_DIR
    dest.mkdir(parents=True, exist_ok=True)
    for path in sorted(SET.glob("*.json")):
        if a.only and path.stem not in a.only:
            continue
        print(json.dumps(build(path.stem, json.loads(path.read_text()), dest)), flush=True)


if __name__ == "__main__":
    main()
