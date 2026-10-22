# LLM provider adapters — field mapping (sprint 3)

Every chat call in the product goes through `libs/models`' `OpenAICompatibleChatProvider`
(all chat backends in `config/models.yaml` are `kind: openai_compat`). It emits one
`models.AttemptRecord` per HTTP attempt; `telemetry.llm.on_attempt` turns each into an
`llm_call` row + `llm_call` span when a processing run is current (metrics always). The billing
ledger (`model_usage`, `UsageRecord`) is unchanged: one record per call, as before.

Call sites and purposes (CI guard: `tests/unit/test_llm_call_sites.py`, allowlist
`tests/unit/llm_call_sites.allowlist`):

| Purpose | Call site | In a run? |
|---|---|---|
| `note_write` | `note_service/domain/writer.py` `call()` — one per 25-min window | yes (initial run continued, or a regeneration's `reprocess` run) |
| `note_merge` | `writer.py` merge (> 1 window, `MERGE_RETRIES=1`) | yes |
| `note_check` | `note_service/domain/checker.py` (`MDX_NOTE_CHECK`) | yes |
| `provider_probe` | note worker `_probe` hook — 1–2 real completions before every job | yes |
| `note_ask` | `note_service/domain/ask.py` (`POST /v1/notes/{id}/ask`) | no recording run → metrics only |
| `inline_completion` | generation-service Layer C (own llama.cpp/Ollama adapter) | allowlisted; no run (Sprint 0 Q8), not yet in metrics |

## Field mapping per backend

| `llm_call` field | OpenAI-compatible (Mistral, HF TGI/vLLM, Ollama `/v1`, llama.cpp `/v1`) | Source |
|---|---|---|
| `total_latency_seconds` | monotonic, request sent → last byte, **this attempt** | provider loop |
| `time_to_first_token_seconds` | null `not_applicable` — every call is non-streaming (`"stream": false`) | — |
| `queue_wait_seconds` | concurrency-slot wait (attempt 1) or the 429 / retry back-off slept before this attempt | provider loop |
| `model_load_seconds` | the `warming` (HTTP 503 + `cold_start_seconds`) sleep before this attempt; attempt 1 → null `not_applicable` | provider loop |
| `input_tokens` / `output_tokens` | `usage.prompt_tokens` / `usage.completion_tokens` as reported | response |
| `cached_input_tokens` | `usage.prompt_tokens_details.cached_tokens` (subset of input) — Mistral/Ollama omit it → null `unavailable` | response |
| `reasoning_tokens` | `usage.completion_tokens_details.reasoning_tokens` (subset of output) — absent → null `unavailable` | response |
| `token_source` | `provider` when usage present; else `estimated` (characters / 4 — no tokenizer in the repo) | — |
| `token_accounting_note` | "prompt_tokens includes cached_tokens; completion_tokens includes reasoning_tokens; stored as reported, subsets never added again" | — |
| `generation_tokens_per_second` | llama.cpp `timings.predicted_per_second` when present; else null `not_supported` (no TTFT without streaming, so `output / (total − ttft)` is not derivable) | response |
| `model` | the response's `model` (what answered); else the configured id | response |
| `execution_mode` | from the base URL: `localhost` / `host.docker.internal` → `native` (Ollama on the Mac), a single-label service host (`llama-server`) → `container`, anything else → `remote` | `telemetry.llm.execution_mode_for` |
| device | remote → null `not_applicable`; native Ollama → `telemetry.llm.ollama_device` reads `/api/ps` (`size_vram` vs `size` → `gpu` / `cpu` / `gpu_partial:0.xx`, **observed**); otherwise null `unavailable` | adapter |
| `error_category` / `error_subtype` | `llm`; subtype from `models.ErrorKind`: `rate_limited→rate_limit`, `timeout`, `schema_invalid→parse`, `context_exceeded→context_length`, `warming`, `unavailable`, `auth` | provider loop |
| `prompt_chars` / `completion_chars` | lengths of system + user messages / of the answer — never the text | provider loop |

Ollama-native fields (`load_duration`, `prompt_eval_duration`, `eval_count`) are only returned by
`/api/generate` and `/api/chat`; the product calls Ollama's OpenAI-compatible `/v1` endpoint,
which does not return them, so they are not available. Anthropic (`kind: anthropic`) is a stub
that raises `provider_not_configured`; its convention ("cache_read_input_tokens are separate from
input_tokens") applies when it is implemented.
