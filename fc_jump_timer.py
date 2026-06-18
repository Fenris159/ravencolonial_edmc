"""
Fleet carrier jump countdown tracking (BGS-Tally-compatible timing).

Journal: CarrierJumpRequest, CarrierJumpCancelled, CarrierLocation.
Timing mirrors BGS-Tally: 10m jump lock-in, 3m20s pad lockdown, 5m post-jump cooldown
(rounded to the minute), 60s cooldown after a cancelled jump.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Mapping, Optional

logger = logging.getLogger(__name__)

UTC = timezone.utc

JUMP_LOCK_SECONDS = 600
PAD_LOCKDOWN_SECONDS = 200
POST_JUMP_COOLDOWN_SECONDS = 300
CANCEL_COOLDOWN_SECONDS = 60


class FleetCarrierJumpPhase(str, Enum):
    IDLE = "Idle"
    JUMPING = "Jumping"
    COOLDOWN = "Cooldown"


def parse_journal_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        raw = str(value).strip()
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def seconds_until(target: Optional[datetime], *, now: Optional[datetime] = None) -> int:
    if target is None:
        return 0
    ref = now or datetime.now(tz=UTC)
    if target.tzinfo is None:
        target = target.replace(tzinfo=UTC)
    return int((target - ref).total_seconds())


def format_countdown(seconds: int) -> str:
    """HH:MM:SS or MM:SS style countdown (BGS-Tally ``_td_str``)."""
    seconds = max(0, int(seconds))
    parts: List[str] = []
    unit = 60
    remaining = seconds
    while unit > 0:
        chunk, remaining = divmod(remaining, unit)
        unit = int(unit / 60)
        if chunk > 0 or unit < 3600:
            parts.append(f"{chunk:02d}")
    return ":".join(parts) if parts else "00"


@dataclass
class CarrierJumpSnapshot:
    carrier_id: int
    market_id: Optional[int] = None
    callsign: str = ""
    jump_destination: str = ""
    jump_destination_body: Optional[str] = None
    departure_scheduled: Optional[datetime] = None
    phase: FleetCarrierJumpPhase = FleetCarrierJumpPhase.IDLE
    timer: Optional[datetime] = None


class FleetCarrierJumpTracker:
    """Per-carrier jump state for overlay countdown rows."""

    def __init__(
        self,
        *,
        schedule_after: Optional[Callable[[int, Callable[[], None]], Optional[str]]] = None,
        on_state_changed: Optional[Callable[[], None]] = None,
    ) -> None:
        self._schedule_after = schedule_after
        self._on_state_changed = on_state_changed
        self._carriers: Dict[int, CarrierJumpSnapshot] = {}
        self._after_ids: set[str] = set()

    def is_active(self) -> bool:
        return any(s.phase != FleetCarrierJumpPhase.IDLE for s in self._carriers.values())

    def register_carrier_stats(self, entry: Mapping[str, Any]) -> None:
        try:
            carrier_id = entry.get("CarrierID")
            if carrier_id is None:
                return
            cid = int(carrier_id)
        except (TypeError, ValueError):
            return
        snap = self._carriers.setdefault(cid, CarrierJumpSnapshot(carrier_id=cid))
        market_raw = entry.get("MarketID")
        if market_raw is not None:
            try:
                snap.market_id = int(market_raw)
            except (TypeError, ValueError):
                pass
        callsign = str(entry.get("Callsign") or "").strip().upper()
        if callsign:
            snap.callsign = callsign

    def note_linked_market_id(self, market_id: int, *, callsign: str = "") -> None:
        """Associate a Ravencolonial-linked FC market id with any known carrier snapshot."""
        mid = int(market_id)
        for snap in self._carriers.values():
            if snap.market_id == mid:
                if callsign and not snap.callsign:
                    snap.callsign = callsign.upper()
                return
        # CarrierID often equals MarketID for fleet carriers; seed a placeholder entry.
        placeholder = self._carriers.setdefault(mid, CarrierJumpSnapshot(carrier_id=mid, market_id=mid))
        if callsign:
            placeholder.callsign = callsign.upper()

    def handle_jump_requested(self, entry: Mapping[str, Any]) -> bool:
        try:
            cid = int(entry.get("CarrierID"))
        except (TypeError, ValueError):
            return False
        departure = parse_journal_datetime(entry.get("DepartureTime"))
        if departure is None:
            return False

        snap = self._carriers.setdefault(cid, CarrierJumpSnapshot(carrier_id=cid))
        snap.market_id = snap.market_id or cid
        snap.jump_destination = str(entry.get("SystemName") or "").strip()
        body = entry.get("Body")
        snap.jump_destination_body = str(body).strip() if body else None
        snap.departure_scheduled = departure
        snap.phase = FleetCarrierJumpPhase.JUMPING
        snap.timer = departure

        rem = max(0, seconds_until(departure))
        self._schedule_once(rem * 1000, lambda: self._jump_complete(cid))
        logger.info(
            "FC jump scheduled carrier=%s destination=%s in %ss",
            cid,
            snap.jump_destination or "?",
            rem,
        )
        self._notify_changed()
        return True

    def handle_jump_cancelled(self, entry: Mapping[str, Any]) -> bool:
        try:
            cid = int(entry.get("CarrierID"))
        except (TypeError, ValueError):
            return False
        snap = self._carriers.get(cid)
        if snap is None:
            return False

        snap.jump_destination = ""
        snap.jump_destination_body = None
        snap.departure_scheduled = None

        if snap.phase == FleetCarrierJumpPhase.JUMPING:
            snap.phase = FleetCarrierJumpPhase.COOLDOWN
            snap.timer = datetime.now(tz=UTC) + timedelta(seconds=CANCEL_COOLDOWN_SECONDS)
            self._schedule_once(CANCEL_COOLDOWN_SECONDS * 1000, lambda: self._cooldown_complete(cid))
            logger.info("FC jump cancelled carrier=%s (60s cooldown)", cid)
            self._notify_changed()
            return True

        snap.phase = FleetCarrierJumpPhase.IDLE
        snap.timer = None
        self._notify_changed()
        return True

    def handle_carrier_location(self, entry: Mapping[str, Any]) -> bool:
        try:
            cid = int(entry.get("CarrierID"))
        except (TypeError, ValueError):
            return False
        snap = self._carriers.get(cid)
        if snap is None:
            return False

        scheduled = snap.departure_scheduled
        if snap.phase != FleetCarrierJumpPhase.JUMPING or scheduled is None:
            return False
        if seconds_until(scheduled) > 0:
            return False

        self._jump_complete(cid)
        if snap.jump_destination:
            snap.jump_destination = str(entry.get("StarSystem") or snap.jump_destination).strip()
            body = entry.get("Body")
            if body:
                snap.jump_destination_body = str(body).strip()
        snap.departure_scheduled = None
        self._notify_changed()
        return True

    def overlay_footer_lines(
        self,
        *,
        prefer_market_id: Optional[int] = None,
        line_formatter: Optional[Callable[..., str]] = None,
    ) -> List[str]:
        snap = self._pick_display_snapshot(prefer_market_id)
        if snap is None or snap.phase == FleetCarrierJumpPhase.IDLE or snap.timer is None:
            return []

        delta = seconds_until(snap.timer)
        if delta <= 0 and snap.phase == FleetCarrierJumpPhase.IDLE:
            return []

        fmt = line_formatter or _default_overlay_lines
        return fmt(snap, delta)

    def _pick_display_snapshot(self, prefer_market_id: Optional[int]) -> Optional[CarrierJumpSnapshot]:
        active = [s for s in self._carriers.values() if s.phase != FleetCarrierJumpPhase.IDLE]
        if not active:
            return None
        if prefer_market_id is not None:
            want = int(prefer_market_id)
            for snap in active:
                if snap.market_id == want or snap.carrier_id == want:
                    return snap
        return active[0]

    def _jump_complete(self, carrier_id: int) -> None:
        snap = self._carriers.get(carrier_id)
        if snap is None or snap.phase != FleetCarrierJumpPhase.JUMPING:
            return

        departure = snap.departure_scheduled or snap.timer
        if departure is None:
            snap.phase = FleetCarrierJumpPhase.IDLE
            snap.timer = None
            self._notify_changed()
            return

        snap.phase = FleetCarrierJumpPhase.COOLDOWN
        if departure.second >= 30:
            cooldown_end = departure + timedelta(minutes=1, seconds=POST_JUMP_COOLDOWN_SECONDS - departure.second)
        else:
            cooldown_end = departure + timedelta(seconds=POST_JUMP_COOLDOWN_SECONDS - departure.second)
        snap.timer = cooldown_end
        snap.departure_scheduled = None
        snap.jump_destination = ""
        snap.jump_destination_body = None

        rem = max(0, seconds_until(cooldown_end))
        self._schedule_once(rem * 1000, lambda: self._cooldown_complete(carrier_id))
        logger.info("FC jump complete carrier=%s cooldown %ss", carrier_id, rem)
        self._notify_changed()

    def _cooldown_complete(self, carrier_id: int) -> None:
        snap = self._carriers.get(carrier_id)
        if snap is None or snap.phase != FleetCarrierJumpPhase.COOLDOWN:
            return
        snap.phase = FleetCarrierJumpPhase.IDLE
        snap.timer = None
        logger.info("FC jump cooldown finished carrier=%s", carrier_id)
        self._notify_changed()

    def _schedule_once(self, delay_ms: int, callback: Callable[[], None]) -> None:
        if not self._schedule_after:
            return
        after_id = self._schedule_after(max(0, int(delay_ms)), callback)
        if after_id:
            self._after_ids.add(after_id)

    def _notify_changed(self) -> None:
        if self._on_state_changed:
            try:
                self._on_state_changed()
            except Exception:
                logger.debug("FC jump on_state_changed failed", exc_info=True)


def _default_overlay_lines(snap: CarrierJumpSnapshot, delta: int) -> List[str]:
    """English fallback when overlay l10n formatter is not injected."""
    cd = format_countdown(delta)
    if snap.phase == FleetCarrierJumpPhase.COOLDOWN and delta > 0:
        return [f"> Jump cooldown {cd}"]

    if snap.phase != FleetCarrierJumpPhase.JUMPING or delta <= 0:
        return []

    dest = (snap.jump_destination_body or snap.jump_destination or "Unknown").strip()
    lines = [f"> Departure to {dest} in {cd}"]
    if delta < PAD_LOCKDOWN_SECONDS:
        lines.append("Landing pads locked down")
    elif delta < JUMP_LOCK_SECONDS:
        lines.append(f"Landing pad lockdown in {format_countdown(delta - PAD_LOCKDOWN_SECONDS)}")
    else:
        lines.append(f"Jump initiation in {format_countdown(delta - JUMP_LOCK_SECONDS)}")
    return lines
