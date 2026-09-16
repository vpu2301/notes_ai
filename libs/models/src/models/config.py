"""Schema for ``config/models.yaml`` — fails fast on unknown keys.

Environment interpolation: ``${VAR}`` and ``${VAR:-default}`` are resolved
from the mapping the caller passes in (libs never read ``os.environ``;
the service's ``config.py`` does and hands it over). A placeholder with no
value and no default is *tolerated while parsing* and recorded per backend;
the registry turns it into a ``ConfigError(missing_env)`` only if that
backend is enabled in the current environment. That is what lets one file
describe dev, staging and prod without every developer holding an HF token.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator

from .errors import ConfigError

BackendKind = Literal["openai_compat", "asr_http", "asr_inproc", "anthropic", "recorded"]
StructuredMode = Literal["json_schema", "json_object", "guided_json", "probe", "none"]
OperationKind = Literal["chat", "asr", "embed"]

# operation -> kind. Adding an operation is a code change here and a routing
# row in models.yaml; the registry refuses operations it does not know.
OPERATION_KINDS: dict[str, OperationKind] = {
    "understand": "chat",
    "summarize": "chat",
    "asr": "asr",
    "embed": "embed",
}
BACKEND_KIND_FOR: dict[BackendKind, OperationKind] = {
    "openai_compat": "chat",
    "anthropic": "chat",
    "recorded": "chat",
    "asr_http": "asr",
    "asr_inproc": "asr",
}
KNOWN_ENVS = ("dev", "test", "staging", "prod")
LOCAL_ONLY_ENVS = frozenset({"dev", "test"})

_PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


class ProcessorInfo(BaseModel):
    """Who processes the data — this is what the workspace Data page lists (decision 12)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    region: str


class BackendConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: BackendKind
    enabled: bool = True
    enabled_in_envs: list[str] = Field(default_factory=lambda: list(KNOWN_ENVS))
    base_url: str | None = None
    # "none" or "bearer:<token>". Held as a SecretStr so a dumped config or a
    # traceback never shows the token.
    auth: SecretStr = SecretStr("none")
    models: dict[str, str] = Field(default_factory=dict)  # {"chat": ..., "asr": ...}
    structured_output: StructuredMode = "json_schema"
    context_window: int = Field(default=32768, ge=1024)
    max_concurrency: int = Field(default=1, ge=1)
    cold_start_seconds: int = Field(default=0, ge=0)
    timeout_seconds: float = Field(default=120.0, gt=0)
    processor: ProcessorInfo | None = None
    cassette_dir: str | None = None  # kind=recorded only
    # Extra OpenAI-API fields merged into every chat request, e.g.
    # {reasoning_effort: none} to keep a reasoning model (Qwen3) from
    # spending the token budget on <think>. Configuration, not code.
    request_overrides: dict[str, Any] = Field(default_factory=dict)

    @field_validator("enabled_in_envs")
    @classmethod
    def _known_envs(cls, envs: list[str]) -> list[str]:
        bad = [e for e in envs if e not in KNOWN_ENVS]
        if bad:
            raise ValueError(f"unknown env(s) {bad}; known: {list(KNOWN_ENVS)}")
        return envs

    @field_validator("auth")
    @classmethod
    def _auth_shape(cls, auth: SecretStr) -> SecretStr:
        raw = auth.get_secret_value()
        if raw != "none" and not raw.startswith("bearer:"):
            raise ValueError("auth must be 'none' or 'bearer:<token>'")
        return auth

    def bearer_token(self) -> str | None:
        raw = self.auth.get_secret_value()
        if raw.startswith("bearer:"):
            token = raw[len("bearer:") :]
            return token or None
        return None

    def model_for(self, kind: OperationKind) -> str | None:
        return self.models.get(kind)


class ModelsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1]
    backends: dict[str, BackendConfig]
    routing: dict[str, dict[str, str]]  # operation -> tier -> backend name
    env_overrides: dict[str, dict[str, str]] = Field(default_factory=dict)  # env -> kind -> backend

    @field_validator("routing")
    @classmethod
    def _known_operations(cls, routing: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
        for op in routing:
            if op not in OPERATION_KINDS:
                raise ValueError(f"unknown operation {op!r}; known: {sorted(OPERATION_KINDS)}")
        return routing

    @field_validator("env_overrides")
    @classmethod
    def _known_override_keys(
        cls, overrides: dict[str, dict[str, str]]
    ) -> dict[str, dict[str, str]]:
        for env, by_kind in overrides.items():
            if env not in KNOWN_ENVS:
                raise ValueError(f"env_overrides: unknown env {env!r}")
            for kind in by_kind:
                if kind not in ("chat", "asr", "embed"):
                    raise ValueError(f"env_overrides.{env}: unknown kind {kind!r}")
        return overrides


class LoadedConfig(BaseModel):
    """Parsed config plus the placeholders that could not be resolved, per backend."""

    model_config = ConfigDict(frozen=True)

    config: ModelsConfig
    unresolved: dict[str, list[str]]  # backend name -> env var names
    source: str


def _interpolate(value: Any, environ: Mapping[str, str], missing: list[str]) -> Any:
    if isinstance(value, str):

        def sub(match: re.Match[str]) -> str:
            name, default = match.group(1), match.group(2)
            if name in environ and environ[name] != "":
                return environ[name]
            if default is not None:
                return default
            missing.append(name)
            return ""

        return _PLACEHOLDER.sub(sub, value)
    if isinstance(value, dict):
        return {k: _interpolate(v, environ, missing) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate(v, environ, missing) for v in value]
    return value


def parse_config(
    raw: Mapping[str, Any], *, environ: Mapping[str, str], source: str
) -> LoadedConfig:
    data = dict(raw)
    unresolved: dict[str, list[str]] = {}
    backends = data.get("backends")
    if isinstance(backends, dict):
        resolved_backends: dict[str, Any] = {}
        for name, spec in backends.items():
            missing: list[str] = []
            resolved_backends[name] = _interpolate(spec, environ, missing)
            if missing:
                unresolved[name] = sorted(set(missing))
        data["backends"] = resolved_backends
    top_missing: list[str] = []
    for key in ("routing", "env_overrides"):
        if key in data:
            data[key] = _interpolate(data[key], environ, top_missing)
    if top_missing:
        raise ConfigError(
            "missing_env", f"{source}: routing references unset {sorted(set(top_missing))}"
        )
    try:
        config = ModelsConfig.model_validate(data)
    except ValidationError as exc:
        # Pydantic's message names the offending key path; that is the
        # whole point of extra="forbid".
        raise ConfigError(
            "invalid_config",
            f"{source}: {exc.errors()[0]['msg']} at {'.'.join(str(p) for p in exc.errors()[0]['loc'])}",
        ) from exc
    _check_static_invariants(config, source)
    return LoadedConfig(config=config, unresolved=unresolved, source=source)


def _check_static_invariants(config: ModelsConfig, source: str) -> None:
    """Invariants that hold regardless of which env we are in."""
    for name, backend in config.backends.items():
        # A processor in region "local" (the founder's Mac) can never be
        # selected on staging/prod, not even by a config typo: the file
        # itself is rejected if it says so.
        if backend.processor is not None and backend.processor.region == "local":
            illegal = [e for e in backend.enabled_in_envs if e not in LOCAL_ONLY_ENVS]
            if illegal:
                raise ConfigError(
                    "backend_not_allowed_in_env",
                    f"{source}: backend {name!r} is a local processor and may not list {illegal}",
                )
        # A missing env var leaves base_url == "" — tolerated here, the
        # registry decides whether this backend matters in this env. A
        # *missing key* is a config bug regardless.
        if backend.kind in ("openai_compat", "asr_http") and backend.base_url is None:
            raise ConfigError(
                "invalid_config", f"{source}: backend {name!r} ({backend.kind}) needs base_url"
            )
        if backend.kind == "recorded" and not backend.cassette_dir:
            raise ConfigError(
                "invalid_config", f"{source}: backend {name!r} (recorded) needs cassette_dir"
            )
        if backend.kind == "anthropic" and backend.processor is None:
            raise ConfigError(
                "invalid_config",
                f"{source}: backend {name!r} (anthropic) must declare its processor",
            )
    for op, tiers in config.routing.items():
        for tier, target in tiers.items():
            if target not in config.backends:
                raise ConfigError(
                    "unknown_backend",
                    f"{source}: routing.{op}.{tier} -> {target!r} is not a backend",
                )
            expected = OPERATION_KINDS[op]
            actual = BACKEND_KIND_FOR[config.backends[target].kind]
            if actual != expected:
                raise ConfigError(
                    "kind_mismatch",
                    f"{source}: routing.{op}.{tier} -> {target!r} is a {actual} backend, operation needs {expected}",
                )
    for env, by_kind in config.env_overrides.items():
        for kind, target in by_kind.items():
            if target not in config.backends:
                raise ConfigError(
                    "unknown_backend",
                    f"{source}: env_overrides.{env}.{kind} -> {target!r} is not a backend",
                )
            if BACKEND_KIND_FOR[config.backends[target].kind] != kind:
                raise ConfigError(
                    "kind_mismatch",
                    f"{source}: env_overrides.{env}.{kind} -> {target!r} is not a {kind} backend",
                )


def load_config(path: str | Path, *, environ: Mapping[str, str]) -> LoadedConfig:
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError("config_not_found", f"cannot read {p}: {exc}") from exc
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError("invalid_config", f"{p}: not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError("invalid_config", f"{p}: top level must be a mapping")
    return parse_config(raw, environ=environ, source=str(p))
