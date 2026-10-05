"""Assemble the pinned pyannote community-1 model dir: fetch at an immutable revision
from the GATED repo, verify SHA-256 fail-closed, load fully offline. The token
(``--token-file`` or huggingface_hub's lookup) is never printed or written.

    uv run python scripts/models/prepare_pyannote.py [--target DIR]
    uv run python scripts/models/prepare_pyannote.py --resolve-pins [--revision <commit>]
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO = "pyannote/speaker-diarization-community-1"
# Immutable commit (docs/models/PINS.md); never a branch or tag.
REVISION = "3533c8cf8e369892e6b79ff1bf80f7b0286a54ee"

# Weight artifact -> pinned SHA-256. An EMPTY digest = not pinned yet: the
# install refuses until --resolve-pins values are committed (here, the
# Dockerfile's MDX_DIAR_V2_PINS default, docs/models/PINS.md).
PINNED: dict[str, str] = {
    "segmentation/pytorch_model.bin": "7ad24338d844fb95985486eb1a464e32d229f6d7a03c9abe60f978bacf3f816e",
    "embedding/pytorch_model.bin": "6f10ff60898a1d185fa22e1d11e0bfa8a92efec811f11bca48cb8cafebefd929",
    "plda/plda.npz": "9b77bcd840692710dd3496f62ecfeed8d8e5f002fd991b785079b244eab7d255",
    "plda/xvec_transform.npz": "325f1ce8e48f7e55e9c8aa47e05d2766b7c48c4b25b8de8dd751e7a4cc5fbe8f",
}

# Public repo metadata: an early "wrong file" signal, NOT a substitute for the pins.
EXPECTED_SIZES: dict[str, int] = {
    "segmentation/pytorch_model.bin": 5_906_507,
    "embedding/pytorch_model.bin": 26_646_242,
    "plda/plda.npz": 133_852,
    "plda/xvec_transform.npz": 134_376,
}
# Small non-LFS files, verified by git blob id (public even for gated repos).
UPSTREAM_GIT_BLOBS: dict[str, str] = {
    "config.yaml": "4022db43960736338378fdb6b5a85cfdae198910",
    "README.md": "8356d6634d7b1074581dd36e2225887ec809326e",
}

# Keys of the upstream config that may differ from the repo-owned copy.
CONFIG_KEYS_ALLOWED_TO_DIFFER = frozenset({"dependencies", "version"})
# Pipeline params that name a sub-model; each must stay `$model/<subfolder>`.
SUBMODEL_PARAMS = ("segmentation", "embedding", "plda")

_REPO_ROOT = Path(__file__).resolve().parents[2]
REPO_CONFIG = _REPO_ROOT / "infra" / "models" / "pyannote-community-1" / "config.yaml"
DEFAULT_TARGET = Path.home() / ".cache" / "mdx-models" / "speaker-diarization-community-1"
LICENSE = "CC-BY-4.0"


# Refusal retrying cannot fix (unpinned, checksum/config mismatch, 401/403);
# the Dockerfile retries only other failures.
EXIT_REFUSED = 3


class PrepareError(Exception):
    """A fail-closed refusal. Its message never carries the token."""


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_blob_sha1(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()


def _read_token(token_file: Path | None) -> str | None:
    """The token from a secret file, or None to let huggingface_hub look it up."""
    if token_file is None:
        return None
    if not token_file.is_file():
        # Optional at mount time; the gated download then 401s below.
        return None
    token = token_file.read_text(encoding="utf-8").strip()
    return token or None


def _download(revision: str, files: list[str], token: str | None) -> Path:
    from huggingface_hub import snapshot_download  # lazy: network path only

    try:
        return Path(snapshot_download(REPO, revision=revision, allow_patterns=files, token=token))
    except Exception as exc:  # hub errors vary by huggingface_hub version
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in (401, 403) or type(exc).__name__ in {
            "GatedRepoError",
            "LocalTokenNotFoundError",
        }:
            raise PrepareError(
                f"{REPO} refused the download (HTTP {status or 'auth'}, {type(exc).__name__}). "
                "It is a gated repo: accept its terms on huggingface.co with the account "
                "whose token you use, then pass the token via HF_TOKEN, "
                "~/.cache/huggingface/token or --token-file."
            ) from None
        raise


def _load_yaml(path: Path) -> dict[str, Any]:
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise PrepareError(f"{path} is not a YAML mapping")
    return data


def _check_local_only(config: dict[str, Any], target: Path) -> None:
    """Every sub-model must be `$model/<subfolder>` and present in ``target``."""
    params = config.get("pipeline", {}).get("params", {})
    for key in SUBMODEL_PARAMS:
        ref = params.get(key)
        if not (isinstance(ref, str) and ref.startswith("$model/")):
            raise PrepareError(
                f"{REPO_CONFIG.name}: pipeline.params.{key} is {ref!r}; it must be "
                "'$model/<subfolder>' or pyannote resolves it on the hub at runtime."
            )
        subfolder = ref.removeprefix("$model/").split("@")[0]
        if "@" in ref or not (target / subfolder).is_dir():
            raise PrepareError(f"pipeline.params.{key}={ref!r} does not name a local subfolder")


def _check_upstream_config(upstream: Path) -> None:
    got = _git_blob_sha1(upstream)
    if got != UPSTREAM_GIT_BLOBS["config.yaml"]:
        raise PrepareError(
            f"upstream config.yaml git blob {got} != pinned {UPSTREAM_GIT_BLOBS['config.yaml']}"
        )
    theirs = {
        k: v for k, v in _load_yaml(upstream).items() if k not in CONFIG_KEYS_ALLOWED_TO_DIFFER
    }
    ours = {
        k: v for k, v in _load_yaml(REPO_CONFIG).items() if k not in CONFIG_KEYS_ALLOWED_TO_DIFFER
    }
    if theirs != ours:
        diff = "\n".join(
            difflib.unified_diff(
                json.dumps(ours, indent=2, sort_keys=True).splitlines(),
                json.dumps(theirs, indent=2, sort_keys=True).splitlines(),
                fromfile=str(REPO_CONFIG.relative_to(_REPO_ROOT)),
                tofile=f"{REPO}@{REVISION[:12]}/config.yaml",
                lineterm="",
            )
        )
        raise PrepareError(
            "the repo-owned config.yaml differs from upstream's at this revision. "
            "Reconcile infra/models/pyannote-community-1/config.yaml (keep every "
            "sub-model as $model/<subfolder>) and re-run:\n" + diff
        )


def resolve_pins(revision: str, token: str | None) -> dict[str, str]:
    """Download at ``revision`` and print the digests to commit. Installs nothing."""
    snapshot = _download(revision, sorted(PINNED), token)
    pins = {name: _sha256(snapshot / name) for name in sorted(PINNED)}
    print(f"# {REPO}@{revision} — paste into PINNED (scripts/models/prepare_pyannote.py):")
    for name, digest in pins.items():
        print(f'    "{name}": "{digest}",')
    return pins


def prepare(
    target: Path,
    *,
    revision: str = REVISION,
    pinned: dict[str, str] | None = None,
    token: str | None = None,
) -> dict[str, str]:
    """Fetch, verify and install; returns the MDX_DIAR_V2_PINS map (weights + config.yaml)."""
    pinned = dict(PINNED if pinned is None else pinned)
    expected_config_sha = pinned.pop("config.yaml", "")
    missing = sorted(set(PINNED) - set(pinned))
    unpinned = sorted(name for name in PINNED if not pinned.get(name))
    if missing or unpinned:
        raise PrepareError(
            f"no SHA-256 pin for {', '.join(missing or unpinned)}. Refusing to install "
            "unverified weights (fail-closed, docs/models/PINS.md). Run with --resolve-pins "
            "using a token that has accepted the model's terms, then commit the digests."
        )
    unknown = sorted(set(pinned) - set(PINNED))
    if unknown:
        raise PrepareError(f"pins for unknown artifacts: {', '.join(unknown)}")

    snapshot = _download(revision, [*sorted(PINNED), *sorted(UPSTREAM_GIT_BLOBS)], token)

    # Verify everything BEFORE writing to the target.
    for name, want in sorted(pinned.items()):
        src = snapshot / name
        if not src.is_file():
            raise PrepareError(f"{name} missing from {REPO}@{revision}")
        if revision == REVISION and src.stat().st_size != EXPECTED_SIZES[name]:
            raise PrepareError(
                f"{name} is {src.stat().st_size} bytes, expected {EXPECTED_SIZES[name]}"
            )
        got = _sha256(src)
        if got != want:
            raise PrepareError(
                f"checksum mismatch for {name}: expected {want}, got {got}. "
                "Refusing to install (fail-closed, docs/models/PINS.md)."
            )
        print(f"  {name}  sha256={got}  OK")
    if revision == REVISION:
        _check_upstream_config(snapshot / "config.yaml")
        readme_blob = _git_blob_sha1(snapshot / "README.md")
        if readme_blob != UPSTREAM_GIT_BLOBS["README.md"]:
            raise PrepareError(f"upstream README.md git blob {readme_blob} is not the pinned one")
        print("  upstream config.yaml + README.md  git blob ids OK")
    else:
        print(f"WARNING: re-pinned revision {revision}: upstream config drift check skipped")

    config_sha = _sha256(REPO_CONFIG)
    if expected_config_sha and expected_config_sha != config_sha:
        raise PrepareError(
            f"config.yaml pin {expected_config_sha} != repo-owned config sha256 {config_sha}. "
            "Update MDX_DIAR_V2_PINS (Dockerfile) together with the config."
        )

    # Assemble in a sibling temp dir and swap: a half-written target must never
    # look like a model dir, and only a previous model dir is ever replaced.
    if target.exists() and any(target.iterdir()) and not (target / "MANIFEST.json").is_file():
        raise PrepareError(f"{target} exists and is not a model dir this script wrote")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    try:
        for name in sorted(pinned):
            (staging / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(snapshot / name, staging / name)
        shutil.copyfile(REPO_CONFIG, staging / "config.yaml")
        shutil.copyfile(snapshot / "README.md", staging / "MODEL_CARD.md")
        _check_local_only(_load_yaml(staging / "config.yaml"), staging)
        pins = {**pinned, "config.yaml": config_sha}
        manifest = {
            "repo": REPO,
            "revision": revision,
            "license": LICENSE,
            "attribution": "pyannote/speaker-diarization-community-1 by pyannoteAI, "
            "CC-BY-4.0 — see MODEL_CARD.md and docs/legal/third-party-notices.md",
            "config": str(REPO_CONFIG.relative_to(_REPO_ROOT)),
            "sha256": pins,
        }
        (staging / "MANIFEST.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        if target.exists():
            shutil.rmtree(target)
        staging.rename(target)
    finally:
        if staging.exists():
            shutil.rmtree(staging)

    print(f"  config.yaml  (repo-owned, sha256={config_sha})")
    print(f"pyannote community-1 model dir ready: {target}")
    print(f"MDX_DIAR_V2_PINS='{json.dumps(pins, sort_keys=True, separators=(',', ':'))}'")
    return pins


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--revision", default=REVISION, help="immutable commit, never a tag")
    parser.add_argument(
        "--pins-json",
        default="",
        help="JSON artifact->sha256 (the MDX_DIAR_V2_PINS shape); default: PINNED above",
    )
    parser.add_argument(
        "--token-file", type=Path, default=None, help="file holding the HF token (build secret)"
    )
    parser.add_argument(
        "--resolve-pins", action="store_true", help="print the digests to pin; install nothing"
    )
    args = parser.parse_args()
    try:
        _run(args)
    except PrepareError as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    return 0


def _run(args: argparse.Namespace) -> None:
    token = _read_token(args.token_file)

    if args.resolve_pins:
        resolve_pins(args.revision, token)
        return
    if args.revision != REVISION:
        print(
            f"WARNING: re-pinning to {args.revision} (default {REVISION}). "
            "Re-baseline the DER gate before shipping a model change."
        )
    pinned: dict[str, str] | None = None
    if args.pins_json.strip():
        raw = json.loads(args.pins_json)
        if not isinstance(raw, dict) or not all(isinstance(v, str) for v in raw.values()):
            raise PrepareError("--pins-json must be a JSON object of artifact -> sha256")
        pinned = raw
    prepare(args.target, revision=args.revision, pinned=pinned, token=token)


if __name__ == "__main__":
    sys.exit(main())
