#!/usr/bin/env python3
"""Probe the dev-Mac backends through libs/models, failing loudly: chat liveness,
structured output and a long-context marker probe; ASR words[] on the bundled clip.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
# Probe = 60 % of the backend's `context_window`, so a server truncating to 4K fails.
PROBE_SHARE = 0.6
FILLER_TOKENS_PER_LINE = 14


async def main() -> int:
    from models import ErrorKind, ProviderError, Registry, build_asr_provider, build_chat_provider

    registry = Registry.load(
        REPO / "config" / "models.yaml", env="dev", environ=os.environ, validate=False
    )
    failures = 0

    # ── chat ────────────────────────────────────────────────────────────
    chat_backend = registry.backend("dev_mac", expect_kind="chat")
    chat = build_chat_provider(chat_backend)
    try:
        t0 = time.monotonic()
        await chat.probe()
        print(
            f"  ✓ chat: {chat_backend.model_id} answers at dev_mac in {time.monotonic() - t0:.1f}s"
        )
        schema = {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}, "n": {"type": "integer"}},
            "required": ["ok", "n"],
        }
        r = await chat.complete('Reply with JSON: {"ok": true, "n": 3}', schema, max_tokens=32)
        assert r.json == {"ok": True, "n": 3}, r.text
        print(f"  ✓ chat: structured output mode '{r.structured_mode}' works")
        # Marker at the START, where a truncating server loses it.
        context = chat_backend.caps.context_window
        probe_tokens = int(context * PROBE_SHARE)
        marker = "ZEBRA-7741"
        filler = " ".join(
            f"line {i}: the quarterly review covered revenue, hiring and the roadmap."
            for i in range(1, max(2, probe_tokens // FILLER_TOKENS_PER_LINE))
        )
        prompt = f"The secret code is {marker}.\n\n{filler}\n\nWhat is the secret code? Reply with the code only."
        t0 = time.monotonic()
        r = await chat.complete(prompt, None, max_tokens=16)
        secs = time.monotonic() - t0
        if r.input_tokens and r.input_tokens < probe_tokens * 0.6:
            print(
                f"  ✗ chat: server reported only {r.input_tokens} prompt tokens for a ~{probe_tokens}-token probe — the context window is truncating (runbook step 2: num_ctx {context})"
            )
            failures += 1
        elif marker not in r.text:
            print(
                f"  ✗ chat: marker lost in a ~{probe_tokens}-token prompt (got {r.text.strip()[:40]!r}); context too small (runbook step 2: num_ctx ≥ {context})"
            )
            failures += 1
        else:
            print(
                f"  ✓ chat: {probe_tokens // 1000}k-token context probe ok ({r.input_tokens} prompt tokens, {secs:.0f}s; context_window {context})"
            )
    except ProviderError as exc:
        hint = (
            " — is the server running? `make dev-model`"
            if exc.kind in (ErrorKind.UNAVAILABLE, ErrorKind.TIMEOUT)
            else ""
        )
        print(f"  ✗ chat: {exc.kind}: {exc.message}{hint}")
        failures += 1
    finally:
        await chat.aclose()

    # ── asr ─────────────────────────────────────────────────────────────
    asr_backend = registry.backend("dev_mac_asr", expect_kind="asr")
    asr = build_asr_provider(asr_backend)
    try:
        await asr.warm_up()
        print(
            f"  ✓ asr: /v1/audio/transcriptions returns words[] ({asr.warmup_seconds:.1f}s for the probe clip)"
        )
    except ProviderError as exc:
        print(f"  ✗ asr: {exc.kind}: {exc.message}")
        failures += 1
    finally:
        await asr.aclose()

    print("verify: " + ("ok" if not failures else f"{failures} problem(s)"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
