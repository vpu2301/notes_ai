#!/usr/bin/env bash
# Start / verify / stop the model servers on the founder's Mac (DEP-S0).
#
#   make dev-model                 # start what is missing, then verify
#   make dev-model ARGS=verify     # probes only (20k-token context, ASR words[])
#   make dev-model ARGS=status
#   make dev-model ARGS=stop       # stops the whisper-server we started
#
# Env (all optional):
#   DEV_MAC_MODEL_URL   http://localhost:11434/v1   Ollama / LM Studio / MLX-serve, OpenAI-compatible
#   DEV_MAC_CHAT_MODEL  notes-chat                  model name the /v1 route serves (see Modelfile)
#   DEV_MAC_BASE_MODEL  gemma3:4b                   base for `ollama create notes-chat`
#   DEV_MAC_ASR_URL     http://localhost:8080       whisper.cpp server (OpenAI path)
#   DEV_MAC_ASR_MODEL   whisper-large-v3-turbo      label only (whisper-server serves one model)
#   WHISPER_MODEL_FILE  ~/.cache/whisper-cpp/ggml-large-v3-turbo.bin
#
# Inside Docker the workers reach these via host.docker.internal (defaults in
# config/models.yaml); this script talks to localhost.
set -euo pipefail
cmd="${1:-start}"
repo="$(cd "$(dirname "$0")/../.." && pwd)"
state="${XDG_CACHE_HOME:-$HOME/.cache}/notes-ai"; mkdir -p "$state"

MODEL_URL="${DEV_MAC_MODEL_URL:-http://localhost:11434/v1}"
CHAT_MODEL="${DEV_MAC_CHAT_MODEL:-notes-chat}"
BASE_MODEL="${DEV_MAC_BASE_MODEL:-gemma3:4b}"
ASR_URL="${DEV_MAC_ASR_URL:-http://localhost:8080}"
WHISPER_FILE="${WHISPER_MODEL_FILE:-$HOME/.cache/whisper-cpp/ggml-large-v3-turbo.bin}"
WHISPER_URL_DOWNLOAD="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/$(basename "$WHISPER_FILE")"
# docs/models/PINS.md row "libs/models dev_mac_asr" — a mismatch refuses to start the server.
WHISPER_SHA256="${WHISPER_MODEL_SHA256:-1fc70f774d38eb169993ac391eea357ef47c88757ef72ee5943879b7e8e2bc69}"
asr_port="${ASR_URL##*:}"; asr_port="${asr_port%%/*}"
pidfile="$state/whisper-server.pid"; logfile="$state/whisper-server.log"

say_() { printf '%s\n' "$*"; }
ok()   { printf '  ✓ %s\n' "$*"; }
bad()  { printf '  ✗ %s\n' "$*" >&2; }

chat_up() { curl -sf -m 3 "${MODEL_URL%/v1}/api/tags" >/dev/null 2>&1 || curl -sf -m 3 "$MODEL_URL/models" >/dev/null 2>&1; }
asr_up()  { curl -s -m 3 -o /dev/null -w '%{http_code}' "$ASR_URL/" 2>/dev/null | grep -qE '^(200|404|405)$'; }
asr_is_whisper() { curl -s -m 3 "$ASR_URL/" 2>/dev/null | grep -qi 'whisper'; }
port_owner() { lsof -nP -iTCP:"$1" -sTCP:LISTEN 2>/dev/null | awk 'NR==2{print $1" (pid "$2")"}'; }

mem_class() {
  local bytes gb; bytes=$(sysctl -n hw.memsize 2>/dev/null || echo 0); gb=$((bytes / 1073741824))
  if   [ "$gb" -ge 64 ]; then echo "$gb GB unified memory → up to a 30B-class 4-bit chat model"
  elif [ "$gb" -ge 32 ]; then echo "$gb GB unified memory → up to a 14B-class 4-bit chat model"
  else                        echo "$gb GB unified memory → 8B-class 4-bit chat model or smaller (leave room for the 12 GiB dev stack)"; fi
}

