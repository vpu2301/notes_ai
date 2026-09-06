# ADR-0046: Model hosting is configuration — `libs/models` and the backend registry

Date: 2026-09-05
Status: Accepted
Sprint: DEP-S0 (Foundation plan rev 1.1, decisions 11–12)

## Context

Every AI gate in the Foundation roadmap was blocked on hardware nobody has
bought: three release gates already waited on an A10G rig (ADR-0034, 0035,
0036), the only LLM seam was a vendor-specific stub
(`note_service/domain/synthesis.py::AnthropicSynthesizer`, `NotImplementedError`),
and ASR had one hard-wired in-process path. The founder's constraint for this
window: development runs models on the founder's Apple-silicon Mac, staging
and beta run open-weight models on Hugging Face Inference Endpoints in an EU
region, and a cloud host of our own is reserved for premium workspaces later —
**not started now, switchable later without a rewrite**.

That plan survives contact with code only if no worker ever names a vendor.

## Decision

1. **One package, three protocols.** `libs/models` defines `ChatProvider`,
   `ASRProvider` and `EmbeddingProvider` (the last completed in DEP-S5).
   Every worker codes against them; the result of every call carries
   `backend` and `model_id` for provenance (`ProviderResult`,
   `TranscriptionOutput.metadata.model`), and every call emits a
   `model_usage` record (counts and identifiers, never content).
2. **One HTTP contract, not one class per vendor.** Ollama, LM Studio,
   MLX-serve, `llama-server`, TGI, vLLM and HF Inference Endpoints all speak
   `POST /v1/chat/completions`; `OpenAICompatibleChatProvider` serves all of
   them. What differs — structured-output flavour (`json_schema` /
   `json_object` / vLLM `guided_json` / `probe`), auth, cold start, context
   window, concurrency — is **configuration** on the backend in
   `config/models.yaml`. ASR likewise: `asr_http` speaks
   `POST /v1/audio/transcriptions` (whisper.cpp server, Speaches, vLLM
   Whisper, an HF endpoint behind an OpenAI-compatible handler);
   `asr_inproc` wraps today's faster-whisper engine unchanged.
   `AnthropicProvider` is the only vendor-specific class — opt-in, BE-S3,
   `NotConfigured` until then. Rejected: LangChain/LiteLLM-style routers
   (dependency weight, hidden retries, a second config language).
3. **Resolution at startup, not per call.** `Registry.resolve(workspace_id,
   operation)` reads the workspace provider setting (`platform` → routing
   table; `anthropic`; `custom` in S7), the workspace **tier** (`standard` →
   `hf_eu` now, `premium` → `hosted_eu` once gate H0 passes) and the
   per-env override (`dev` → the Mac, `test` → recorded cassettes /
   in-process whisper). `Registry.validate()` walks every reachable route
   at boot; a misconfigured environment refuses to start
   (`ConfigError` with a stable code) instead of failing jobs at 3 a.m.
4. **`dev_mac` is a guarded backend.** Any backend whose processor region is
   `local` may only be enabled in `dev`/`test`; the config file itself is
   rejected if it says otherwise, and a `staging`/`prod` process that is
   routed to it refuses to boot (`backend_not_allowed_in_env`). This cannot
   be undone by a config typo.
5. **Word timings are a contract.** Clip replay (ADR-0037) needs per-word
   timings; an HTTP ASR backend whose probe reply carries no `words[]` is
   rejected at startup. The `asr_http` provider glues punctuation tokens
   onto the preceding word so both backends produce the faster-whisper
   shape downstream.
6. **Switching a tier's backend is a config PR reviewed like a migration**:
   eval parity (`make eval-smoke BACKEND=…`, keyed by `(backend, model_id)`)
   → shadow run (DEP-S5) → flip → rollback path. `hosted_eu` is registered
   now, `enabled: false`, so the H0 switch is one reviewed line.
7. **Data-control binds the registry (decision 12).** A workspace's data
   goes only to processors the registry can resolve for its env;
   `Registry.processors_for_env()` is the Data page's input. There is no
   fallback path to a processor that is not on the page.
