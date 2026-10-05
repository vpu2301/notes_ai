#!/usr/bin/env bash
# The local bake-off: every candidate model on one corpus through the
# production pipeline; `scripts/eval/local_bakeoff_report.py` folds the
# day's manifest entries into one report.
#
#   make local-bakeoff [CORPUS=...] [CANDIDATES="gemma3:4b qwen3:8b"]
#
# --before <tag> also runs that tag with the small-model profile OFF.
# Env: DEV_MAC_DOCKER_GIB (Docker limit the budget subtracts), BAKEOFF_DATE.
set -uo pipefail
repo="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$repo"

CORPUS="tests/fixtures/eval/notes"
CANDIDATES=""
BEFORE="gemma3:4b"
ARM="pipeline"
while [ $# -gt 0 ]; do
  case "$1" in
    --corpus) CORPUS="$2"; shift 2 ;;
    --candidates) CANDIDATES="$2"; shift 2 ;;
    --before) BEFORE="$2"; shift 2 ;;
    --no-before) BEFORE=""; shift ;;
    --arm) ARM="$2"; shift 2 ;;
    *) echo "usage: $0 [--corpus DIR] [--candidates \"tag …\"] [--before TAG|--no-before] [--arm pipeline|single_pass]" >&2; exit 2 ;;
  esac
done

# The harness runs on the host; the Docker-side default URL does not resolve here.
export DEV_MAC_MODEL_URL="${DEV_MAC_MODEL_URL:-http://localhost:11434/v1}"
export PYTHONUNBUFFERED=1  # per-meeting lines as they happen, through tee
DATE="${BAKEOFF_DATE:-$(date -u +%Y-%m-%d)}"
OUT="scripts/eval/local/bakeoff-$DATE"; mkdir -p "$OUT"
corpus_name="$(basename "$CORPUS")"
say_() { printf '%s\n' "$*"; }

# Default candidates for 16-24 GB; newer families only when the registry serves the tag.
if [ -z "$CANDIDATES" ]; then
  CANDIDATES="gemma3:4b qwen3:8b gemma3:12b-it-qat qwen3:14b llama3.1:8b"
  for t in gemma4:e4b gemma4:12b qwen3.6:4b qwen3.6:8b qwen3.6:14b; do
    repo_="${t%%:*}"; tag_="${t##*:}"
    code=$(curl -s -o /dev/null -w '%{http_code}' -m 15 -H 'Accept: application/vnd.docker.distribution.manifest.v2+json' \
      "https://registry.ollama.ai/v2/library/$repo_/manifests/$tag_" 2>/dev/null || echo 000)
    [ "$code" = "200" ] && CANDIDATES="$CANDIDATES $t"
  done
fi
say_ "local bake-off $DATE — corpus $CORPUS, arm $ARM"
say_ "candidates: $CANDIDATES$( [ -n "$BEFORE" ] && printf ' (+ %s with the profile off)' "$BEFORE")"

slug_of() { printf '%s' "$1" | tr ':/.' '---'; }

write_entry() {  # slug tag model profile status report assert_log sampler_log eval_log
  python3 - "$OUT/$1-$corpus_name.json" "$@" <<'PY'
import json, re, sys, pathlib
out, slug, tag, model, profile, status, report, assert_log, sampler_log, eval_log = sys.argv[1:11]
entry = {"slug": slug, "tag": tag, "model": model, "profile": profile == "on", "status": status,
         "corpus": sys.argv[11], "report": report or None, "arm": sys.argv[12]}
passes = total = 0
if assert_log and pathlib.Path(assert_log).is_file():
    for m in re.finditer(r": (\d+)/(\d+) checks pass", pathlib.Path(assert_log).read_text("utf-8", "replace")):
        passes += int(m.group(1)); total += int(m.group(2))
entry["checks"] = [passes, total] if total else None
peak = 0.0; processor = None
if sampler_log and pathlib.Path(sampler_log).is_file():
    for line in pathlib.Path(sampler_log).read_text("utf-8", "replace").splitlines():
        m = re.match(r"([\d.]+) (GB|MB)\|(.*)", line.strip())
        if not m: continue
        size = float(m.group(1)) * (1 if m.group(2) == "GB" else 0.001)
        if size >= peak: peak, processor = size, m.group(3).strip()
entry["peak_gb"] = round(peak, 1) if peak else None
entry["processor"] = processor
if eval_log and pathlib.Path(eval_log).is_file():
    text = pathlib.Path(eval_log).read_text("utf-8", "replace")
    m = re.search(r"^wrote (.+)$", text, re.M)
    if m and not entry["report"]: entry["report"] = m.group(1).strip()
    entry["eval_exit_note"] = "FAIL" if re.search(r"^\s+\S+\s+FAIL ", text, re.M) else None
pathlib.Path(out).write_text(json.dumps(entry, indent=2) + "\n", "utf-8")
print(f"  manifest: {out}")
PY
}