start_chat() {
  if chat_up; then ok "chat server answering at $MODEL_URL"; else
    if command -v ollama >/dev/null; then
      say_ "  starting ollama serve (OLLAMA_HOST=0.0.0.0 so Docker can reach it)…"
      OLLAMA_HOST=0.0.0.0 nohup ollama serve >"$state/ollama.log" 2>&1 &
      for _ in $(seq 1 30); do chat_up && break; sleep 1; done
      chat_up && ok "ollama up" || { bad "ollama did not come up — see $state/ollama.log"; return 1; }
    else
      bad "no server at $MODEL_URL and ollama not installed (brew install ollama, or run LM Studio / MLX-serve and set DEV_MAC_MODEL_URL)"; return 1
    fi
  fi
  if command -v ollama >/dev/null && [[ "$MODEL_URL" == *11434* ]]; then
    if ollama show "$CHAT_MODEL" >/dev/null 2>&1; then ok "model '$CHAT_MODEL' present"; else
      say_ "  creating '$CHAT_MODEL' from $BASE_MODEL with num_ctx 32768 (Modelfile)…"
      ollama show "$BASE_MODEL" >/dev/null 2>&1 || ollama pull "$BASE_MODEL"
      sed "s#^FROM .*#FROM $BASE_MODEL#" "$repo/infra/models/dev-mac/Modelfile" > "$state/Modelfile"
      ollama create "$CHAT_MODEL" -f "$state/Modelfile" && ok "created '$CHAT_MODEL'"
    fi
  fi
}

start_asr() {
  if asr_up; then
    if asr_is_whisper; then ok "whisper-server answering at $ASR_URL"; else
      bad "port $asr_port is taken by $(port_owner "$asr_port") — not whisper-server. Set DEV_MAC_ASR_URL=http://localhost:8090 (and the same in .env.local for Docker: http://host.docker.internal:8090)"; return 1
    fi
    return 0
  fi
  command -v whisper-server >/dev/null || { bad "whisper-server not installed: brew install whisper-cpp"; return 1; }
  if [ ! -f "$WHISPER_FILE" ]; then
    say_ "  downloading $(basename "$WHISPER_FILE") (~1.6 GB) to $(dirname "$WHISPER_FILE")…"
    mkdir -p "$(dirname "$WHISPER_FILE")"; curl -sSL -o "$WHISPER_FILE" "$WHISPER_URL_DOWNLOAD"
  fi
  if [[ "$(basename "$WHISPER_FILE")" == "ggml-large-v3-turbo.bin" ]]; then
    actual="$(shasum -a 256 "$WHISPER_FILE" | cut -d' ' -f1)"
    [ "$actual" = "$WHISPER_SHA256" ] || { bad "whisper model digest mismatch ($actual ≠ pinned $WHISPER_SHA256, docs/models/PINS.md) — refusing to serve unaccounted weights"; return 1; }
    ok "whisper weights match the PINS.md digest"
  fi
  say_ "  starting whisper-server on :$asr_port (Metal, OpenAI path)…"
  nohup whisper-server -m "$WHISPER_FILE" --host 127.0.0.1 --port "$asr_port" \
        --inference-path /v1/audio/transcriptions --split-on-word >"$logfile" 2>&1 &
  echo $! > "$pidfile"
  for _ in $(seq 1 60); do asr_up && break; sleep 1; done
  asr_up && ok "whisper-server up (pid $(cat "$pidfile"), log $logfile)" || { bad "whisper-server did not come up — see $logfile"; return 1; }
}

verify() {
  say_ "verify:"
  DEV_MAC_MODEL_URL="$MODEL_URL" DEV_MAC_CHAT_MODEL="$CHAT_MODEL" DEV_MAC_ASR_URL="$ASR_URL" ENV=dev \
    uv run --project "$repo/libs/models" python "$repo/scripts/dev/dev_model_verify.py"
}

status() {
  say_ "dev-model status  ($(mem_class))"
  chat_up && ok "chat: $MODEL_URL (model '$CHAT_MODEL')" || bad "chat: nothing at $MODEL_URL"
  if asr_up; then asr_is_whisper && ok "asr: whisper-server at $ASR_URL" || bad "asr: port $asr_port taken by $(port_owner "$asr_port")"; else bad "asr: nothing at $ASR_URL"; fi
}

case "$cmd" in
  start) say_ "dev-model start  ($(mem_class))"; start_chat; start_asr; verify ;;
  verify) verify ;;
  status) status ;;
  stop)
    if [ -f "$pidfile" ] && kill "$(cat "$pidfile")" 2>/dev/null; then ok "stopped whisper-server"; rm -f "$pidfile"; else say_ "no whisper-server started by this script (ollama is left running)"; fi ;;
  *) echo "usage: $0 [start|verify|status|stop]" >&2; exit 2 ;;
esac
