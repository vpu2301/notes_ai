"""Auth-service entry point.

Day-5 surface area:
- ``/healthz``, ``/readyz``
- ``/audit/events``  (paginated read; requires auditor or tenant_admin role)
- ``/audit/verify``  (chain verification; requires auditor or tenant_admin)

Days 6+ add login/refresh/logout/me/admin routers. The lifespan, DI, and
problem-detail handling established here are unchanged in later days.
"""

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

    # FND-0: the mode is logged on every boot. During the `dual` period a
    # deployment's mode is the single most load-bearing fact about it —
    # which issuers are live, whether signup is open, what a rollback
    # costs — and "which mode is staging actually running?" is not a
    # question anyone should have to answer from a Helm diff.
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
    # Account-mail outbox drain. Only when the feature is on AND a
    # provider was built — a worker polling an outbox nothing writes to
    # is pure noise, and `testing` keeps it out of unit-test event loops.
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
        # Reset links would be minted and queued but never sent — the
        # user waits for mail that cannot arrive. Loud, because nothing
        # else in the system would surface it.
        logger.error(
            "auth.password.reset_enabled_but_no_mail_worker",
            extra={
                "background_jobs": settings.background_jobs_enabled,
                "has_provider": state.email_provider is not None,
            },
        )

    # ── IDX-B3: scheduled maintenance (ADR-0041) ────────────────────
    # One task per scheduled job, each surviving its own failures inside
    # `run_job_once`. No advisory lock: every job is idempotent, so a
    # second replica running the same sweep is redundant rather than
    # harmful — the ADR's stated trade-off.
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
    """The zero-arg callable ``run_periodic`` wants, bound to the pool.

    Maintenance runs on ``tenant_writer``: the identity tables grant
    ``app_role`` nothing, which is the point.
    """

    async def _run() -> Any:
        return await run_job(job, state.tenant_writer_pool)

    return _run


