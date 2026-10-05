#!/usr/bin/env python3
"""Record a chat cassette (key = sha256(model, prompt, schema, system)) for the
``recorded`` test-env backend. Never record real customer content.

    uv run --project libs/models python scripts/eval/record_cassette.py --backend dev_mac --prompt-file prompt.txt --out tests/fixtures/eval/cassettes
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from _common import load_registry


async def run(args: argparse.Namespace) -> int:
    from models import RecordedChatProvider, build_chat_provider

    registry = load_registry()
    provider = build_chat_provider(registry.backend(args.backend, expect_kind="chat"))
    prompt = Path(args.prompt_file).read_text(encoding="utf-8")
    schema = (
        json.loads(Path(args.schema_file).read_text(encoding="utf-8")) if args.schema_file else None
    )
    system = Path(args.system_file).read_text(encoding="utf-8") if args.system_file else None
    result = await provider.complete(prompt, schema, max_tokens=args.max_tokens, system=system)
    await provider.aclose()
    path = RecordedChatProvider(
        backend="recorded", cassette_dir=args.out, model_id=args.model_id
    ).record(prompt, schema, system, result)
    print(
        f"recorded {path} from {result.backend}/{result.model_id} ({result.input_tokens} in / {result.output_tokens} out)"
    )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--backend", required=True)
    ap.add_argument("--prompt-file", required=True)
    ap.add_argument("--schema-file")
    ap.add_argument("--system-file")
    ap.add_argument(
        "--model-id",
        default="recorded",
        help="model id the test env will ask for (default: recorded)",
    )
    ap.add_argument("--out", default="tests/fixtures/eval/cassettes")
    ap.add_argument("--max-tokens", type=int, default=1500)
    return asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main())
