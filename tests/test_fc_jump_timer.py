"""Fleet carrier jump timer (BGS-Tally-compatible phases)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fc_jump_timer import (
    CANCEL_COOLDOWN_SECONDS,
    FleetCarrierJumpPhase,
    FleetCarrierJumpTracker,
    format_countdown,
    parse_journal_datetime,
    seconds_until,
)

UTC = timezone.utc


def test_parse_journal_datetime_zulu() -> None:
    dt = parse_journal_datetime("2020-04-20T09:45:00Z")
    assert dt is not None
    assert dt.year == 2020 and dt.month == 4 and dt.day == 20


def test_format_countdown() -> None:
    assert format_countdown(125) == "02:05"
    # BGS-Tally _td_str uses chained divmod (MM:SS only, not true H:MM:SS).
    assert format_countdown(3661) == "61:01"


def test_jump_request_cancel_and_cooldown() -> None:
    tracker = FleetCarrierJumpTracker()
    departure = datetime.now(tz=UTC) + timedelta(minutes=15)
    entry = {
        "CarrierID": 3700005632,
        "SystemName": "Paesui Xena",
        "Body": "Paesui Xena A",
        "DepartureTime": departure.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    assert tracker.handle_jump_requested(entry) is True
    snap = tracker._carriers[3700005632]
    assert snap.phase == FleetCarrierJumpPhase.JUMPING
    assert snap.jump_destination == "Paesui Xena"

    assert tracker.handle_jump_cancelled({"CarrierID": 3700005632}) is True
    assert snap.phase == FleetCarrierJumpPhase.COOLDOWN
    assert seconds_until(snap.timer) <= CANCEL_COOLDOWN_SECONDS

    lines = tracker.overlay_footer_lines()
    assert lines and "cooldown" in lines[0].lower()


def test_overlay_departure_subphases() -> None:
    tracker = FleetCarrierJumpTracker()
    departure = datetime.now(tz=UTC) + timedelta(minutes=15)
    tracker.handle_jump_requested(
        {
            "CarrierID": 1,
            "SystemName": "Test Sys",
            "Body": "Test Body",
            "DepartureTime": departure.isoformat().replace("+00:00", "Z"),
        }
    )
    snap = tracker._carriers[1]
    lines = tracker.overlay_footer_lines()
    assert any("Departure" in line for line in lines)
    assert any("Jump initiation" in line for line in lines)

    snap.timer = datetime.now(tz=UTC) + timedelta(seconds=300)
    lines_mid = tracker.overlay_footer_lines()
    assert any("lockdown" in line.lower() for line in lines_mid)

    snap.timer = datetime.now(tz=UTC) + timedelta(seconds=100)
    lines_late = tracker.overlay_footer_lines()
    assert any("locked down" in line.lower() for line in lines_late)
