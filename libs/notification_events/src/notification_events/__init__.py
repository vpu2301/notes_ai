"""Notification event contract shared by producers and the consumer (leaf package).

Renaming or reordering a field is BREAKING: add a v2 module and run both through a deprecation window.
"""

from .enums import (
    Category,
    Channel,
    EmailMode,
    Severity,
)
from .envelope import (
    EVENT_SCHEMA_VERSION,
    NotificationEvent,
)
from .publisher import build_event, publish_event
from .streams import (
    NOTIFICATIONS_DLQ_STREAM,
    NOTIFICATIONS_GROUP,
    NOTIFICATIONS_STREAM,
    user_channel,
)

__all__ = [
    "EVENT_SCHEMA_VERSION",
    "NOTIFICATIONS_DLQ_STREAM",
    "NOTIFICATIONS_GROUP",
    "NOTIFICATIONS_STREAM",
    "Category",
    "Channel",
    "EmailMode",
    "NotificationEvent",
    "Severity",
    "build_event",
    "publish_event",
    "user_channel",
]
