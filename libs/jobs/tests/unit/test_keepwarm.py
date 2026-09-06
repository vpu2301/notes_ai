from __future__ import annotations

from datetime import UTC, datetime

from jobs import KeepWarmSchedule


def test_off_by_default() -> None:
    assert KeepWarmSchedule().is_active(datetime(2026, 9, 15, 8, 0, tzinfo=UTC)) is False


def test_window_is_weekday_office_hours_in_cet() -> None:
    s = KeepWarmSchedule(enabled=True)
    assert s.is_active(datetime(2026, 9, 15, 6, 30, tzinfo=UTC)) is True  # Tue 08:30 CEST
    assert s.is_active(datetime(2026, 9, 15, 5, 30, tzinfo=UTC)) is False  # Tue 07:30 CEST
    assert s.is_active(datetime(2026, 9, 15, 17, 30, tzinfo=UTC)) is False  # Tue 19:30 CEST
    assert s.is_active(datetime(2026, 9, 19, 10, 0, tzinfo=UTC)) is False  # Saturday