8. **The `no-vendor-import` gate** (`scripts/ci/check-no-vendor-import.py`,
   `make check-no-vendor-import`, CI "gates" job) fails the build if
   `anthropic`/`openai`/`huggingface_hub`/… is imported outside
   `libs/models` (build-time pin tooling under `scripts/models/` excepted).

asr-worker is the first consumer: `ASR_BACKEND` names a backend
(`inproc_cpu_asr` default — byte-identical to the pre-seam worker, parity
test in `libs/models/tests/unit/test_asr_inproc.py`; `dev_mac_asr`;
`hf_eu_asr`). The understanding-worker (BE-S2) will be the first chat
consumer.

## Measured (2026-09-05, Apple M5, 24 GB, macOS 26.4.1)

See `docs/eval/turnaround-2026-09-05-*.json` and `docs/eval/smoke-2026-09-05-dev_mac.json`;
the numbers are quoted in the amended ADR-0034/0035/0036 and in the
"Model family" section below. The GPU line for every gate now reads
**"deferred to the DEP-S6 metered sandbox"**; `hf_eu` numbers land when
DEP-S1 provisions the endpoint (by 18 Sep; G0 accepts Mac + CPU numbers if
HF slips).

## Model family (G0 decision)

Smoke eval: five synthetic meetings (3 EN, 1 DE, 1 UK), JSON-schema
structured extraction with verbatim evidence quotes, `temperature 0`, on the
founder's M5 via Ollama 0.32.5 (`docs/eval/smoke-2026-09-05-dev_mac-*.json`):

| Family / model (Q4_K_M) | Passed | Hallucinated quotes | p50 latency | max latency | Notes |
|---|---|---|---|---|---|
| **Gemma 3 — gemma3:4b** | 5/5 | 0 / 18 | 21.7 s | 24.8 s | native `json_schema`; no special handling |
| Qwen3 — qwen3:8b | 5/5 | 0 / 19 | 33.6 s | 54.6 s | needs `request_overrides: {reasoning_effort: none}` or it spends the budget on `<think>` |

Both families satisfy the DEP-S0 bar (schema-valid, evidence-bearing, no
invented quotes, DE/UK output in the meeting language). **Decision: Gemma 3
is the family for this window** — 4B on the dev Mac (`notes-chat`), and the
same family on `hf_eu` (`google/gemma-3-4b-it` on an L4 first; the DEP-S2
eval matrix decides whether 12B on a larger instance earns its cost). Why
not Qwen3: ~1.5–2× slower at the same task on this hardware, and the
reasoning switch is one more server-specific knob to carry across TGI/vLLM.
Qwen3-8B stays in the registry's vocabulary as the DEP-S2 comparison
candidate; nothing about this decision is code.

## Consequences

- No worker, router or job ever imports a vendor SDK or reads a model URL;
  adding a backend is YAML plus, at most, one line in `factory.py`.
- Every eval result, calibration table (S4) and cost figure (DEP-S4) is
  keyed by `(backend, model_id)`; a model-pin change cannot ship without
  the eval gate (DEP-S4).
- `libs/models` depends on `asr_models` only (import-linter contract);
  libs never read `os.environ` — the service's `config.py` passes the
  mapping in.
- Known limitations recorded deliberately: structured-output *probing* is a
  flag plus a `json_object` fallback (full capability matrix in DEP-S2);
  embeddings are declared, not implemented (DEP-S5); the `custom`
  (bring-your-own-endpoint) provider setting raises until DEP-S7.

## What would re-open this

A backend we need that does not speak the OpenAI-compatible HTTP API
(then it gets its own class beside `AnthropicProvider`, still behind the
registry); an eval showing the `hf_eu` structured-output fallback
(`json_object` + in-band schema) is measurably worse than `json_schema`
on the beta model (then DEP-S2 pins a model/server pair that enforces
schemas); or gate H0 passing, which flips `premium` to `hosted_eu` by PR.
