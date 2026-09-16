# Models on the founder's Mac (DEP-S0 runbook)

Development runs every model locally; staging/beta runs open-weight models on
Hugging Face Inference Endpoints (EU); our own GPU host stays dormant until
gate H0. All three are *backends* in `config/models.yaml` — no worker names
a vendor (Foundation plan, decision 11). This page is the dev-Mac half.

**Measured on this machine (2026-09-05):** Apple M5, **24 GB** unified
memory, macOS 26.4.1. That puts it between the plan's brackets (16 GB → ≤ 8B,
32–36 GB → ≤ 14B): with the 12 GiB Docker dev stack resident, run an
**8B-class 4-bit chat model or smaller**. 12B-class fits only with the dev
stack stopped. `make dev-model ARGS=status` prints the bracket for any Mac.

## 0. One command

```sh
make dev-model                 # start Ollama + whisper-server if missing, create the model, verify
make dev-model ARGS=verify     # probes only
make dev-model ARGS=status
make dev-model ARGS=stop       # stops the whisper-server this script started
```

`verify` fails loudly on the two silent failure modes below (context
truncation, ASR without word timings). Run it after every model change.

## 1. Chat server (Ollama by default)

Any OpenAI-compatible server works — Ollama, LM Studio, MLX-serve,
`llama-server`. Point `DEV_MAC_MODEL_URL` at its `/v1` base.

```sh
brew install ollama
OLLAMA_HOST=0.0.0.0 ollama serve        # 0.0.0.0 so Docker reaches it via host.docker.internal
```

If you run **Ollama.app** instead of `ollama serve`, it listens on
127.0.0.1 only; set `launchctl setenv OLLAMA_HOST 0.0.0.0` and restart the
app, or workers inside Docker get `connection refused`.

Pull the pinned base model (see `docs/models/PINS.md`, row "libs/models
dev_mac") and create the named model — `make dev-model` does both:

```sh
ollama pull gemma3:4b
ollama create notes-chat -f infra/models/dev-mac/Modelfile
```

`config/models.yaml` serves `${DEV_MAC_CHAT_MODEL:-notes-chat}`. To try a
different family: `DEV_MAC_BASE_MODEL=qwen3:8b make dev-model`, or set
`DEV_MAC_CHAT_MODEL=qwen3:8b` directly (then the context gotcha below is
yours to handle).

## 2. Context-length gotcha (the silent one)

Local servers default to a **2–4k context**. Ollama's OpenAI-compatible
`/v1` route ignores a per-request `num_ctx`, so a 60-minute transcript
window is **silently truncated** — the model answers confidently about the
tail of the meeting and nothing else. Fixes, in order of preference:

1. **Modelfile** (what `make dev-model` uses): `infra/models/dev-mac/Modelfile`
   sets `PARAMETER num_ctx 32768`, matching `context_window` in
   `config/models.yaml`.
2. LM Studio: set "Context Length" on the loaded model to ≥ 32768.
3. `llama-server`: `-c 32768`.

`make dev-model ARGS=verify` sends a **~20k-token probe** with a marker at
the *start* of the prompt; a truncating server loses it and the probe
fails with "context too small". A backend that reports `finish_reason:
length` raises `ProviderError(context_exceeded)` — the caller re-chunks
(BE-S2), it never guesses.

Memory: 32k context on an 8B Q4 model needs ~2–3 GB of KV cache on top of
~5 GB weights. Keep **one model resident** (`max_concurrency: 1` in the
config; Ollama unloads after 5 min idle).

## 3. ASR server (whisper.cpp, Metal)

```sh
brew install whisper-cpp
whisper-server -m ~/.cache/whisper-cpp/ggml-large-v3-turbo.bin \
  --host 127.0.0.1 --port 8080 --inference-path /v1/audio/transcriptions --split-on-word
```

`make dev-model` downloads `ggml-large-v3-turbo.bin` (1.6 GB, from
ggerganov/whisper.cpp) and starts this for you. The `--inference-path`
flag is what makes whisper.cpp speak the OpenAI route the `asr_http`
backend expects; the reply carries per-segment `words[]` with
probabilities. `verify` posts the bundled 2.8 s probe clip and **refuses a
server whose reply has no `words[]`** — clip replay (ADR-0037) depends on
word timings, so a timing-less backend is rejected at startup, not
discovered in production.

**Port 8080 is often taken** (on this Mac by a local Python dev server).
Use another port and tell both sides:

```sh
DEV_MAC_ASR_URL=http://localhost:8090 make dev-model
# .env.local, for workers inside Docker:
DEV_MAC_ASR_URL=http://host.docker.internal:8090
```

An MLX whisper wrapper (`tools/asr-mac/`) was in the sprint's "cut first"
list and was cut: whisper.cpp on Metal already meets the A2 turnaround
gate on this Mac (see `docs/eval/turnaround-*.json`).

## 4. Route the stack to the Mac

`ENV=dev` (in `.env.local`) makes the registry apply
`env_overrides.dev` → chat on `dev_mac`, ASR on `dev_mac_asr`. asr-worker
additionally needs `ASR_BACKEND=dev_mac_asr` (its default,
`inproc_cpu_asr`, keeps the baked faster-whisper path so CI and self-host
need no server). Then:

```sh
make dev-model
make eval-smoke BACKEND=dev_mac                       # 5 synthetic meetings → docs/eval/smoke-<date>-dev_mac.json
make measure-turnaround FIXTURE=10min_de BACKEND=dev_mac_asr
```

Fixtures are synthetic TTS built by `scripts/eval/make_tts_fixture.sh`
(gitignored); they measure *turnaround*, not WER. The BE-S2 corpus replaces
them.

## 5. Keep-alive, memory, iteration speed

- One model resident at a time. Chat + whisper together take ~7 GB; the
  dev stack ~12 GiB; that is the 24 GB budget with little to spare —
  close browsers with many tabs before a 60-minute run.
- Expect minutes, not seconds, for 60-minute fixtures on chat (the 32k
  prompt is the cost; generation is ~15–25 tok/s on an 8B Q4). Iterate on
  the 10-minute fixtures; run the 60-minute one before a PR.
- Diarization stays in-process and is slow on the Mac; set
  `DIARIZATION=fixture` to iterate on gold fixtures with known speakers
  (asr-worker respects it from BE-S2; until then diarize=false jobs).
- `dev_mac` refuses to load unless `ENV=dev` — on staging/prod the
  registry raises `backend_not_allowed_in_env` at startup, even if the
  YAML is edited to allow it (`processor.region: local` is hard-refused).

## 6. Where things are

| What | Path |
|---|---|
| Backends, routing, env overrides | `config/models.yaml` |
| Provider seam (protocols, HTTP provider, registry) | `libs/models/` |
| Dev-Mac Modelfile | `infra/models/dev-mac/Modelfile` |
| Start/verify script | `scripts/dev/dev-model.sh`, `scripts/dev/dev_model_verify.py` |
| Eval + measurement | `scripts/eval/smoke_eval.py`, `scripts/eval/measure_turnaround.py` |
| Results | `docs/eval/*.json` |
| Vendor-import gate | `scripts/ci/check-no-vendor-import.py` (`make check-no-vendor-import`) |
