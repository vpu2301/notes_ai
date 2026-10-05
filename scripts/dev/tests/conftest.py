"""Load the hyphenated gate scripts by file path and expose them as pytest fixtures."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

_DEV_DIR = Path(__file__).resolve().parent.parent


def _load(filename: str) -> ModuleType:
    path = _DEV_DIR / filename
    spec = importlib.util.spec_from_file_location(path.stem.replace("-", "_"), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def env_gate() -> ModuleType:
    return _load("check-no-os-environ.py")


@pytest.fixture(scope="session")
def asyncpg_gate() -> ModuleType:
    return _load("check-no-direct-asyncpg.py")
