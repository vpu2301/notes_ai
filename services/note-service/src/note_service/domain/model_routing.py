"""One registry per process, probed once at startup (Sprint L2).

The API and the worker used to each build a `Registry` lazily and never
ask it anything until the first job. With a hosted default and a local
fallback the decision has to be made — and said — when the process starts:

    models.route      backend=mistral_eu  primary=mistral_eu  reason=None
    models.override_fallback  backend=dev_mac  primary=mistral_eu  reason=probe_failed

`load_registry()` reads `config/models.yaml` with the workspace settings
source and the dev switch (`MDX_DEV_CHAT_BACKEND`); `probe_chat()` sends
one liveness call to the active chat backend with a short timeout and, in
dev only, moves to the fallback for the rest of the process when the
primary does not answer. Staging and prod never switch processors on
their own: a failed probe there is a `ConfigError` and the process refuses
to boot, exactly as before.

`describe()` is what the AI-settings page shows under "Notes are written
by": backend, processor, and the fallback and reason when one is active.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from models import ActiveOverride, ConfigError, Registry, build_chat_provider

from ..config import settings

logger = logging.getLogger(__name__)

PROBE_TIMEOUT_S = 5.0
# The operations a generation makes chat calls for, in the order the AI
# settings page lists them.
CHAT_OPERATIONS = ("summarize", "understand", "classify", "title", "entities")


def forced_overrides() -> dict[str, str]:
    """`MDX_DEV_CHAT_BACKEND` names the backend for every chat operation.
    Dev only: the registry ignores it outside dev/test."""
    name = (settings.dev_chat_backend or "").strip()
    if not name:
        return {}
    return {"chat": name, "classify": name, "title": name, "entities": name}


def load_registry(settings_source: Any = None, *, validate: bool = False) -> Registry:
    """The registry this process routes with. `validate=False` for the same
    reason `ask.py` and the worker used it: an unrelated (ASR) misconfiguration
    must not stop notes being written."""
    return Registry.load(
        settings.models_config,
        env=settings.registry_env(),
        environ=settings.registry_environ(),
        validate=validate,
        settings_source=(settings_source.cached if settings_source is not None else None),
        forced=forced_overrides(),
    )


async def probe_chat(
    registry: Registry, *, timeout_s: float = PROBE_TIMEOUT_S
) -> ActiveOverride | None:
    """Probe the active chat backend once. Returns what is active afterwards.

    dev/test: a primary that does not answer within `timeout_s` is replaced
    by the fallback for this process (`models.override_fallback
    reason=probe_failed`). A fallback that does not answer is logged and
    kept — the first job reports the model error, as today.
    staging/prod: a failed probe raises `ConfigError` (refuse to boot).
    """
    active = registry.active_override("chat")
    if active is None:
        return None
    ok = await _answers(registry, active.name, timeout_s)
    if ok:
        logger.info("models.route", extra={"operation": "chat", **active.log_fields()})
        return active
    if active.is_fallback or not active.fallback:
        logger.warning("models.probe_failed", extra={**active.log_fields(), "switched": False})
        return active
    if registry.env not in ("dev", "test"):
        raise ConfigError(
            "probe_failed",
            f"chat backend {active.name!r} did not answer the startup probe in ENV={registry.env}",
        )
    switched = registry.fall_back("chat")
    # The short operations follow: a laptop without the API names its notes locally.
    for operation in ("classify", "title", "entities"):
        op = registry.active_override(operation)
        if op is not None and op.fallback and not op.is_fallback:
            registry.fall_back(operation)
    logger.info("models.route", extra={"operation": "chat", **switched.log_fields()})
    return switched


async def _answers(registry: Registry, backend: str, timeout_s: float) -> bool:
    provider = None
    try:
        provider = build_chat_provider(registry.backend(backend, expect_kind="chat"))
        await asyncio.wait_for(provider.probe(), timeout=timeout_s)
        return True
    except TimeoutError:
        logger.warning("models.probe_timeout", extra={"backend": backend, "timeout_s": timeout_s})
        return False
    except Exception as exc:  # noqa: BLE001 — the probe's whole job is to absorb this
        logger.warning(
            "models.probe_error", extra={"backend": backend, "error": type(exc).__name__}
        )
        return False
    finally:
        if provider is not None:
            try:
                await provider.aclose()
            except Exception:  # noqa: BLE001
                logger.debug("models.probe_close_failed", exc_info=True)


def describe(registry: Registry | None) -> dict[str, Any] | None:
    """What the AI-settings page shows: who writes the notes right now.

    ``{"backend", "model_id", "processor", "region", "primary",
    "fallback", "reason", "small": {...}}`` — names only, no URL, no key.
    """
    if registry is None:
        return None
    active = registry.active_override("chat")
    if active is None:
        return None

    def _one(name: str, over: ActiveOverride) -> dict[str, Any]:
        try:
            resolved = registry.backend(name, expect_kind="chat")
            processor, region, model_id = (
                (resolved.processor.name if resolved.processor else None),
                (resolved.processor.region if resolved.processor else None),
                resolved.model_id,
            )
        except ConfigError:
            processor = region = model_id = None
        return {
            "backend": name,
            "model_id": model_id,
            "processor": processor,
            "region": region,
            "primary": over.primary,
            "fallback": over.fallback,
            "reason": over.reason,
        }

    out = _one(active.name, active)
    small = registry.active_override("classify")
    if small is not None:
        out["small"] = _one(small.name, small)
    return out
