#!/usr/bin/env bash
# Start / verify / stop the model servers on the founder's Mac (DEP-S0, Sprint L1).
#
#   make dev-model                 # start what is missing, then verify
#   make dev-model ARGS=verify     # probes only (context probe, ASR words[], 100 % GPU)
#   make dev-model ARGS=status
#   make dev-model ARGS=fit        # memory budget for DEV_MAC_BASE_MODEL, no changes
#   make dev-model ARGS=chat       # chat model only: fit check, pull, create (the bake-off)
#   make dev-model ARGS=stop       # stops the whisper-server we started (ollama is left running)
#
# Env (all optional):
#   DEV_MAC_MODEL_URL   http://localhost:11434/v1   Ollama / LM Studio / MLX-serve, OpenAI-compatible
#   DEV_MAC_CHAT_MODEL  notes-chat                  model name the /v1 route serves (see Modelfile)
#   DEV_MAC_BASE_MODEL  gemma3:4b                   base for `ollama create notes-chat`
#   DEV_MAC_CONTEXT     16384                       num_ctx baked into the named model; 32768 uses
#                                                   Modelfile.longctx (also chosen by a *-long name)
#   DEV_MAC_DOCKER_GIB  (docker info)               memory the Docker VM may take; 12 when unknown
#   DEV_MAC_ASR_URL     http://localhost:8080       whisper.cpp server (OpenAI path)
#   DEV_MAC_ASR_MODEL   whisper-large-v3-turbo      label only (whisper-server serves one model)
#   WHISPER_MODEL_FILE  ~/.cache/whisper-cpp/ggml-large-v3-turbo.bin
#
# Memory budget (Sprint L1 T1): total unified memory − the Docker VM's limit
# − 3 GiB for macOS. A base model whose 4-bit weights plus KV cache at the
# chosen context exceed it is refused, not loaded onto swap. Weights are
# read from `ollama list` when the tag is local, else from a size table by
# parameter class. KV at q8_0: ≈ 1.5 GiB at 16K, ≈ 3 GiB at 32K.
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
ollama_pidfile="$state/ollama.pid"; ollama_log="$state/ollama.log"

# A *-long model name means the long-context Modelfile (the eval's single-pass arm).
case "$CHAT_MODEL" in *-long) CONTEXT="${DEV_MAC_CONTEXT:-32768}" ;; *) CONTEXT="${DEV_MAC_CONTEXT:-16384}" ;; esac
if [ "$CONTEXT" -ge 32768 ]; then MODELFILE="$repo/infra/models/dev-mac/Modelfile.longctx"; else MODELFILE="$repo/infra/models/dev-mac/Modelfile"; fi
OS_RESERVE_GIB=3

# The server tuning the budget assumes. Applied to an `ollama serve` this
# script starts; a server started elsewhere keeps its own settings.
export OLLAMA_FLASH_ATTENTION="${OLLAMA_FLASH_ATTENTION:-1}"
export OLLAMA_KV_CACHE_TYPE="${OLLAMA_KV_CACHE_TYPE:-q8_0}"
export OLLAMA_NUM_PARALLEL="${OLLAMA_NUM_PARALLEL:-1}"
export OLLAMA_KEEP_ALIVE="${OLLAMA_KEEP_ALIVE:-30m}"

say_() { printf '%s\n' "$*"; }
ok()   { printf '  ✓ %s\n' "$*"; }
bad()  { printf '  ✗ %s\n' "$*" >&2; }

chat_up() { curl -sf -m 3 "${MODEL_URL%/v1}/api/tags" >/dev/null 2>&1 || curl -sf -m 3 "$MODEL_URL/models" >/dev/null 2>&1; }
asr_up()  { curl -s -m 3 -o /dev/null -w '%{http_code}' "$ASR_URL/" 2>/dev/null | grep -qE '^(200|404|405)$'; }
asr_is_whisper() { curl -s -m 3 "$ASR_URL/" 2>/dev/null | grep -qi 'whisper'; }
port_owner() { lsof -nP -iTCP:"$1" -sTCP:LISTEN 2>/dev/null | awk 'NR==2{print $1" (pid "$2")"}'; }
is_ollama() { command -v ollama >/dev/null && [[ "$MODEL_URL" == *11434* ]]; }

