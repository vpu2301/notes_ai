#!/usr/bin/env python3
"""Apply / diff Hugging Face Inference Endpoint specs (DEP-S1-01).

    hf_endpoints.py plan   --env staging          # diff live vs deploy/hf/endpoints/*.yaml (exit 2 on drift)
    hf_endpoints.py apply  --env staging          # create or update to match the specs
    hf_endpoints.py status --env staging          # state, URL, replicas
    hf_endpoints.py pause|resume --env staging
    hf_endpoints.py delete --env staging --yes
    hf_endpoints.py validate                      # schema-check the specs offline (no token)

Plain HTTPS against https://api.endpoints.huggingface.cloud/v2/endpoint/{namespace}
— no vendor SDK. Needs HF_TOKEN (fine-grained, endpoints:write) and
HF_NAMESPACE. The token is never printed; API error bodies are redacted.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import httpx
import yaml

REPO = Path(__file__).resolve().parents[2]
SPEC_DIR = REPO / "deploy" / "hf" / "endpoints"
API = "https://api.endpoints.huggingface.cloud/v2/endpoint"
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_ENVS = ("staging", "prod")


class SpecError(ValueError):
    pass


# ── spec ────────────────────────────────────────────────────────────────
def load_specs(env: str | None = None) -> list[dict[str, Any]]:
    specs = []
    for path in sorted(SPEC_DIR.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise SpecError(f"{path.name}: top level must be a mapping")
        validate_spec(raw, path.name)
        if env:
            raw = json.loads(json.dumps(raw).replace("{env}", env))
        raw["_file"] = path.name
        specs.append(raw)
    if not specs:
        raise SpecError(f"no specs under {SPEC_DIR}")
    return specs


def validate_spec(spec: dict[str, Any], name: str) -> None:
    required = {"name", "task", "type", "model", "provider", "compute"}
    missing = required - set(spec)
    if missing:
        raise SpecError(f"{name}: missing {sorted(missing)}")
    extra = set(spec) - required - {"_file"}
    if extra:
        raise SpecError(f"{name}: unknown top-level key(s) {sorted(extra)}")
    if spec["type"] != "protected":
        raise SpecError(f"{name}: type must be 'protected' (no public inference URL)")
    region = str(spec["provider"].get("region", ""))
    if not region.startswith("eu-"):
        raise SpecError(f"{name}: provider.region must be an EU region, got {region!r}")
    model = spec["model"]
    for key in ("repository", "revision"):
        if not model.get(key):
            raise SpecError(f"{name}: model.{key} is required")
    if model["revision"] != "PIN_ME" and not _COMMIT.match(str(model["revision"])):
        raise SpecError(
            f"{name}: model.revision must be a 40-hex immutable commit (from docs/models/PINS.md), not {model['revision']!r}"
        )
    scaling = spec["compute"].get("scaling", {})
    if int(scaling.get("min_replica", 1)) != 0:
        raise SpecError(
            f"{name}: compute.scaling.min_replica must be 0 (scale-to-zero) in this window"
        )
    if int(scaling.get("max_replica", 0)) > 2:
        raise SpecError(f"{name}: compute.scaling.max_replica > 2 needs a cost decision (DEP-S6)")


def to_api_body(spec: dict[str, Any]) -> dict[str, Any]:
    """Spec → Endpoints API body (create/update)."""
    model = spec["model"]
    scaling = spec["compute"].get("scaling", {})
    body: dict[str, Any] = {
        "name": spec["name"],
        "type": spec["type"],
        "provider": {"vendor": spec["provider"]["vendor"], "region": spec["provider"]["region"]},
        "compute": {
            "accelerator": spec["compute"]["accelerator"],
            "instanceType": spec["compute"]["instance_type"],
            "instanceSize": spec["compute"]["instance_size"],
            "scaling": {
                "minReplica": int(scaling.get("min_replica", 0)),
                "maxReplica": int(scaling.get("max_replica", 1)),
                "scaleToZeroTimeout": int(scaling.get("scale_to_zero_timeout", 15)),
            },
        },
        "model": {
            "repository": model["repository"],
            "revision": model["revision"],
            "task": spec["task"],
            "framework": model.get("framework", "pytorch"),
        },
    }
    image = model.get("image")
    if image:
        body["model"]["image"] = _image_body(image)
    return body


def _image_body(image: dict[str, Any]) -> dict[str, Any]:
    if "tgi" in image:
        tgi = image["tgi"]
        return {
            "tgi": {
                "healthRoute": "/health",
                "port": 80,
                "url": "ghcr.io/huggingface/text-generation-inference:latest",
                "maxInputTokens": int(tgi.get("max_input_tokens", 8192)),
                "maxTotalTokens": int(tgi.get("max_total_tokens", 16384)),
                "maxBatchPrefillTokens": int(tgi.get("max_batch_prefill_tokens", 16384)),
            }
        }
    if "custom" in image:
        c = image["custom"]
        return {
            "custom": {
                "url": c["url"],
                "port": int(c.get("port", 80)),
                "health_route": c.get("health_route", "/health"),
                "env": {k: str(v) for k, v in (c.get("env") or {}).items()},
            }
        }
    raise SpecError(f"unknown image kind: {sorted(image)}")


# ── api ─────────────────────────────────────────────────────────────────
class Client:
    def __init__(self) -> None:
        token = os.environ.get("HF_TOKEN")
        ns = os.environ.get("HF_NAMESPACE")
        if not token or not ns:
            raise SystemExit(
                "HF_TOKEN and HF_NAMESPACE must be set (secret manager / .env.local, never committed)"
            )
        self._token = token
        self._http = httpx.Client(
            base_url=f"{API}/{ns}", headers={"Authorization": f"Bearer {token}"}, timeout=60
        )

    def _call(
        self, method: str, path: str = "", body: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        resp = self._http.request(method, path, json=body)
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            text = resp.text.replace(self._token, "***")[:300]
            raise SystemExit(f"HF API {method} {path or '/'} → HTTP {resp.status_code}: {text}")
        return resp.json() if resp.content else {}

    def get(self, name: str) -> dict[str, Any] | None:
        return self._call("GET", f"/{name}")

    def create(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._call("POST", "", body) or {}

    def update(self, name: str, body: dict[str, Any]) -> dict[str, Any]:
        patch = {k: v for k, v in body.items() if k in ("compute", "model")}
        return self._call("PUT", f"/{name}", patch) or {}

    def delete(self, name: str) -> None:
        self._call("DELETE", f"/{name}")

    def pause(self, name: str) -> None:
        self._call("POST", f"/{name}/pause")

    def resume(self, name: str) -> None:
        self._call("POST", f"/{name}/resume")


# ── diff ────────────────────────────────────────────────────────────────
def _flatten(d: Any, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(d, dict):
        for k, v in d.items():
            out.update(_flatten(v, f"{prefix}{k}."))
    else:
        out[prefix.rstrip(".")] = d
    return out


def diff(spec_body: dict[str, Any], live: dict[str, Any]) -> list[str]:
    """Lines describing drift; empty means in sync. Compares only keys the spec owns."""
    want = _flatten({k: v for k, v in spec_body.items() if k != "name"})
    have = _flatten({k: live.get(k) for k in ("type", "provider", "compute", "model")})
    lines = []
    for key, value in sorted(want.items()):
        if key in ("model.image.tgi.url",):
            continue  # HF pins its own TGI image tag
        if have.get(key) != value:
            lines.append(f"  {key}: live={have.get(key)!r} spec={value!r}")
    return lines


# ── commands ────────────────────────────────────────────────────────────
def cmd_validate(_args: argparse.Namespace) -> int:
    specs = load_specs()
    for spec in specs:
        pin = (
            "PIN_ME (fill before apply)"
            if spec["model"]["revision"] == "PIN_ME"
            else spec["model"]["revision"][:12]
        )
        print(
            f"ok  {spec['_file']:<12} {spec['name']:<22} {spec['model']['repository']} @ {pin}  {spec['provider']['region']}  {spec['compute']['instance_type']} x{spec['compute']['scaling']['max_replica']}"
        )
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    client = Client()
    drift = 0
    for spec in load_specs(args.env):
        body = to_api_body(spec)
        live = client.get(spec["name"])
        if live is None:
            print(f"+ create {spec['name']} ({spec['_file']})")
            drift += 1
            continue
        lines = diff(body, live)
        if lines:
            print(f"~ update {spec['name']} ({spec['_file']}):")
            print("\n".join(lines))
            drift += 1
        else:
            print(f"= {spec['name']} in sync ({live.get('status', {}).get('state', '?')})")
    return 2 if drift else 0


def cmd_apply(args: argparse.Namespace) -> int:
    client = Client()
    for spec in load_specs(args.env):
        if spec["model"]["revision"] == "PIN_ME":
            raise SystemExit(
                f"{spec['_file']}: model.revision is PIN_ME — pin it from docs/models/PINS.md before apply"
            )
        body = to_api_body(spec)
        live = client.get(spec["name"])
        if live is None:
            result = client.create(body)
            print(
                f"created {spec['name']} → {result.get('status', {}).get('url', '(url pending)')}"
            )
        elif diff(body, live):
            client.update(spec["name"], body)
            print(f"updated {spec['name']}")
        else:
            print(f"unchanged {spec['name']}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    client = Client()
    for spec in load_specs(args.env):
        live = client.get(spec["name"])
        if live is None:
            print(f"{spec['name']:<22} absent")
            continue
        st = live.get("status", {})
        print(
            f"{spec['name']:<22} {st.get('state', '?'):<12} replicas={st.get('replica', {}).get('current', '?')}/{st.get('replica', {}).get('target', '?')}  url={st.get('url', '-')}"
        )
    return 0


def _simple(action: str) -> Any:
    def run(args: argparse.Namespace) -> int:
        client = Client()
        for spec in load_specs(args.env):
            if action == "delete" and not args.yes:
                raise SystemExit("delete needs --yes")
            getattr(client, action)(spec["name"])
            print(f"{action}d {spec['name']}")
        return 0

    return run


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (
        ("validate", cmd_validate),
        ("plan", cmd_plan),
        ("apply", cmd_apply),
        ("status", cmd_status),
        ("pause", _simple("pause")),
        ("resume", _simple("resume")),
        ("delete", _simple("delete")),
    ):
        p = sub.add_parser(name)
        if name != "validate":
            p.add_argument("--env", required=True, choices=_ENVS)
        if name == "delete":
            p.add_argument("--yes", action="store_true")
        p.set_defaults(fn=fn)
    args = ap.parse_args()
    try:
        return int(args.fn(args))
    except SpecError as exc:
        print(f"spec error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
