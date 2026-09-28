# Models on the founder's Mac (DEP-S0 runbook)

Development runs every model locally; staging/beta runs open-weight models on
Hugging Face Inference Endpoints (EU); our own GPU host stays dormant until
gate H0. All three are *backends* in `config/models.yaml` — no worker names
a vendor (Foundation plan, decision 11). This page is the dev-Mac half.

**Measured on this machine (2026-09-05, budget rule 2026-09-27):** Apple M5,
**24 GB** unified memory, macOS 26.4.1. What fits is a budget, not a
bracket (Sprint L1 T1):

```
budget = total unified memory − Docker VM limit (docker info MemTotal; 12 GiB when unknown) − 3 GiB for macOS
need   = 4-bit weights + KV cache at the baked context (q8_0: ≈ 1.5 GiB at 16K, ≈ 3 GiB at 32K)
```

| Base model (Q4) | Weights | + KV 16K | Fits when the budget is ≥ |
|---|---|---|---|
| `gemma3:4b` | 3 GiB | 4.5 GiB | 4.5 GiB — any setting |
| `qwen3:8b`, `llama3.1:8b` | 5.5 GiB | 7 GiB | 7 GiB — Docker ≤ 14 GiB on 24 GB |
| `gemma3:12b-it-qat`, `gemma4:12b` | 8 GiB | 9.5 GiB | 9.5 GiB — **Docker ≤ 8 GiB on 24 GB** |
| `qwen3:14b` | 9.5 GiB | 11 GiB | 11 GiB — Docker ≤ 8 GiB on 24 GB (the local ceiling) |
| 24B–27B | 16 GiB | 17.5 GiB | 32 GB Macs and up |

**For model work, set Docker Desktop (or Colima) memory to 8 GiB.** With the
default 13.6 GiB limit a 24 GB Mac has 7.4 GiB for a model: 8B is the
ceiling and 12B is refused. `make dev-model` prints the budget and refuses
a base model over it ("`<tag>` needs ≈ N GiB, budget is M GiB — lower Docker
memory to 8 GiB or pick a smaller model"); `DEV_MAC_DOCKER_GIB` overrides
the Docker figure (e.g. `0` when Docker is stopped). `make dev-model
ARGS=fit` checks a tag without changing anything; `ARGS=verify` also prints
`ollama ps` and fails unless the model is **100 % GPU** — a partial CPU
offload is the silent way a model that does not fit still "works", at a
tenth of the speed.

## 0. Where the Mac fits (Sprint L2)

Since L2 the dev stack writes notes with **Mistral's EU API** when
`MISTRAL_API_KEY` is in `.env.local`, and with **this Mac's model** when it
is not, when the API does not answer the startup probe, or when
`MDX_DEV_CHAT_BACKEND=dev_mac` forces it. The startup log says which
(`models.route` / `models.override_fallback reason=…`) and the Data
settings page shows "Notes are written by: …". Everything below is the
local half — the fallback — and it has to produce a usable note on its
own.

**A database that predates L2 needs `make seed` once.** Since L2 nothing
is written until a workspace admin has acknowledged every processor in
the data path, and the dev tenants get theirs from the seed
(`_seed_ai_processors`: Mistral AI (EU) and Developer machine (local)).
On a stack that was migrated but not re-seeded, every capture ends as a
bare transcript with no summary and a default title, and the client shows
"a workspace admin has to agree to who processes your meetings"
(`meeting.generation_blocked reason=processor_unacknowledged` in the
note-service log). Run `make seed`, or agree on Settings › Data.

## 1. One command

```sh
make dev-model                 # start Ollama + whisper-server if missing, create the model, verify
make dev-model ARGS=verify     # probes only: context, structured output, ASR words[], 100 % GPU
make dev-model ARGS=status
make dev-model ARGS=fit        # memory budget for DEV_MAC_BASE_MODEL, no changes
make dev-model ARGS=chat       # chat model only (what the bake-off calls per candidate)
make dev-model ARGS=stop       # stops the whisper-server this script started (Ollama is left running)
```

`verify` fails loudly on the three silent failure modes below (context
truncation, ASR without word timings, CPU offload). Run it after every
model change.

An `ollama serve` this script starts gets `OLLAMA_FLASH_ATTENTION=1`,
`OLLAMA_KV_CACHE_TYPE=q8_0`, `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_KEEP_ALIVE=30m`
— the KV sizes in the budget assume them. A server started elsewhere
(Ollama.app, your own shell) keeps its own settings; the script says so.

## 2. Chat server (Ollama by default)

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
yours to handle). The named model is recreated when its `num_ctx` differs
from `DEV_MAC_CONTEXT`.

**Two Modelfiles** (Sprint L1): `infra/models/dev-mac/Modelfile` bakes
**`num_ctx 16384`** — the pipeline's calls are small (a 6 000-character
window ≈ 2.5k tokens + ≈ 1.2k system + ≤ 3k output; a block reduce ≈ 4k in,
2.5k out), and 32K of KV cache is what stopped a 12B fitting on 24 GB.
`Modelfile.longctx` bakes 32K for the one caller that hands a whole
transcript to the model, the eval's single-pass arm:

```sh
DEV_MAC_CHAT_MODEL=notes-chat-long make dev-model ARGS=chat        # a *-long name selects Modelfile.longctx
DEV_MAC_CHAT_MODEL=notes-chat-long DEV_MAC_CONTEXT=32768 make eval-notes BACKEND=dev_mac ARM=single_pass
```

`dev_mac.context_window` is `${DEV_MAC_CONTEXT:-16384}`; set the variable
to match the model you point the stack at.