# ── memory budget ──────────────────────────────────────────────────────
total_gib() { local b; b=$(sysctl -n hw.memsize 2>/dev/null || echo 0); echo $(( b / 1073741824 )); }

docker_gib() {
  # The VM's limit, not its current use: what it may grow to mid-run.
  if [ -n "${DEV_MAC_DOCKER_GIB:-}" ]; then echo "$DEV_MAC_DOCKER_GIB"; return; fi
  local b; b=$(docker info --format '{{.MemTotal}}' 2>/dev/null || true)
  if [ -n "$b" ] && [ "$b" -gt 0 ] 2>/dev/null; then awk -v b="$b" 'BEGIN{printf "%.1f", b/1073741824}'; else echo 12; fi
}

budget_gib() { awk -v t="$(total_gib)" -v d="$(docker_gib)" -v o="$OS_RESERVE_GIB" 'BEGIN{b=t-d-o; if(b<0)b=0; printf "%.1f", b}'; }

kv_gib() { awk -v c="$1" 'BEGIN{printf "%.1f", 1.5*c/16384}'; }

# Weights in GiB: the local blob when the tag is pulled (`ollama list` prints
# decimal GB), else the 4-bit table by parameter class.
weights_gib() {
  local tag="$1" size
  if is_ollama; then
    size=$(ollama list 2>/dev/null | awk -v t="$tag" '$1==t || $1==t":latest" {print $3" "$4; exit}')
    if [ -n "$size" ]; then awk -v s="$size" 'BEGIN{split(s,a," "); v=a[1]; if(a[2]=="MB")v=v/1000; printf "%.1f", v*0.931}'; return; fi
  fi
  local cls; cls=$(printf '%s' "$tag" | tr 'A-Z' 'a-z' | grep -oE '(e[0-9]+b|[0-9]+(\.[0-9]+)?b)' | head -1)
  case "$cls" in
    e2b) echo 3 ;; e4b) echo 7 ;;
    0.*b|1b|1.*b|2b) echo 1.5 ;;
    3b|3.*b|4b|4.*b) echo 3 ;;
    7b|7.*b|8b|8.*b|9b) echo 5.5 ;;
    10b|11b|12b|12.*b) echo 8 ;;
    13b|14b|14.*b|15b) echo 9.5 ;;
    2[0-9]b|2[0-9].*b) echo 16 ;;
    3[0-9]b|3[0-9].*b) echo 20 ;;
    *) echo 5.5 ;;  # unknown class: assume an 8B
  esac
}

# Prints the budget line; exit 1 with the refusal when the base model does not fit.
fit_check() {
  local tag="$1" w k need budget
  w=$(weights_gib "$tag"); k=$(kv_gib "$CONTEXT"); budget=$(budget_gib)
  need=$(awk -v w="$w" -v k="$k" 'BEGIN{printf "%.1f", w+k}')
  say_ "  budget: $(total_gib) GiB total − Docker $(docker_gib) GiB − macOS $OS_RESERVE_GIB GiB = $budget GiB; $tag needs ≈ $need GiB (weights $w + KV $k at ${CONTEXT} ctx q8_0)"
  if awk -v n="$need" -v b="$budget" 'BEGIN{exit !(n>b)}'; then
    bad "$tag needs ≈ $need GiB, budget is $budget GiB — lower Docker memory to 8 GiB or pick a smaller model"
    return 1
  fi
  ok "$tag fits the budget"
}