run_candidate() {  # tag profile(on|off)
  local tag="$1" profile="$2" slug model label eval_log assert_log sampler_log report sampler_pid
  slug="$(slug_of "$tag")"; [ "$profile" = "off" ] && slug="$slug-noprofile"
  model="notes-chat-$(slug_of "$tag")"
  label="$slug"
  eval_log="$OUT/$slug-$corpus_name.eval.log"; assert_log="$OUT/$slug-$corpus_name.assert.log"; sampler_log="$OUT/$slug-$corpus_name.ps.log"
  say_ ""; say_ "── $tag (profile $profile) → $model"
  # Fit check before pulling, again after with the real size.
  if ! DEV_MAC_BASE_MODEL="$tag" bash scripts/dev/dev-model.sh fit; then
    write_entry "$slug" "$tag" "$model" "$profile" "skipped: over budget" "" "" "" "" "$corpus_name" "$ARM"; return
  fi
  if ! ollama show "$tag" >/dev/null 2>&1; then
    say_ "  pulling $tag…"
    if ! ollama pull "$tag" >"$OUT/$slug.pull.log" 2>&1; then
      write_entry "$slug" "$tag" "$model" "$profile" "skipped: tag not available" "" "" "" "" "$corpus_name" "$ARM"; return
    fi
  fi
  if ! DEV_MAC_BASE_MODEL="$tag" DEV_MAC_CHAT_MODEL="$model" bash scripts/dev/dev-model.sh chat; then
    write_entry "$slug" "$tag" "$model" "$profile" "skipped: over budget after pull" "" "" "" "" "$corpus_name" "$ARM"; return
  fi
  local small="true"; [ "$profile" = "off" ] && small="false"
  # `ollama ps` lists a resident model under the first name sharing its digest: match the ID.
  local model_id; model_id="$(ollama list 2>/dev/null | awk -v m="$model:latest" '$1==m {print $2; exit}')"
  ( while :; do ollama ps 2>/dev/null | awk -v id="$model_id" 'NR>1 && (id=="" || $2==id) {print $3" "$4"|"$5" "$6" "$7}'; sleep 10; done ) >"$sampler_log" 2>/dev/null &
  sampler_pid=$!
  DEV_MAC_CHAT_MODEL="$model" DEV_MAC_SMALL_MODEL="$small" make eval-notes BACKEND=dev_mac ARM="$ARM" CORPUS="$CORPUS" LABEL="$label" 2>&1 | tee "$eval_log" | grep -E '^\s+\S+\s+[0-9.]+s|^  run |wrote |FAIL|gate' || true
  report="$(grep -E '^wrote ' "$eval_log" | tail -1 | sed 's/^wrote //')"
  if [ "$ARM" = "pipeline" ]; then
    DEV_MAC_CHAT_MODEL="$model" DEV_MAC_SMALL_MODEL="$small" make eval-notes-assert BACKEND=dev_mac CORPUS="$CORPUS" 2>&1 | tee "$assert_log" | grep -E 'checks pass|RUN FAILED' || true
  fi
  kill "$sampler_pid" 2>/dev/null; wait "$sampler_pid" 2>/dev/null
  local status="ran"; [ -z "$report" ] && status="failed: no report"
  write_entry "$slug" "$tag" "$model" "$profile" "$status" "$report" "$assert_log" "$sampler_log" "$eval_log" "$corpus_name" "$ARM"
}

[ -n "$BEFORE" ] && run_candidate "$BEFORE" off
for tag in $CANDIDATES; do run_candidate "$tag" on; done

say_ ""; say_ "report:"
uv run --project services/note-service python scripts/eval/local_bakeoff_report.py --date "$DATE"
