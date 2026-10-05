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
    LOCAL_ONLY_ENVS,
    OPERATION_KINDS,
    BackendConfig,
    LoadedConfig,
    OperationKind,
    OverrideSpec,
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


# Sprint L2 — why the env override landed where it did.
REASON_MISSING_ENV = "missing_env"
REASON_FORCED = "forced"
REASON_PROBE_FAILED = "probe_failed"


@dataclass(frozen=True, slots=True)
class ActiveOverride:
    """What an env override resolved to, and why (Sprint L2).

    ``reason`` is None when the primary is in use; otherwise one of
    ``missing_env`` (the primary's ``${VAR}`` is unset), ``forced`` (the
    service's dev switch named another backend) or ``probe_failed`` (the
    primary did not answer at startup). Log-safe: names only."""

    kind: str
    name: str
    primary: str
    fallback: str | None
    reason: str | None = None

    @property
    def is_fallback(self) -> bool:
        return self.reason is not None

    def log_fields(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "backend": self.name,
            "primary": self.primary,
            "fallback": self.fallback,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class Capabilities:
    structured_output: str
    context_window: int
    max_concurrency: int
    cold_start_seconds: int
    timeout_seconds: float
    small_model: bool = False


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
        forced: Mapping[str, str] | None = None,
    ) -> None:
        if env not in KNOWN_ENVS:
            raise ConfigError("unknown_env", f"ENV={env!r}; known: {list(KNOWN_ENVS)}")
        self._loaded = loaded
        self._config = loaded.config
        self._env = env
        self._settings_source: SettingsSource = settings_source or _platform_standard
        # Sprint L2 — the env overrides as chosen for this process. A
        # `{primary, fallback}` override lands on the fallback only in a
        # local env (dev/test) and only for a reason that is logged.
        self._active: dict[str, ActiveOverride] = {}
        for kind, value in self._config.env_overrides.get(env, {}).items():
            self._active[kind] = self._choose(kind, value, (forced or {}).get(kind))
            if self._active[kind].is_fallback:
                logger.warning("models.override_fallback", extra=self._active[kind].log_fields())

    def _choose(self, kind: str, value: str | OverrideSpec, forced: str | None) -> ActiveOverride:
        if isinstance(value, str):
            if forced and forced != value and self._env in LOCAL_ONLY_ENVS:
                return ActiveOverride(
                    kind, forced, primary=value, fallback=None, reason=REASON_FORCED
                )
            return ActiveOverride(kind, value, primary=value, fallback=None)
        primary, fallback = value.primary, value.fallback
        if forced and forced != primary and self._env in LOCAL_ONLY_ENVS:
            return ActiveOverride(
                kind, forced, primary=primary, fallback=fallback, reason=REASON_FORCED
            )
        cfg = self._config.backends.get(primary)
        unusable = (
            cfg is None
            or not cfg.enabled
            or self._env not in cfg.enabled_in_envs
            or bool(self._loaded.unresolved.get(primary))
        )
        if unusable and fallback and self._env in LOCAL_ONLY_ENVS:
            return ActiveOverride(
                kind, fallback, primary=primary, fallback=fallback, reason=REASON_MISSING_ENV
            )
        # Staging/prod, or no fallback: the primary stands, and `backend()`
        # refuses to boot with `missing_env` exactly as before.
        return ActiveOverride(kind, primary, primary=primary, fallback=fallback)

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
        forced: Mapping[str, str] | None = None,
    ) -> Registry:
        """``forced`` (Sprint L2): ``{kind: backend}`` a dev switch names
        instead of the override's primary — read by the service's config
        (``MDX_DEV_CHAT_BACKEND``), never by this library."""
        loaded = (
            parse_config(source, environ=environ, source="<dict>")
            if isinstance(source, Mapping)
            else load_config(source, environ=environ)
        )
        registry = cls(loaded, env=env, settings_source=settings_source, forced=forced)
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
        for key, active in self._active.items():
            self.backend(active.name, expect_kind=OPERATION_KINDS.get(key, key))  # type: ignore[arg-type]

    def override_for(self, kind: str) -> str | None:
        """The backend this env pins for an operation kind, if any.

        Used by callers that are not routed by tier (the diarizer names
        its backend directly), so dev still lands on the Mac without
        every service repeating the mapping. With a ``{primary, fallback}``
        override this is the one actually chosen for the process. ``kind``
        may also be an operation name (``classify``, ``title``,
        ``entities``) when the env pins those separately.
        """
        active = self._active.get(kind)
        return active.name if active else None

    def active_override(self, kind: str) -> ActiveOverride | None:
        """Sprint L2 — what the env override for ``kind`` (or operation)
        resolved to and why (for the startup log and the AI-settings page)."""
        return self._active.get(kind)

    def active_overrides(self) -> list[ActiveOverride]:
        return list(self._active.values())

    def fall_back(self, kind: str, reason: str = REASON_PROBE_FAILED) -> ActiveOverride:
        """Switch ``kind`` to its fallback for the rest of this process.

        Dev/test only: on staging and prod a processor never changes
        without an admin acknowledging it, so a failed probe there is a
        ``ConfigError`` and the process refuses to boot, as before.
        """
        active = self._active.get(kind)
        if active is None or not active.fallback:
            raise ConfigError(
                "fallback_not_configured", f"no fallback for {kind!r} in ENV={self._env}"
            )
        if self._env not in LOCAL_ONLY_ENVS:
            raise ConfigError(
                "fallback_not_allowed",
                f"{active.primary!r} failed ({reason}) and ENV={self._env} does not fall back",
            )
        if active.name == active.fallback:
            return active
        switched = ActiveOverride(
            kind, active.fallback, primary=active.primary, fallback=active.fallback, reason=reason
        )
        self._active[kind] = switched
        logger.warning("models.override_fallback", extra=switched.log_fields())
        return switched

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
        if cfg.kind in ("openai_compat", "asr_http", "diar_http") and not model_id:
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
                small_model=cfg.small_model,
            ),
            config=cfg,
        )

    def _resolve_platform(self, operation: str, tier: Tier) -> ResolvedBackend:
        kind = OPERATION_KINDS.get(operation)
        if kind is None:
            raise ConfigError(
                "unknown_operation", f"operation {operation!r}; known: {sorted(OPERATION_KINDS)}"
            )
        # An operation-level override wins over the kind-level one (L2:
        # classify/title/entities on the small model, the rest on chat).
        override = self.override_for(operation) or self.override_for(kind)
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

    def processor_routes(self) -> list[tuple[ProcessorInfo, str, str]]:
        """``(processor, operation, tier)`` for every route in this env.

        The Data page has to say what a company DOES with the data —
        "transcription", "notes", "answers" — and a bare processor list
        cannot answer that. Same walk as `processors_for_env`, one level
        less collapsed, so the page and the router still read the same
        object rather than a description of it.
        """
        routes: list[tuple[ProcessorInfo, str, str]] = []
        for operation, tiers in self._config.routing.items():
            for tier in tiers:
                r = self._resolve_platform(operation, tier)  # type: ignore[arg-type]
                if r.processor is not None:
                    routes.append((r.processor, operation, str(tier)))
        return routes