mem_class() {
  local usable; usable=$(budget_gib)
  local cls
  if   awk -v u="$usable" 'BEGIN{exit !(u>=24)}'; then cls="up to a 30B-class 4-bit chat model"
  elif awk -v u="$usable" 'BEGIN{exit !(u>=12)}'; then cls="up to a 14B-class 4-bit chat model"
  elif awk -v u="$usable" 'BEGIN{exit !(u>=9.5)}'; then cls="up to a 12B-class 4-bit chat model"
  elif awk -v u="$usable" 'BEGIN{exit !(u>=7)}';   then cls="up to an 8B-class 4-bit chat model"
  else cls="a 4B-class 4-bit chat model (or lower the Docker limit to 8 GiB)"; fi
  echo "$(total_gib) GB unified memory, Docker limit $(docker_gib) GiB → $usable GiB usable at ${CONTEXT} ctx → $cls"
}

# ── chat server ────────────────────────────────────────────────────────
ollama_tuned() {
  # True when the running server was started with the tuning above (read
  # from its own startup line in our log — only a server we started logs there).
  [ -f "$ollama_pidfile" ] && kill -0 "$(cat "$ollama_pidfile")" 2>/dev/null \
    && grep -q 'OLLAMA_FLASH_ATTENTION:true' "$ollama_log" 2>/dev/null \
    && grep -q 'OLLAMA_KV_CACHE_TYPE:q8_0' "$ollama_log" 2>/dev/null
}

start_ollama() {
  say_ "  starting ollama serve (OLLAMA_HOST=0.0.0.0 so Docker can reach it; flash attention, q8_0 KV, keep-alive $OLLAMA_KEEP_ALIVE)…"
  OLLAMA_HOST=0.0.0.0 nohup ollama serve >"$ollama_log" 2>&1 &
  echo $! > "$ollama_pidfile"
  for _ in $(seq 1 30); do chat_up && break; sleep 1; done
  chat_up && ok "ollama up (pid $(cat "$ollama_pidfile"))" || { bad "ollama did not come up — see $ollama_log"; return 1; }
}

start_chat() {
  if chat_up; then
    if is_ollama && [ -f "$ollama_pidfile" ] && kill -0 "$(cat "$ollama_pidfile")" 2>/dev/null && ! ollama_tuned; then
      # Ours, started before the tuning existed: restart it with the tuning.
      say_ "  restarting the ollama this script started (no flash attention / q8_0 KV in its config)…"
      kill "$(cat "$ollama_pidfile")" 2>/dev/null || true
      for _ in $(seq 1 20); do chat_up || break; sleep 1; done
      start_ollama || return 1
    else
      ok "chat server answering at $MODEL_URL"
      if is_ollama && ! ollama_tuned; then
        say_ "  note: this ollama was not started by this script — OLLAMA_FLASH_ATTENTION=1 OLLAMA_KV_CACHE_TYPE=q8_0 apply only to a server it starts (stop yours and rerun to get the budgeted KV size)"
      fi
    fi
  else
    if command -v ollama >/dev/null; then start_ollama || return 1
    else
      bad "no server at $MODEL_URL and ollama not installed (brew install ollama, or run LM Studio / MLX-serve and set DEV_MAC_MODEL_URL)"; return 1
    fi
  fi
  if is_ollama; then
    local have_ctx=""
    if ollama show "$CHAT_MODEL" >/dev/null 2>&1; then
      have_ctx=$(ollama show "$CHAT_MODEL" --modelfile 2>/dev/null | awk '$1=="PARAMETER" && $2=="num_ctx" {print $3; exit}')
    fi
    if [ -n "$have_ctx" ] && [ "$have_ctx" = "$CONTEXT" ]; then
      ok "model '$CHAT_MODEL' present (num_ctx $have_ctx)"
      fit_check "$CHAT_MODEL" || return 1
    else
      [ -n "$have_ctx" ] && say_ "  '$CHAT_MODEL' has num_ctx $have_ctx, wanted $CONTEXT — recreating"
      fit_check "$BASE_MODEL" || return 1
      ollama show "$BASE_MODEL" >/dev/null 2>&1 || { say_ "  pulling $BASE_MODEL…"; ollama pull "$BASE_MODEL" || { bad "ollama pull $BASE_MODEL failed — no such tag, or offline"; return 1; }; fit_check "$BASE_MODEL" || return 1; }
      say_ "  creating '$CHAT_MODEL' from $BASE_MODEL with num_ctx $CONTEXT ($(basename "$MODELFILE"))…"
      sed -e "s#^FROM .*#FROM $BASE_MODEL#" -e "s#^PARAMETER num_ctx .*#PARAMETER num_ctx $CONTEXT#" "$MODELFILE" > "$state/Modelfile"
      ollama create "$CHAT_MODEL" -f "$state/Modelfile" && ok "created '$CHAT_MODEL'"
    fi
  fi
}