def _maint_audit(state: Any, job: Any) -> Any:
    """ADR-0041's per-run audit row, under the platform tenant.

    Best-effort — the scheduler already treats `on_complete` as such, and
    a sweep that ran must not be reported as failed because the hash
    chain was briefly unavailable.
    """

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
    # IDX-B3 E. Added first so they wrap outermost: the headers land on
    # every response, including the ones the origin check refuses.
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(BodyLimitMiddleware)
    # CORS for the SPA (sprint A3). allow_credentials=True is required so the
    # browser sends/stores the HttpOnly `mdx_rt` cookie on cross-origin XHR;
    # that forbids a wildcard origin, so origins are an explicit allow-list.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        # IDX-B3 E. `X-Client-Type` is IDX-A2's and decides where the
        # refresh token travels; a browser that sends it on a
        # cross-origin request triggers a preflight, and a preflight that
        # is not allowed the header fails the whole call. Leaving it out
        # meant the SPA could declare itself only by not declaring
        # itself. `X-Request-Id` is the correlation header the fleet
        # already propagates.
        allow_headers=["Authorization", "Content-Type", "X-Client-Type", "X-Request-Id"],
        expose_headers=["WWW-Authenticate", "X-Request-Id", "Retry-After"],
        max_age=600,
    )
    app.include_router(health.router)
    # FND-1: the JWKS endpoint is mounted in EVERY mode. Before BE-2 it
    # answers `{"keys": []}` — the fleet is configured to trust this
    # issuer first and it starts signing second, so the URL has to exist
    # (and be verifiable with curl) before there is a key behind it.
    app.include_router(wellknown.router)
    if settings.idp_mode == "native":
        # IDX-A2: browser state changes on /auth must come from an allowed
        # origin; native apps declare themselves (X-Client-Type) and send no
        # Origin. Native mode only — today's Mac/iOS apps and the smoke
        # scripts send neither header, so this is a cut-over precondition
        # (M1/I1), not something to switch on under Keycloak. `dual` does
        # not get it either, for the same reason: BE-2's smoke is password
        # login working unchanged on web, macOS and iOS.
        app.add_middleware(OriginCheckMiddleware, allowed_origins=settings.cors_origins_list)
        # IDX-A2's session half, carried by IDX-M1: `/auth/refresh` and
        # `/auth/logout` against `auth_sessions`. Mounted before anything
        # else that could claim those paths, and `login.router` — which
        # proxies both to Keycloak — is not mounted in this mode at all.
        app.include_router(session_native.router)
        # IDX-A3: self-serve signup and login by emailed one-time code.
        app.include_router(email_code.router)
        # IDX-A5: second factors, sessions, email change, deletion.
        # `mfa_native` and the sprint-16 `mfa` router both claim
        # /auth/mfa/verify, with different meanings — exactly one is
        # mounted, so the path never means two things in one process.
        app.include_router(mfa_native.router)
        app.include_router(account.router)
        # IDX-B1b: tokens for principals that are not people. Native only
        # — while Keycloak is the issuer it is also the token endpoint for
        # devices and services, and two of those would be one too many.
        app.include_router(oauth.router)
        app.include_router(credentials.router)
    elif settings.idp_mode == "dual":
        # BE-2 / ADR-0047. Both session stores are live, so the mounting
        # ORDER is the routing: Starlette matches the first route whose
        # path fits, and three paths are claimed by both routers.
        #
        #   /auth/refresh, /auth/logout — session_native wins, and hands
        #       JWT-shaped tokens straight to login.py's handler
        #       (`_belongs_to_keycloak`). One path, one entry point, two
        #       stores behind it.
        #   /auth/sessions              — password.py (Keycloak) wins,
        #       because during `dual` most sessions still are Keycloak's
        #       and a list that showed only the native ones would read as
        #       "you are signed in nowhere else".
        #   /auth/mfa/verify            — mfa.py (Keycloak) wins;
        #       mfa_native is NOT mounted. Native MFA enrolment is IDX-A5's
        #       and out of this batch: during `dual` a person with a second
        #       factor authenticates with their password, which is where
        #       their factor lives (BE-3's `use_password` rule).
        app.include_router(session_native.router)
        # IDX-A3: the headline of this batch — self-serve signup by
        # emailed code, for people Keycloak has never heard of.
        app.include_router(email_code.router)
        # `/auth/login` and the Keycloak password surface, untouched.
        # Everything an existing user does today keeps working; that is
        # the whole reason `dual` exists rather than a cut-over.
        app.include_router(mfa.router)
        app.include_router(login.router)
        app.include_router(password.router)
        # BE-0 signup lives beside BE-3's `/auth/email/*` during `dual`.
        # Two ways in, deliberately: password signup is what web, macOS
        # and iOS can already use, and the email-code path is what
        # replaces it once the clients ship support.
        app.include_router(signup.router)
        # IDX-A5's account surface, for `PATCH /auth/me` — the welcome
        # step writes the browser's timezone through it (BE-3 §4). Mounted
        # AFTER password.router so the `/auth/sessions` collision above
        # resolves to Keycloak's list.
        app.include_router(account.router)
    else:
        app.include_router(mfa.router)
        # `/auth/login`, `/auth/refresh`, `/auth/logout` — every one of
        # them a Keycloak proxy. Native mode serves the last two from
        # `session_native` and still owes the first (IDX-A4).
        app.include_router(login.router)
        # BE-0: self-serve signup against Keycloak. The router itself is
        # always mounted in this mode; whether it answers is decided by
        # `state.onboarding_service` being wired (MDX_SIGNUP_ENABLED plus
        # a mail relay), so a deployment with signup off 404s rather than
        # advertising a switched-off feature in its OpenAPI.
        app.include_router(signup.router)
        # Every endpoint in the password router reaches Keycloak
        # (password_grant, set_password, logout_user, list_sessions), so
        # in native mode it could only return 502s — and its
        # `GET /auth/sessions` would shadow the native one. IDX-A4 brings
        # the native password surface; until then, native deployments
        # simply do not have this one.
        app.include_router(password.router)
    # Sprint 19: the shared page's CTA lands on /join, which posts here.
    # Every mode — it depends on no identity provider at all.
    app.include_router(leads.router)
    app.include_router(me.router)
    app.include_router(admin.router)
    app.include_router(tenants.router)
    app.include_router(audit.router)
    FastAPIInstrumentor.instrument_app(app)
    return app


app = create_app()
