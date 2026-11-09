"""Attribute ship inventory changes without counting journal movements twice."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Optional

from .api.client import normalize_commodity_key


def cargo_counts(cargo: Mapping[str, Any]) -> dict[str, int]:
    """Normalize a ship snapshot, retaining an observed empty hold."""
    result: dict[str, int] = {}
    for raw_key, raw_value in cargo.items():
        key = normalize_commodity_key(str(raw_key).lower())
        try:
            amount = int(raw_value)
        except (TypeError, ValueError):
            continue
        if key and amount > 0:
            result[key] = result.get(key, 0) + amount
    return result


def _positive_count(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def read_market_cargo_snapshot(entry: Mapping[str, Any], journal_dir: Optional[str]) -> Optional[dict[str, int]]:
    """Read a complete main-ship inventory belonging to this trade, never a past or future event."""
    if not journal_dir or not entry.get("timestamp"):
        return None
    try:
        data = json.loads((Path(journal_dir) / "Cargo.json").read_text(encoding="utf-8"))
        if not isinstance(data, Mapping):
            return None
        if (data.get("timestamp") != entry["timestamp"] or data.get("Vessel") != "Ship"
                or data.get("event") != "Cargo"):
            return None
        return _complete_file_inventory(data)
    except (OSError, UnicodeError, ValueError, TypeError, KeyError):
        return None


def _complete_file_inventory(data: Mapping[str, Any]) -> Optional[dict[str, int]]:
    inventory = data.get("Inventory")
    if not isinstance(inventory, list) or not _nonnegative_integer(data.get("Count")):
        return None
    cargo: dict[str, int] = {}
    for item in inventory:
        if not isinstance(item, Mapping):
            return None
        name = item.get("Name")
        amount = item.get("Count")
        if not isinstance(name, str) or not _nonnegative_integer(amount):
            return None
        key = normalize_commodity_key(name)
        if not key:
            return None
        cargo[key] = cargo.get(key, 0) + amount
    if sum(cargo.values()) != data["Count"]:
        return None
    return cargo_counts(cargo)


def _nonnegative_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _event_time(value: Any) -> Optional[float]:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.timestamp() if parsed.tzinfo is not None else None
    except ValueError:
        return None


def _add_signed(target: dict[str, int], changes: Mapping[str, int], sign: int = 1) -> None:
    for key, amount in changes.items():
        value = target.get(key, 0) + sign * amount
        if value:
            target[key] = value
        else:
            target.pop(key, None)


@dataclass
class InventoryWindow:
    """Retain one physical interval until its attribution can be proved safely."""

    before: dict[str, int]
    cargo: Optional[dict[str, int]]
    time: Optional[float]
    known: dict[str, int]
    reason: str


@dataclass
class CargoDecision:
    """Checkpoint this movement and its exact evidence together before dispatch."""

    ship: Optional[dict[str, int]] = None
    delta: dict[str, int] = field(default_factory=dict)
    evidence: Optional[dict[str, Any]] = None
    generation: int = 0


class CarrierShipCargoTracker:
    """Own ship freshness and one conservative bank-inference window."""

    def __init__(self) -> None:
        self.in_main_ship = True
        self._inventory_observed = False
        self.reset()

    def reset(self, cargo: Optional[Mapping[str, Any]] = None) -> None:
        """Start a new dock/vehicle context without replaying the previous context's evidence."""
        self._before = cargo_counts(cargo) if cargo is not None else None
        self._ship = None if self._before is None else dict(self._before)
        self._point_time: Optional[float] = None
        self._point_complete = False
        self._ship_time: Optional[float] = None
        self._origin_time: Optional[float] = None
        self._origin_inventory: Optional[dict[str, int]] = None
        self._origin_known = cargo is not None
        self._known: dict[str, int] = {}
        self._known_time: Optional[float] = None
        self._pending: Optional[InventoryWindow] = None
        self._manual_cutoff: Optional[float] = None
        self._manual = False
        self._journal_time: Optional[float] = None
        self._generation = getattr(self, '_generation', 0) + 1

    def context_generation(self) -> int:
        """Identify the dock lifetime owning the returned checkpoint."""
        return self._generation

    def is_main_ship(self, state: Optional[Mapping[str, Any]] = None) -> bool:
        """Exclude on-foot, SRV and fighter state from mothership cargo."""
        state = state or {}
        ship = str(state.get('ShipType') or '').lower()
        return self.in_main_ship and not (
            'buggy' in ship or 'fighter' in ship or state.get('OnFoot') or state.get('IsSRV')
        )

    def observe_dashboard(self, entry: Mapping[str, Any]) -> None:
        """Reset context when Elite's vehicle flags leave the main ship."""
        flags = int(entry.get('Flags', 0))
        if flags & ((1 << 24) | (1 << 25) | (1 << 26)):
            self.in_main_ship = bool(flags & (1 << 24)) and not bool(int(entry.get('Flags2', 0)) & 1)
            if not self.in_main_ship:
                self.reset()

    def observe_journal(self, entry: Mapping[str, Any], state: Mapping[str, Any], market_id: Any) -> None:
        """Consume context changes only; process owns every movement exactly once."""
        event = entry.get('event')
        if event in {'StartUp', 'LoadGame', 'ShipyardSwap', 'Died', 'Resurrect'}:
            self._inventory_observed = False
        if event in {'LaunchSRV', 'LaunchFighter', 'Disembark'}:
            self.in_main_ship = False
        elif event in {'DockSRV', 'DockFighter', 'LoadGame'}:
            self.in_main_ship = True
        elif event == 'Embark':
            self.in_main_ship = not bool(entry.get('SRV'))
        cargo = state.get('Cargo')
        known = isinstance(cargo, Mapping) and (bool(cargo_counts(cargo)) or self._inventory_observed)
        if (event in {'Docked', 'Location', 'StartUp', 'LoadGame', 'Undocked', 'Died', 'Resurrect',
                      'ShipyardSwap', 'LaunchSRV', 'LaunchFighter', 'Disembark', 'DockSRV', 'DockFighter', 'Embark'}
                or not self.is_main_ship(state)
                or event in {'MarketBuy', 'MarketSell'} and str(entry.get('MarketID')) != str(market_id)):
            self.reset(cargo if known and self.is_main_ship(state) else None)

    def cover_manifest(self) -> None:
        """Capture attribution coverage when a full correction is reserved, rather than acknowledged."""
        cutoff = max((point for point in (self._ship_time, self._journal_time) if point is not None), default=None)
        ship = None if self._ship is None else dict(self._ship)
        point = None if self._ship is None or self._pending is not None else dict(self._ship)
        if point is not None:
            _add_signed(point, self._known)
            point = cargo_counts(point)
        self.reset(point)
        self._ship = point if point is not None else ship
        self._manual = True
        self._manual_cutoff = cutoff
        self._point_time = self._ship_time = cutoff

    @staticmethod
    def _ship_changes(entry: Mapping[str, Any]) -> dict[str, int]:
        event = entry.get('event')
        if event == 'CargoTransfer':
            return CarrierShipCargoTracker._transfer_changes(entry)
        if event in {'BuyDrones', 'SellDrones'}:
            count = _positive_count(entry.get('Count'))
            return {'drones': count if event == 'BuyDrones' else -count} if count else {}
        signs = {'MarketBuy': 1, 'MarketSell': -1, 'EjectCargo': -1, 'CollectCargo': 1, 'MiningRefined': 1}
        key = normalize_commodity_key(str(entry.get('Type') or '').lower())
        count = _positive_count(entry.get('Count', 1))
        return {key: signs[event] * count} if event in signs and key and count else {}

    @staticmethod
    def _transfer_changes(entry: Mapping[str, Any]) -> dict[str, int]:
        result: dict[str, int] = {}
        for transfer in entry.get('Transfers') or []:
            if not isinstance(transfer, Mapping):
                continue
            key = normalize_commodity_key(str(transfer.get('Type') or '').lower())
            direction = str(transfer.get('Direction') or '').lower()
            count = _positive_count(transfer.get('Count'))
            if key and count and direction in {'toship', 'tocarrier'}:
                _add_signed(result, {key: count if direction == 'toship' else -count})
        return result

    def process(
        self, entry: Mapping[str, Any], state: Mapping[str, Any], cargo: Optional[Mapping[str, int]],
        *, complete: bool, carrier: bool, bank: bool, available: Optional[Mapping[str, int]],
    ) -> CargoDecision:
        """Return the ship observation, signed delivery and evidence for one ordered journal callback."""
        if entry.get('event') == 'Cargo' and str(entry.get('Vessel') or 'Ship').lower() != 'ship':
            self.reset()
            return self._decision()
        if not self.is_main_ship(state):
            return self._decision()
        event = entry.get('event')
        stamp = _event_time(entry.get('timestamp'))
        changes = self._ship_changes(entry)
        trade = event in {'MarketBuy', 'MarketSell', 'CargoTransfer'}
        explicit = {key: -value for key, value in changes.items()} if trade and carrier else {}
        if trade and not changes:
            return self._decision()
        if not self._ordered(event, stamp):
            return self._decision()
        observed = self._observe_inventory(entry, cargo, stamp, complete)
        if not bank:
            return self._nonbank_event(entry, state, observed, stamp, explicit)
        decision = self._bank_event(entry, state, observed if complete else None, stamp, explicit, available)
        if observed is not None:
            decision.ship = observed
        return decision

    def _observe_inventory(
        self, entry: Mapping[str, Any], cargo: Optional[Mapping[str, int]], stamp: Optional[float], complete: bool,
    ) -> Optional[dict[str, int]]:
        valid_view = (entry.get('event') == 'Cargo' and bool(cargo)
                      and sum(cargo_counts(cargo).values()) == _positive_count(entry.get('Count')))
        return self._ship_observation(cargo, stamp) if cargo is not None and (complete or valid_view) else None

    def _nonbank_event(
        self, entry: Mapping[str, Any], state: Mapping[str, Any], observed: Optional[dict[str, int]],
        stamp: Optional[float], explicit: dict[str, int],
    ) -> CargoDecision:
        if observed is None and self._ship_changes(entry):
            observed = self._partial_ship(entry, state, stamp)
        if observed is not None:
            self._ship_observation(observed, stamp)
            if self._pending is not None:
                # Leave persisted uncertainty opaque until resync; do not bind it to the new point.
                self._generation += 1
            self._accept(observed, stamp)
            self._origin_known = True
        return self._decision(observed, explicit)

    def _ordered(self, event: Any, stamp: Optional[float]) -> bool:
        if (self._manual and stamp is not None and self._manual_cutoff is not None
                and stamp < self._manual_cutoff):
            return False
        if event != 'Cargo' and stamp is not None:
            if self._journal_time is not None and stamp < self._journal_time:
                self._hold(None, self._point_time, 'journal_order')
                return False
            self._journal_time = stamp
        return True

    def _bank_event(
        self, entry: Mapping[str, Any], state: Mapping[str, Any], observed: Optional[dict[str, int]],
        stamp: Optional[float], explicit: dict[str, int], available: Optional[Mapping[str, int]],
    ) -> CargoDecision:
        if self._pending is not None and self._pending.reason == 'journal_order':
            return self._decision(observed)
        changes = self._ship_changes(entry)
        trade = entry.get('event') in {'MarketBuy', 'MarketSell', 'CargoTransfer'}
        if self._manual_covers(stamp):
            if changes:
                self._hold(None, self._manual_cutoff, 'manual_order')
            return self._decision(observed)
        if entry.get('event') == 'Cargo':
            delta = self._snapshot(observed, stamp, available) if observed is not None else {}
            return self._decision(observed, delta)
        historical = (not self._origin_known and self._origin_time is not None
                      and stamp is not None and stamp <= self._origin_time)
        if historical:
            return self._historical(changes, observed, stamp, explicit, available)
        if self._before is None:
            return self._known_without_bank_baseline(entry, state, observed, stamp, explicit)
        if not trade:
            return self._ship_only(changes, observed, stamp, available)
        return self._trade(entry, state, observed, stamp, explicit, available)

    def _known_without_bank_baseline(
        self, entry: Mapping[str, Any], state: Mapping[str, Any], observed: Optional[dict[str, int]],
        stamp: Optional[float], explicit: dict[str, int],
    ) -> CargoDecision:
        if observed is not None and self._pending is None:
            self._seed_baseline(observed, stamp)
        elif self._pending is not None:
            self._record_known(self._ship_changes(entry), stamp)
        if observed is None and explicit:
            observed = self._partial_ship(entry, state, stamp)
            if observed is not None:
                self._ship_observation(observed, stamp)
        return self._decision(observed, explicit)

    def _manual_covers(self, stamp: Optional[float]) -> bool:
        return self._manual and (stamp is None or self._manual_cutoff is not None and stamp <= self._manual_cutoff)

    def _historical(
        self, changes: Mapping[str, int], observed: Optional[dict[str, int]], stamp: Optional[float],
        explicit: dict[str, int], available: Optional[Mapping[str, int]],
    ) -> CargoDecision:
        if stamp != self._origin_time or self._origin_inventory is None:
            return self._decision(observed, explicit)
        inferred = {key: self._origin_inventory.get(key, 0) - (self._before or {}).get(key, 0)
                    for key in changes}
        delta = dict(explicit)
        _add_signed(delta, inferred, -1)
        for key in changes:
            self._origin_inventory[key] = (self._before or {}).get(key, 0)
        self._hold(None, self._point_time, 'origin')
        return self._decision(observed, delta if self._funded(delta, available) else {})

    def _ship_only(
        self, changes: Mapping[str, int], observed: Optional[dict[str, int]],
        stamp: Optional[float], available: Optional[Mapping[str, int]],
    ) -> CargoDecision:
        if (observed is None and self._pending is None and stamp is not None
                and self._point_time is not None and stamp < self._point_time
                and self._funded(changes, available)):
            return self._decision(None, dict(changes))
        if observed is not None and self._pending is None:
            _add_signed(self._known, changes)
        else:
            self._record_known(changes, stamp, defer_same=observed is None)
        delta = self._snapshot(observed, stamp, available) if observed is not None else {}
        return self._decision(observed, delta)

    def _trade(
        self, entry: Mapping[str, Any], state: Mapping[str, Any], observed: Optional[dict[str, int]],
        stamp: Optional[float], explicit: dict[str, int], available: Optional[Mapping[str, int]],
    ) -> CargoDecision:
        if self._pending is not None and (observed is None or self._pending.reason in {'origin', 'manual_order'}):
            return self._trade_in_window(entry, observed, stamp, explicit)
        if observed is not None:
            return self._decision(observed, self._snapshot(observed, stamp, available))
        if stamp is not None and self._point_time is not None and stamp <= self._point_time:
            if stamp == self._point_time:
                if self._after_reported_partial(stamp):
                    self._record_known(self._ship_changes(entry), stamp)
                    self._hold(None, stamp, 'ambiguous')
                    return self._decision(None, explicit)
                self._hold(None, stamp, 'ambiguous')
            return self._decision()
        observed = self._partial_ship(entry, state, stamp)
        if observed is not None and self._movement(observed, self._known) == explicit:
            self._accept(observed, stamp, complete=False)
            self._ship_observation(observed, stamp)
            return self._decision(observed, explicit)
        self._record_known(self._ship_changes(entry), stamp)
        self._hold(None, stamp, 'ambiguous')
        return self._decision(None, explicit)

    def _trade_in_window(
        self, entry: Mapping[str, Any], observed: Optional[dict[str, int]], stamp: Optional[float],
        explicit: dict[str, int],
    ) -> CargoDecision:
        pending = self._pending
        if pending.reason == 'funds' or self._after_reported_partial(stamp) or (
                stamp is not None and pending.time is not None and stamp > pending.time):
            self._record_known(self._ship_changes(entry), stamp)
            return self._decision(observed, explicit)
        self._defer_placement()
        return self._decision(observed)

    def _after_reported_partial(self, stamp: Optional[float]) -> bool:
        return stamp is not None and stamp == self._point_time and not self._point_complete

    def _defer_placement(self) -> None:
        """Require fresh inventory without weakening a barrier that needs authoritative resync."""
        if self._pending is not None and self._pending.reason == 'funds':
            self._pending.reason = 'ambiguous'

    def _ship_observation(self, cargo: Mapping[str, int], stamp: Optional[float]) -> Optional[dict[str, int]]:
        if stamp is not None and self._ship_time is not None and stamp < self._ship_time:
            return None
        self._ship = cargo_counts(cargo)
        self._ship_time = stamp
        self._inventory_observed = True
        return dict(self._ship)

    def _partial_ship(
        self, entry: Mapping[str, Any], state: Mapping[str, Any], stamp: Optional[float],
    ) -> Optional[dict[str, int]]:
        if (self._ship is None or self._pending is not None
                or stamp is not None and self._ship_time is not None and stamp <= self._ship_time):
            return None
        raw = state.get('Cargo')
        observed = cargo_counts(raw) if isinstance(raw, Mapping) else dict(self._ship)
        if not isinstance(raw, Mapping):
            _add_signed(observed, self._ship_changes(entry))
            observed = cargo_counts(observed)
        return observed

    def _record_known(self, changes: Mapping[str, int], stamp: Optional[float], *, defer_same: bool = True) -> None:
        if self._pending is not None and (stamp is None or self._pending.time is None or stamp <= self._pending.time):
            _add_signed(self._pending.known, changes)
            if defer_same and stamp == self._pending.time:
                self._defer_placement()
        else:
            _add_signed(self._known, changes)
            self._known_time = max((time for time in (self._known_time, stamp) if time is not None), default=None)
            if (self._pending is None and stamp is not None
                    and self._point_time is not None and stamp <= self._point_time):
                self._hold(None, self._point_time, 'ambiguous')

    def _snapshot(
        self, cargo: Mapping[str, int], stamp: Optional[float], available: Optional[Mapping[str, int]],
    ) -> dict[str, int]:
        if self._known_time is not None and (stamp is None or stamp < self._known_time):
            return {}
        pending = self._pending
        if pending is not None:
            if pending.reason in {'journal_order', 'manual_order', 'origin'}:
                return {}
            if pending.reason == 'ambiguous' and not (
                    stamp is not None and (pending.time is None or stamp > pending.time)):
                return {}
        known = dict(pending.known) if pending is not None else {}
        _add_signed(known, self._known)
        if self._before is None:
            self._seed_baseline(cargo, stamp)
            return {}
        delta = self._movement(cargo, known)
        if not self._funded(delta, available):
            self._hold(cargo_counts(cargo), stamp, 'funds', known=known)
            return {}
        self._accept(cargo, stamp)
        return delta

    def _movement(self, cargo: Mapping[str, int], known: Mapping[str, int]) -> dict[str, int]:
        before = self._before or {}
        return {key: value for key in before.keys() | cargo.keys() | known.keys()
                if (value := before.get(key, 0) - cargo.get(key, 0) + known.get(key, 0))}

    @staticmethod
    def _funded(delta: Mapping[str, int], available: Optional[Mapping[str, int]]) -> bool:
        return all(value >= 0 or available is not None and available.get(key, 0) >= -value
                   for key, value in delta.items())

    def _seed_baseline(self, cargo: Mapping[str, int], stamp: Optional[float]) -> None:
        self._origin_time = stamp
        self._origin_inventory = cargo_counts(cargo)
        self._accept(cargo, stamp)

    def _accept(self, cargo: Mapping[str, int], stamp: Optional[float], *, complete: bool = True) -> None:
        self._before = cargo_counts(cargo)
        self._point_time = stamp
        self._point_complete = complete
        self._known.clear()
        self._known_time = None
        self._pending = None

    def _hold(
        self, cargo: Optional[dict[str, int]], stamp: Optional[float], reason: str,
        *, known: Optional[dict[str, int]] = None,
    ) -> None:
        if self._pending is None:
            self._pending = InventoryWindow(dict(self._before or {}), cargo, stamp,
                                            dict(self._known if known is None else known), reason)
        else:
            self._pending.cargo = cargo
            self._pending.time = stamp
            self._pending.reason = reason
            if known is not None:
                self._pending.known = dict(known)
        self._known.clear()
        self._known_time = None

    def retry_pending_inventory(self, available: Mapping[str, int]) -> Optional[CargoDecision]:
        """Release only an unambiguous complete observation after its stock becomes available."""
        pending = self._pending
        if pending is None or pending.reason != 'funds' or pending.cargo is None:
            return None
        delta = self._movement(pending.cargo, pending.known)
        if not self._funded(delta, available):
            return None
        later, later_time = dict(self._known), self._known_time
        self._accept(pending.cargo, pending.time)
        self._known, self._known_time = later, later_time
        return self._decision(None, delta)

    def _decision(
        self, ship: Optional[dict[str, int]] = None, delta: Optional[dict[str, int]] = None,
    ) -> CargoDecision:
        evidence = None
        if self._pending is not None:
            window = self._pending
            evidence = {'before': dict(window.before), 'cargo': window.cargo, 'inventory_time': window.time,
                        'accounted': dict(window.known), 'later_known': dict(self._known),
                        'known_through': self._known_time, 'reason': window.reason}
        return CargoDecision(ship, delta or {}, evidence, self._generation)
