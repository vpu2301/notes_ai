#!/usr/bin/env bash
# Build a synthetic speech fixture with macOS TTS (no real audio needed).
#   scripts/eval/make_tts_fixture.sh 10min_de     # ~10 min German
#   scripts/eval/make_tts_fixture.sh 60min_de
#   scripts/eval/make_tts_fixture.sh 10min_en
# Output: tests/fixtures/eval/audio/<name>.wav (16 kHz mono 16-bit, gitignored).
# Synthetic TTS is NOT a WER gold set — it exists so turnaround numbers are
# reproducible on any Mac before the BE-S2 corpus lands.
set -euo pipefail
name="${1:?fixture name, e.g. 10min_de}"
minutes="${name%%min_*}"; lang="${name##*_}"
repo="$(cd "$(dirname "$0")/../.." && pwd)"
out_dir="$repo/tests/fixtures/eval/audio"; mkdir -p "$out_dir"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT

case "$lang" in
  de) voice="Anna"; text="Guten Morgen zusammen, wir beginnen mit dem Projektstatus. Die Schnittstelle zum Lagersystem ist fast fertig, der Liefertermin bleibt der zweiundzwanzigste. Bitte schickt eure Rückmeldungen bis Freitag an das Team. Als Nächstes besprechen wir das Budget für das vierte Quartal und die offenen Stellen im Vertrieb." ;;
  en) voice="Samantha"; text="Good morning everyone, let's start with the project status. The warehouse integration is almost done and the delivery date stays the twenty-second. Please send your feedback to the team by Friday. Next we discuss the budget for the fourth quarter and the open positions in sales." ;;
  uk) voice="Lesya"; text="Доброго ранку всім, починаємо зі статусу проєкту. Інтеграція зі складом майже готова, дата поставки залишається двадцять друге. Надішліть, будь ласка, свої відгуки команді до п'ятниці. Далі обговорюємо бюджет на четвертий квартал і відкриті вакансії у продажах." ;;
  *) echo "unknown language suffix: $lang" >&2; exit 2 ;;
esac

# One paragraph ≈ 20 s at the default rate; repeat with a pause to reach the target length.
say -v "$voice" -r 175 -o "$tmp/para.aiff" "$text" 2>/dev/null || { echo "voice '$voice' not installed: System Settings → Accessibility → Spoken Content → System voice → Manage voices" >&2; exit 3; }
afconvert -f WAVE -d LEI16@16000 -c 1 "$tmp/para.aiff" "$tmp/para.wav"
para_s=$(python3 -c "import wave;w=wave.open('$tmp/para.wav');print(w.getnframes()/w.getframerate())")
reps=$(python3 -c "import math;print(max(1, math.ceil($minutes*60/($para_s+1.0))))")
python3 - "$tmp/para.wav" "$out_dir/$name.wav" "$reps" <<'PY'
import sys, wave, struct
src, dst, reps = sys.argv[1], sys.argv[2], int(sys.argv[3])
with wave.open(src) as w:
    params, frames = w.getparams(), w.readframes(w.getnframes())
pause = b"\x00\x00" * 16000  # 1 s silence
with wave.open(dst, "wb") as out:
    out.setparams(params)
    for _ in range(reps):
        out.writeframes(frames + pause)
PY
dur=$(python3 -c "import wave;w=wave.open('$out_dir/$name.wav');print(round(w.getnframes()/w.getframerate()/60,1))")
echo "wrote $out_dir/$name.wav (${dur} min, voice $voice, ${reps}× paragraph)"
