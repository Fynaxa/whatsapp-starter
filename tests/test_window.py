"""The 24 hour window: the boundary is the whole point, so it is tested at the second."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from whatsapp_starter import SendMode, WindowTracker, closes_at, is_open, required_mode

from .conftest import CUSTOMER, NOW


def test_window_closes_exactly_24_hours_after_the_inbound_message() -> None:
    assert closes_at(NOW) == NOW + timedelta(hours=24)


def test_open_one_second_before_the_boundary() -> None:
    assert is_open(NOW, NOW + timedelta(hours=24, seconds=-1)) is True


def test_closed_exactly_at_the_boundary() -> None:
    assert is_open(NOW, NOW + timedelta(hours=24)) is False


def test_closed_after_the_boundary() -> None:
    assert is_open(NOW, NOW + timedelta(hours=24, seconds=1)) is False


def test_without_an_inbound_message_the_window_never_opened() -> None:
    assert is_open(None, NOW) is False
    assert required_mode(None, NOW) is SendMode.TEMPLATE


@pytest.mark.parametrize(
    ("offset", "expected"),
    [
        (timedelta(0), SendMode.FREEFORM),
        (timedelta(hours=23, minutes=59, seconds=59), SendMode.FREEFORM),
        (timedelta(hours=24), SendMode.TEMPLATE),
        (timedelta(days=3), SendMode.TEMPLATE),
    ],
)
def test_required_mode_switches_at_the_boundary(offset: timedelta, expected: SendMode) -> None:
    assert required_mode(NOW, NOW + offset) is expected


def test_a_different_timezone_describes_the_same_instant() -> None:
    berlin = NOW.astimezone(timezone(timedelta(hours=2)))
    assert is_open(berlin, NOW + timedelta(hours=23)) is True


@pytest.mark.parametrize("bad", [datetime(2026, 9, 19, 12, 0), datetime(2026, 9, 20, 12, 0)])
def test_naive_timestamps_are_refused(bad: datetime) -> None:
    with pytest.raises(ValueError, match="timezone aware"):
        is_open(bad, NOW)


def test_tracker_state_survives_a_restart(tmp_path) -> None:
    path = tmp_path / "windows.json"
    WindowTracker(path).record_inbound(CUSTOMER, NOW)
    assert WindowTracker(path).is_open(CUSTOMER, NOW + timedelta(hours=1)) is True
    assert WindowTracker(path).is_open(CUSTOMER, NOW + timedelta(hours=25)) is False


def test_an_out_of_order_webhook_never_moves_the_boundary_backwards(windows) -> None:
    windows.record_inbound(CUSTOMER, NOW)
    windows.record_inbound(CUSTOMER, NOW - timedelta(hours=5))
    assert windows.last_inbound(CUSTOMER) == NOW


def test_contacts_are_tracked_independently(windows) -> None:
    windows.record_inbound(CUSTOMER, NOW)
    assert windows.is_open("4915199999999", NOW) is False


def test_corrupt_state_file_does_not_crash_the_receiver(tmp_path) -> None:
    path = tmp_path / "windows.json"
    path.write_text("{ not json", encoding="utf-8")
    assert WindowTracker(path).last_inbound(CUSTOMER) is None
