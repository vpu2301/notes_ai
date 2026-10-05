"""Application-level heartbeat + idle/token-expiry watchdogs.

WS ping/pong is deliberately not relied upon: proxies buffer pong frames and mask TCP failures.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from ..config import settings
from ..protocol import Heartbeat, TokenExpiring, encode_server
from .manager import SessionContext

logger = logging.getLogger(__name__)


async def heartbeat_loop(ctx: SessionContext) -> None:
    """Emit a server heartbeat every ``ws_heartbeat_interval_s``; exits when the WS is gone."""
    interval = settings.ws_heartbeat_interval_s
    while ctx.ws is not None:
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            return
        if ctx.ws is None:
            return
        msg = Heartbeat(server_time_ms=int(time.time() * 1000))
        try:
            await ctx.ws.send_text(encode_server(msg))
        except Exception as exc:  # noqa: BLE001
            logger.info(
                "heartbeat.send_failed",
                extra={
                    "session_id": str(ctx.session_id),
                    "error": str(exc),
                    "error_class": type(exc).__name__,
                },
            )
            return


async def idle_watchdog(
    ctx: SessionContext,
    *,
    on_idle: Callable[[SessionContext], Awaitable[None]],
) -> None:
    """Call ``on_idle`` and stop if no client traffic for ``ws_idle_timeout_s``."""
    timeout = settings.ws_idle_timeout_s
    while ctx.ws is not None:
        elapsed = time.monotonic() - ctx.last_active_at
        if elapsed > timeout:
            logger.info(
                "session.idle_timeout",
                extra={
                    "session_id": str(ctx.session_id),
                    "elapsed_s": round(elapsed, 2),
                    "timeout_s": timeout,
                },
            )
            try:
                await on_idle(ctx)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "idle_watchdog.on_idle_failed",
                    extra={"session_id": str(ctx.session_id), "error": str(exc)},
                )
            return
        try:
            await asyncio.sleep(max(1.0, timeout - elapsed))
        except asyncio.CancelledError:
            return


async def token_expiry_watchdog(ctx: SessionContext) -> None:
    """Emit `token_expiring` in the warn window; ``ctx.token_exp_ts`` is re-read each pass."""
    warn_before = settings.session_token_expiry_warn_seconds
    while ctx.ws is not None and ctx.token_exp_ts is not None:
        now = time.time()
        remaining = ctx.token_exp_ts - now
        if remaining <= 0:
            return
        if remaining <= warn_before:
            try:
                await ctx.ws.send_text(encode_server(TokenExpiring(expires_in_s=int(remaining))))
            except Exception:
                return
            sleep_for = 15.0  # re-emit while in the warn window
        else:
            sleep_for = remaining - warn_before
        try:
            await asyncio.sleep(max(1.0, sleep_for))
        except asyncio.CancelledError:
            return