**Running the harness on the host:** `config/models.yaml`'s default URL is
the Docker-side name `host.docker.internal`, which a plain shell may not
resolve. `make local-bakeoff` sets `DEV_MAC_MODEL_URL=http://localhost:11434/v1`;
do the same for a hand-run `make eval-notes`.

**Small-model profile.** `dev_mac` is the only backend with
`small_model: true` (`${DEV_MAC_SMALL_MODEL:-true}`). The document engine
then gives the model simpler work: twelve facts per window instead of the
density rule, one extraction example, no `noise` field, reduce calls over
at most fifteen facts with the heading asked in its own call and no
sub-points, the strict summary rung first, and a retry that echoes the
schema after a malformed answer. Verification is untouched. Every run
records `stats.small_model_profile`; `DEV_MAC_SMALL_MODEL=false` runs the
engine as a hosted backend sees it. Qwen 3 families think by default; the
backend sends `reasoning_effort: none` (`DEV_MAC_REASONING_EFFORT`), which
Gemma ignores.

## 3. Context-length gotcha (the silent one)

Local servers default to a **2–4k context**. Ollama's OpenAI-compatible
`/v1` route ignores a per-request `num_ctx`, so a 60-minute transcript
window is **silently truncated** — the model answers confidently about the
tail of the meeting and nothing else. Fixes, in order of preference:

1. **Modelfile** (what `make dev-model` uses): `infra/models/dev-mac/Modelfile`
   sets `PARAMETER num_ctx 16384`, matching `context_window` in
   `config/models.yaml` (`Modelfile.longctx`: 32768 for the single-pass arm).
2. LM Studio: set "Context Length" on the loaded model to ≥ 16384.
3. `llama-server`: `-c 16384`.

`make dev-model ARGS=verify` sends a probe worth **60 % of the configured
context** (≈ 9.8k tokens at 16K, ≈ 19.6k at 32K) with a marker at the
*start* of the prompt; a truncating server loses it and the probe fails
with "context too small". A backend that reports `finish_reason: length`
raises `ProviderError(context_exceeded)` — the caller re-chunks (BE-S2), it
never guesses.

Memory: 16K of q8_0 KV cache is ≈ 1.5 GiB, 32K ≈ 3 GiB, on top of the
weights (table above). Keep **one model resident** (`max_concurrency: 1` in
the config; the script's Ollama keeps a model for 30 min idle).

## 4. ASR server (whisper.cpp, Metal)

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

## 5. Route the stack to the Mac

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

## 6. Keep-alive, memory, iteration speed

- One model resident at a time. The budget above is the rule: on this Mac
  with Docker at its default 13.6 GiB, 7.4 GiB — an 8B at 16K and nothing
  larger. Lower Docker to 8 GiB for a 12B/14B run. Close browsers with many
  tabs before a long run.
- Expect minutes, not seconds, per recording (the 2026-09-26 4B run took
  ≈ 4 000 s per meeting-hour through the pipeline). Iterate on one synthetic
  meeting; run the corpus before a PR.
- Diarization stays in-process and is slow on the Mac; set
  `DIARIZATION=fixture` to iterate on gold fixtures with known speakers
  (asr-worker respects it from BE-S2; until then diarize=false jobs).
- `dev_mac` refuses to load unless `ENV=dev` — on staging/prod the
  registry raises `backend_not_allowed_in_env` at startup, even if the
  YAML is edited to allow it (`processor.region: local` is hard-refused).

## 7. Local bake-off (Sprint L1 T3)

```sh
make local-bakeoff                                        # synthetic corpus, default candidates
make local-bakeoff CORPUS=scripts/eval/local/real         # r01–r03 (never committed)
make local-bakeoff CANDIDATES="gemma3:4b qwen3:8b" CORPUS=…
```

`scripts/dev/local-bakeoff.sh` runs, per tag: the fit check, `ollama pull`,
`make dev-model ARGS=chat` into `notes-chat-<slug>`, `make eval-notes
BACKEND=dev_mac ARM=pipeline LABEL=<slug>` and `make eval-notes-assert`,
while sampling `ollama ps` for peak size and GPU share. The "before" row
runs `--before gemma3:4b` with the profile off. Default candidates:
`gemma3:4b qwen3:8b gemma3:12b-it-qat qwen3:14b llama3.1:8b`, plus
`gemma4:*` / `qwen3.6:*` tags when the registry serves them (checked, never
assumed). A tag that does not exist or does not fit is a row that says so.
Manifest entries land under `scripts/eval/local/bakeoff-<date>/` (gitignored);
`scripts/eval/local_bakeoff_report.py` writes
`docs/eval/notes-local-bakeoff-<date>.md` — numbers only. The API row is
appended by L2.

## 8. Where things are

| What | Path |
|---|---|
| Backends, routing, env overrides | `config/models.yaml` |
| Provider seam (protocols, HTTP provider, registry) | `libs/models/` |
| Dev-Mac Modelfiles | `infra/models/dev-mac/Modelfile` (16K), `Modelfile.longctx` (32K, single-pass arm) |
| Start/verify script | `scripts/dev/dev-model.sh`, `scripts/dev/dev_model_verify.py` |
| Eval + measurement | `scripts/eval/smoke_eval.py`, `scripts/eval/notes_eval.py`, `scripts/eval/measure_turnaround.py` |
| Local bake-off | `scripts/dev/local-bakeoff.sh`, `scripts/eval/local_bakeoff_report.py` |
| Results | `docs/eval/*.json`, `docs/eval/notes-local-bakeoff-<date>.md` |
| Vendor-import gate | `scripts/ci/check-no-vendor-import.py` (`make check-no-vendor-import`) |
