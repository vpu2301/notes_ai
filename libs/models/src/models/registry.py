"""Resolve ``(workspace, operation)`` to a backend — at startup, not per call.

Resolution order (spec §D):

1. workspace ``provider`` setting: ``platform`` → routing table;
   ``anthropic`` → the ``anthropic`` backend (BE-S3); ``custom`` → the
   workspace's own endpoint (S7, not yet).
2. workspace **tier** (``standard`` in beta; ``premium`` flips to
   ``hosted_eu`` at gate H0 by config PR).
3. ``env_overrides[env][kind]`` — dev routes chat/asr to the Mac, test to
   recorded cassettes / in-process CPU whisper.
4. The chosen backend must be ``enabled``, allowed in this env, and have
   every ``${VAR}`` resolved — else ``ConfigError``.

``Registry.validate()`` walks every route for the current env so a broken
environment refuses to boot instead of failing jobs.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .config import (
    BACKEND_KIND_FOR,
    KNOWN_ENVS,
    OPERATION_KINDS,
    BackendConfig,
    LoadedConfig,
    OperationKind,
    ProcessorInfo,
    load_config,
    parse_config,
)
from .errors import ConfigError

logger = logging.getLogger("models.registry")

ProviderSetting = Literal["platform", "anthropic", "custom"]
Tier = Literal["standard", "premium"]


@dataclass(frozen=True, slots=True)
class WorkspaceModelSettings:
    provider: ProviderSetting = "platform"
    tier: Tier = "standard"


SettingsSource = Callable[[str], WorkspaceModelSettings]


def _platform_standard(_workspace_id: str) -> WorkspaceModelSettings:
    return WorkspaceModelSettings()


@dataclass(frozen=True, slots=True)
class Capabilities:
    structured_output: str
    context_window: int
    max_concurrency: int
    cold_start_seconds: int
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class ResolvedBackend:
    """What a worker gets back. Log-safe: no token, no URL."""

    name: str
    kind: str
    operation_kind: OperationKind
    model_id: str
    processor: ProcessorInfo | None
    caps: Capabilities
    config: BackendConfig

    def log_fields(self) -> dict[str, Any]:
        return {
            "backend": self.name,
            "model_id": self.model_id,
            "processor": self.processor.name if self.processor else None,
            "processor_region": self.processor.region if self.processor else None,
        }


class Registry:
    def __init__(
        self,
        loaded: LoadedConfig,
        *,
        env: str,
        settings_source: SettingsSource | None = None,
    ) -> None:
        if env not in KNOWN_ENVS:
            raise ConfigError("unknown_env", f"ENV={env!r}; known: {list(KNOWN_ENVS)}")
        self._loaded = loaded
        self._config = loaded.config
        self._env = env
        self._settings_source: SettingsSource = settings_source or _platform_standard

    # ── construction ────────────────────────────────────────────────────
    @classmethod
    def load(
        cls,
        source: str | Path | Mapping[str, Any],
        *,
        env: str,
        environ: Mapping[str, str],
        settings_source: SettingsSource | None = None,
        validate: bool = True,
    ) -> Registry:
        loaded = (
            parse_config(source, environ=environ, source="<dict>")
            if isinstance(source, Mapping)
            else load_config(source, environ=environ)
        )
        registry = cls(loaded, env=env, settings_source=settings_source)
        if validate:
            registry.validate()
        return registry

    @property
    def env(self) -> str:
        return self._env

    @property
    def backend_names(self) -> list[str]:
        return list(self._config.backends)

    # ── validation ──────────────────────────────────────────────────────
    def validate(self) -> None:
        """Every route reachable in this env must resolve. Raises ``ConfigError``."""
        for operation, tiers in self._config.routing.items():
            for tier in tiers:
                resolved = self._resolve_platform(operation, tier)  # type: ignore[arg-type]
                logger.info(
                    "models.route",
                    extra={
                        "env": self._env,
                        "operation": operation,
                        "tier": tier,
                        **resolved.log_fields(),
                    },
                )
        for kind, name in self._config.env_overrides.get(self._env, {}).items():
            self.backend(name, expect_kind=kind)  # type: ignore[arg-type]

    # ── lookups ─────────────────────────────────────────────────────────
    def backend(self, name: str, *, expect_kind: OperationKind | None = None) -> ResolvedBackend:
        """Direct lookup by backend name (eval scripts, ``ASR_BACKEND``). Enforces env rules."""
        cfg = self._config.backends.get(name)
        if cfg is None:
            raise ConfigError(
                "unknown_backend", f"no backend named {name!r}; known: {self.backend_names}"
            )
        if not cfg.enabled:
            raise ConfigError("backend_disabled", f"backend {name!r} is disabled (enabled: false)")
        if self._env not in cfg.enabled_in_envs:
            raise ConfigError(
                "backend_not_allowed_in_env",
                f"backend {name!r} is not allowed in ENV={self._env} (allowed: {cfg.enabled_in_envs})",
            )
        missing = self._loaded.unresolved.get(name)
        if missing:
            raise ConfigError(
                "missing_env", f"backend {name!r} needs environment variable(s) {missing}"
            )
        op_kind = BACKEND_KIND_FOR[cfg.kind]
        if expect_kind is not None and op_kind != expect_kind:
            raise ConfigError(
                "kind_mismatch", f"backend {name!r} is a {op_kind} backend, expected {expect_kind}"
            )
        if cfg.kind == "anthropic":
            raise ConfigError(
                "provider_not_configured", "the anthropic provider is not configured until BE-S3"
            )
        model_id = cfg.model_for(op_kind) or {
            "asr_inproc": "in-process",
            "recorded": "recorded",
        }.get(cfg.kind, "")
        if cfg.kind in ("openai_compat", "asr_http") and not model_id:
            raise ConfigError("invalid_config", f"backend {name!r} declares no models.{op_kind}")
        return ResolvedBackend(
            name=name,
            kind=cfg.kind,
            operation_kind=op_kind,
            model_id=model_id,
            processor=cfg.processor,
            caps=Capabilities(
                structured_output=cfg.structured_output,
                context_window=cfg.context_window,
                max_concurrency=cfg.max_concurrency,
                cold_start_seconds=cfg.cold_start_seconds,
                timeout_seconds=cfg.timeout_seconds,
            ),
            config=cfg,
        )

    def _resolve_platform(self, operation: str, tier: Tier) -> ResolvedBackend:
        kind = OPERATION_KINDS.get(operation)
        if kind is None:
            raise ConfigError(
                "unknown_operation", f"operation {operation!r}; known: {sorted(OPERATION_KINDS)}"
            )
        override = self._config.env_overrides.get(self._env, {}).get(kind)
        if override is not None:
            return self.backend(override, expect_kind=kind)
        tiers = self._config.routing.get(operation)
        if tiers is None:
            raise ConfigError("unknown_operation", f"no routing row for operation {operation!r}")
        name = tiers.get(tier)
        if name is None:
            raise ConfigError("invalid_config", f"routing.{operation} has no tier {tier!r}")
        return self.backend(name, expect_kind=kind)

    def resolve(self, workspace_id: str, operation: str) -> ResolvedBackend:
        settings = self._settings_source(workspace_id)
        if settings.provider == "platform":
            return self._resolve_platform(operation, settings.tier)
        if settings.provider == "anthropic":
            # Decision 12: opt-in processor, acknowledged on the Data page.
            # Landing in BE-S3; `backend()` raises provider_not_configured.
            return self.backend("anthropic", expect_kind=OPERATION_KINDS[operation])
        raise ConfigError(
            "provider_not_configured",
            f"workspace provider {settings.provider!r} (bring-your-own endpoint) lands in DEP-S7",
        )

    def processors_for_env(self) -> list[ProcessorInfo]:
        """Every processor a workspace on this env may be routed to (Data page input)."""
        seen: dict[str, ProcessorInfo] = {}
        for operation, tiers in self._config.routing.items():
            for tier in tiers:
                r = self._resolve_platform(operation, tier)  # type: ignore[arg-type]
                if r.processor is not None:
                    seen[r.processor.name] = r.processor
        return list(seen.values())