# ── asr server ─────────────────────────────────────────────────────────
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

# ── verify ─────────────────────────────────────────────────────────────
gpu_check() {
  # After the probe the chat model is resident: it must be entirely on the GPU.
  is_ollama || return 0
  local ps_out row
  ps_out=$(ollama ps 2>/dev/null || true)
  say_ "  ollama ps:"; printf '%s\n' "$ps_out" | sed 's/^/    /'
  row=$(printf '%s\n' "$ps_out" | awk -v m="$CHAT_MODEL" '$1==m || $1==m":latest"')
  if [ -z "$row" ]; then bad "'$CHAT_MODEL' is not resident after the probe"; return 1; fi
  if printf '%s' "$row" | grep -q '100% GPU'; then ok "'$CHAT_MODEL' is 100 % GPU"; else
    bad "'$CHAT_MODEL' is partly on the CPU ($(printf '%s' "$row" | grep -oE '[0-9]+%(/[0-9]+%)? [A-Z/]+')) — it does not fit: lower Docker memory to 8 GiB, a smaller context, or a smaller model"; return 1
  fi
}

verify() {
  local rc=0
  say_ "verify:  ($(mem_class))"
  fit_check "$CHAT_MODEL" || true
  DEV_MAC_MODEL_URL="$MODEL_URL" DEV_MAC_CHAT_MODEL="$CHAT_MODEL" DEV_MAC_ASR_URL="$ASR_URL" DEV_MAC_CONTEXT="$CONTEXT" ENV=dev \
    uv run --project "$repo/libs/models" python "$repo/scripts/dev/dev_model_verify.py" || rc=$?
  gpu_check || rc=1
  return $rc
}

status() {
  say_ "dev-model status  ($(mem_class))"
  chat_up && ok "chat: $MODEL_URL (model '$CHAT_MODEL', num_ctx $CONTEXT)" || bad "chat: nothing at $MODEL_URL"
  if is_ollama && chat_up; then ollama ps 2>/dev/null | sed 's/^/    /'; fi
  if asr_up; then asr_is_whisper && ok "asr: whisper-server at $ASR_URL" || bad "asr: port $asr_port taken by $(port_owner "$asr_port")"; else bad "asr: nothing at $ASR_URL"; fi
}

case "$cmd" in
  start) say_ "dev-model start  ($(mem_class))"; start_chat; start_asr; verify ;;
  chat) say_ "dev-model chat  ($(mem_class))"; start_chat ;;
  fit) say_ "dev-model fit  ($(mem_class))"; fit_check "$BASE_MODEL" ;;
  verify) verify ;;
  status) status ;;
  stop)
    if [ -f "$pidfile" ] && kill "$(cat "$pidfile")" 2>/dev/null; then ok "stopped whisper-server"; rm -f "$pidfile"; else say_ "no whisper-server started by this script (ollama is left running)"; fi ;;
  *) echo "usage: $0 [start|chat|fit|verify|status|stop]" >&2; exit 2 ;;
esac
