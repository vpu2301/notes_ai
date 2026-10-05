"""Redis stream and channel names shared by producers and the consumer (drift would be silent)."""

from __future__ import annotations

from typing import Final
from uuid import UUID

# The event bus (ADR-0029): one stream, one consumer group.
NOTIFICATIONS_STREAM: Final = "mdx:notifications:events"
NOTIFICATIONS_DLQ_STREAM: Final = "mdx:notifications:events:dlq"
NOTIFICATIONS_GROUP: Final = "notification-workers"

# Cross-worker WebSocket fan-out (ADR-0030): every worker subscribes per user and forwards to its local sockets.
_USER_CHANNEL_PREFIX: Final = "mdx:notify:user:"


def user_channel(user_id: UUID | str) -> str:
    """Pub/sub channel carrying fan-out frames for one recipient."""
    return f"{_USER_CHANNEL_PREFIX}{user_id}"
