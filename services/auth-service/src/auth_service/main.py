"""Auth-service entry point: lifespan, middleware and router mounting per idp_mode."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from audit import Severity
from observability import bootstrap, register_exception_handlers, run_periodic

from .config import settings
from .delivery import worker as mail_worker
from .deps import install_state
from .main_deps import auth_issuers, build_state, teardown_state
from .maintenance import JOBS, run_job
from .middleware.origin_check import OriginCheckMiddleware
from .middleware.security_headers import BodyLimitMiddleware, SecurityHeadersMiddleware
from .routers import (
    account,
    admin,
    audit,
    credentials,
    email_code,
    health,
    leads,
    login,
    me,
    mfa,
    mfa_native,
    oauth,
    password,
    session_native,
    signup,
    tenants,
    wellknown,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    bootstrap(
        settings.service_name,
        otlp_endpoint=settings.otel_exporter_otlp_endpoint,
        log_level=settings.log_level,
        deployment_environment=settings.environment,
        package_name="auth-service",
        disable_otel=settings.testing or settings.otel_sdk_disabled,
    )

    state = await build_state()
    app.state.svc = state
    install_state(state)

    logger.info(
        "auth-service starting",
        extra={
            "service": settings.service_name,
            "env": settings.environment,
            "issuer": settings.auth_issuer,
            "idp_mode": settings.idp_mode,
            "trusted_issuers": [config.issuer for config in auth_issuers()],
        },
    )
    # Outbox drain only when the feature is on AND a provider was built.
    mail_task: asyncio.Task[None] | None = None
    if (
        settings.password_reset_enabled
        and settings.background_jobs_enabled
        and not settings.testing
        and state.email_provider is not None
    ):
        mail_task = asyncio.create_task(
            mail_worker.run_forever(
                app_pool=state.app_pool,
                provider=state.email_provider,
                reply_to=settings.auth_email_reply_to,
                interval_s=settings.mail_delivery_interval_s,
                batch_size=settings.mail_delivery_batch_size,
                max_attempts=settings.mail_delivery_max_attempts,
                backoff_base_s=settings.mail_delivery_backoff_base_s,
            )
        )
    elif settings.password_reset_enabled and not settings.testing:
        # Reset links would be queued but never sent.
        logger.error(
            "auth.password.reset_enabled_but_no_mail_worker",
            extra={
                "background_jobs": settings.background_jobs_enabled,
                "has_provider": state.email_provider is not None,
            },
        )

    # Scheduled maintenance (ADR-0041): no advisory lock, every job is idempotent.
    maint_tasks: list[asyncio.Task[None]] = []
    if settings.background_jobs_enabled and not settings.testing:
        for job in JOBS:
            if not job.scheduled or job.interval_seconds is None:
                continue
            maint_tasks.append(
                asyncio.create_task(
                    run_periodic(
                        job_name=f"auth.{job.name}",
                        interval_seconds=job.interval_seconds,
                        fn=_maint_runner(state, job),
                        on_complete=_maint_audit(state, job),
                    )
                )
            )
        logger.info("auth.maint.scheduled", extra={"jobs": len(maint_tasks)})

    try:
        yield
    finally:
        for task in (*maint_tasks, mail_task):
            if task is not None:
                task.cancel()
        for task in (*maint_tasks, mail_task):
            if task is not None:
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        await teardown_state(state)
        logger.info("auth-service shutting down")


def _maint_runner(state: Any, job: Any) -> Any:
    """Zero-arg callable for ``run_periodic``; runs on ``tenant_writer`` (app_role has no grants)."""

    async def _run() -> Any:
        return await run_job(job, state.tenant_writer_pool)

    return _run


def _maint_audit(state: Any, job: Any) -> Any:
    """Best-effort per-run audit row under the platform tenant (ADR-0041)."""

    async def _on_complete(outcome: str, detail: Any, duration: float) -> None:
        payload: dict[str, Any] = {
            "job": job.name,
            "outcome": outcome,
            "duration_s": round(duration, 3),
        }
        if hasattr(detail, "as_payload"):
            payload.update(detail.as_payload())
        elif detail is not None:
            payload["detail"] = str(detail)[:500]
        try:
            await state.audit_writer.write_event(
                tenant_id=UUID(settings.auth_platform_tenant_id),
                kind=("scheduler.job.completed" if outcome == "ok" else "scheduler.job.failed"),
                actor_sub=None,
                target_kind="tenant",
                target_id=None,
                payload=payload,
                severity=Severity.INFO if outcome == "ok" else Severity.WARN,
            )
        except Exception:  # noqa: BLE001
            logger.warning("auth.maint.audit_failed", extra={"job": job.name})

    return _on_complete


def create_app() -> FastAPI:
    app = FastAPI(
        title="Auth Service",
        description="Identity, tenant, and audit-read service.",
        version="0.2.0",
        openapi_version="3.1.0",
        lifespan=_lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )
    register_exception_handlers(app)
    # Added first so they wrap outermost (headers land on refused responses too).
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(BodyLimitMiddleware)
    # allow_credentials=True (HttpOnly refresh cookie) forbids a wildcard origin.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        # `X-Client-Type` decides where the refresh token travels; it must pass preflight.
        allow_headers=["Authorization", "Content-Type", "X-Client-Type", "X-Request-Id"],
        expose_headers=["WWW-Authenticate", "X-Request-Id", "Retry-After"],
        max_age=600,
    )
    app.include_router(health.router)
    # JWKS is mounted in every mode (`{"keys": []}` until there is a key).
    app.include_router(wellknown.router)
    if settings.idp_mode == "native":
        # Origin check is native-only: Mac/iOS apps and smoke scripts send no Origin
        # and no X-Client-Type under Keycloak.
        app.add_middleware(OriginCheckMiddleware, allowed_origins=settings.cors_origins_list)
        # Mounted before anything else that could claim /auth/refresh or /auth/logout.
        app.include_router(session_native.router)
        app.include_router(email_code.router)
        # `mfa_native` and `mfa` both claim /auth/mfa/verify; exactly one is mounted.
        app.include_router(mfa_native.router)
        app.include_router(account.router)
        # Native only: under Keycloak it is the token endpoint for devices/services.
        app.include_router(oauth.router)
        app.include_router(credentials.router)
    elif settings.idp_mode == "dual":
        # ADR-0047: both session stores are live, so mounting ORDER is the routing
        # (first matching route wins):
        #   /auth/refresh, /auth/logout — session_native wins and hands JWT-shaped
        #       tokens to login.py (`_belongs_to_keycloak`).
        #   /auth/sessions — password.py (Keycloak) wins.
        #   /auth/mfa/verify — mfa.py (Keycloak) wins; mfa_native is NOT mounted.
        app.include_router(session_native.router)
        app.include_router(email_code.router)
        app.include_router(mfa.router)
        app.include_router(login.router)
        app.include_router(password.router)
        app.include_router(signup.router)
        # After password.router so /auth/sessions resolves to Keycloak's list.
        app.include_router(account.router)
    else:
        app.include_router(mfa.router)
        app.include_router(login.router)
        # Always mounted here; it 404s unless `state.onboarding_service` is wired.
        app.include_router(signup.router)
        # Keycloak-only: in native mode it could only 502 and would shadow /auth/sessions.
        app.include_router(password.router)
    # Every mode: /join depends on no identity provider.
    app.include_router(leads.router)
    app.include_router(me.router)
    app.include_router(admin.router)
    app.include_router(tenants.router)
    app.include_router(audit.router)
    FastAPIInstrumentor.instrument_app(app)
    return app


app = create_app()
