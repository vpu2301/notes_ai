"""What code wrote a note (Task 4 step 1): the commit the image was built from, a digest
of the engine's source as installed, the prompt version and the flags the run used.
Numbers, hashes and names only. The eval report writer refuses a stale build with it."""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any


def _package_dir(name: str) -> Path | None:
    try:
        module = __import__(name)
    except ImportError:
        return None
    file = getattr(module, "__file__", None)
    return Path(file).resolve().parent if file else None


@lru_cache(maxsize=1)
def code_digest() -> str:
    """sha256 over the engine's installed source: every ``.py`` of ``note_service`` and
    ``models``, by relative path, in one order. Identical in the container and in the
    working tree exactly when the image was built from this tree."""
    digest = hashlib.sha256()
    for name in ("note_service", "models"):
        root = _package_dir(name)
        if root is None:
            continue
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            digest.update(f"{name}/{path.relative_to(root).as_posix()}\n".encode())
            digest.update(path.read_bytes())
            digest.update(b"\n")
    return digest.hexdigest()[:16]


def stamp(
    *,
    build_sha: str | None,
    prompt_version: str,
    effective_version: str | None,
    flags: dict[str, Any],
) -> dict[str, Any]:
    """``stats.build``: ``git_sha`` (the image's ``BUILD_SHA``, or the tree's), ``code_digest``,
    ``prompt_version`` (the package's), ``effective_version`` (the prompt set this run sent),
    and the run's flags."""
    return {
        "git_sha": build_sha or None,
        "code_digest": code_digest(),
        "prompt_version": prompt_version,
        "effective_version": effective_version,
        "flags": {k: bool(v) for k, v in flags.items()},
    }
