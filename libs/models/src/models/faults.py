"""Dev-only fault injection (telemetry sprint 5, scenario S3): the next ``n`` chat requests
fail as an HTTP 503 would, inside the provider's own retry loop, so retries can be observed end
to end. Nothing arms it unless a service does so from its development settings."""

from __future__ import annotations

import threading

_lock = threading.Lock()
_remaining = 0


def arm_chat_failures(n: int) -> None:
    global _remaining
    with _lock:
        _remaining = max(0, n)


def take_chat_failure() -> bool:
    """``True`` (and one fewer left) when the next chat request must fail."""
    global _remaining
    with _lock:
        if _remaining <= 0:
            return False
        _remaining -= 1
        return True
