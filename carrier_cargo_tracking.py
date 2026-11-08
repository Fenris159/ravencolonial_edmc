"""Attribute ship inventory changes without counting journal movements twice."""

from __future__ import annotations

import json
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


class CarrierShipCargoTracker:
    """Keep one dock's ship baseline and exclude already-attributed cargo mutations."""

    def __init__(self) -> None:
        self.in_main_ship = True
        self._inventory_observed = False
        self.reset()

    def reset(self, cargo: Optional[Mapping[str, Any]] = None) -> None:
        """Rebase on context changes; an unknown hold cannot generate a delivery."""
        self._before: Optional[dict[str, int]] = cargo_counts(cargo) if cargo is not None else None
        self._accounted: dict[str, int] = {}
        self._unknown_origin = cargo is None
        self._baseline_proven = cargo is not None
        self._origin_ambiguous: set[str] = set()
        self._origin_exposure: dict[str, int] = {}
        self._origin_exposed: set[str] = set()
        self._origin_time: Optional[float] = None
        self._inventory_time: Optional[float] = None
        self._reconciled_time: Optional[float] = None
        self._physical_time: Optional[float] = None
        self._inferred: dict[str, int] = {}
        self._anchor_before: Optional[dict[str, int]] = None
        self._anchor_accounted: dict[str, int] = {}
        self._frame_start: Optional[float] = None
        self._next_frame_start: Optional[float] = None
        self._deferred_inventory = False
        self._context_generation = getattr(self, "_context_generation", 0) + 1

    def context_generation(self) -> int:
        """Identify the dock/vehicle lifetime owning an unresolved physical observation."""
        return self._context_generation

    def is_main_ship(self, state: Optional[Mapping[str, Any]] = None) -> bool:
        """Use vehicle events/status, with explicit non-ship state as an extra guard."""
        state = state or {}
        ship = str(state.get("ShipType") or "").lower()
        return self.in_main_ship and not (
            "buggy" in ship or "fighter" in ship or state.get("OnFoot") or state.get("IsSRV")
        )

    def observe_dashboard(self, entry: Mapping[str, Any]) -> None:
        """Read Elite Status vehicle flags; EDMC ShipType remains the mothership type."""
        flags = int(entry.get("Flags", 0))
        if flags & ((1 << 24) | (1 << 25) | (1 << 26)):
            self.in_main_ship = bool(flags & (1 << 24)) and not bool(int(entry.get("Flags2", 0)) & 1)
            if not self.in_main_ship:
                self.reset()

    def observe_journal(self, entry: Mapping[str, Any], state: Mapping[str, Any], market_id: Any) -> None:
        """Consume context and known ship movements before processing this event's snapshot."""
        event = entry.get("event")
        if event in {"StartUp", "LoadGame", "ShipyardSwap", "Died", "Resurrect"}:
            self._inventory_observed = False
        if event in {"LaunchSRV", "LaunchFighter", "Disembark"}:
            self.in_main_ship = False
            self.reset()
        elif event in {"DockSRV", "DockFighter", "LoadGame"}:
            self.in_main_ship = True
            self.reset()
        elif event == "Embark":
            self.in_main_ship = not bool(entry.get("SRV"))
            self.reset()

        snapshot = self._known_state_cargo(state)
        if event in {"Docked", "Location", "StartUp", "LoadGame", "Undocked", "Died", "Resurrect", "ShipyardSwap"}:
            self.reset(snapshot)
            return
        if not self.is_main_ship(state):
            self.reset()
            return
        if event in {"MarketBuy", "MarketSell"} and str(entry.get("MarketID")) != str(market_id):
            self.reset(snapshot)
            return
        changes = self._ship_changes(entry)
        if not changes:
            return
        stamp = _event_time(entry.get("timestamp"))
        if stamp is not None and self._physical_time is not None and stamp > self._physical_time:
            self._clear_inferred()
        if self._before is None:
            return
        self._account_changes(changes, stamp)

    def _account_changes(self, changes: Mapping[str, int], stamp: Optional[float]) -> None:
        for key, delta in changes.items():
            self._accounted[key] = self._accounted.get(key, 0) + delta
            if (self._anchor_before is not None
                    and (stamp is None or self._frame_start is None or stamp >= self._frame_start)):
                self._anchor_accounted[key] = self._anchor_accounted.get(key, 0) + delta

    def _known_state_cargo(self, state: Mapping[str, Any]) -> Optional[dict[str, int]]:
        cargo = state.get("Cargo")
        if not isinstance(cargo, Mapping):
            return None
        snapshot = cargo_counts(cargo)
        return snapshot if snapshot or self._inventory_observed else None

    @staticmethod
    def _ship_changes(entry: Mapping[str, Any]) -> dict[str, int]:
        event = entry.get("event")
        if event == "CargoTransfer":
            return CarrierShipCargoTracker._transfer_changes(entry)
        if event in {"BuyDrones", "SellDrones"}:
            count = _positive_count(entry.get("Count"))
            return {"drones": count if event == "BuyDrones" else -count} if count else {}
        signs = {"MarketBuy": 1, "MarketSell": -1, "EjectCargo": -1, "CollectCargo": 1, "MiningRefined": 1}
        if event in signs:
            key = normalize_commodity_key(str(entry.get("Type") or "").lower())
            count = _positive_count(entry.get("Count", 1))
            return {key: signs[event] * count} if key and count > 0 else {}
        return {}

    @staticmethod
    def _transfer_changes(entry: Mapping[str, Any]) -> dict[str, int]:
        result: dict[str, int] = {}
        for transfer in entry.get("Transfers") or []:
            if not isinstance(transfer, Mapping):
                continue
            key = normalize_commodity_key(str(transfer.get("Type") or "").lower())
            direction = str(transfer.get("Direction") or "").lower()
            count = _positive_count(transfer.get("Count"))
            if key and count > 0 and direction in {"toship", "tocarrier"}:
                result[key] = result.get(key, 0) + (count if direction == "toship" else -count)
        return result

    def reconcile(
        self, cargo: Mapping[str, Any], *, allow_bank_movement: bool, timestamp: Any = None,
        carrier_stock: Optional[Mapping[str, int]] = None,
    ) -> dict[str, int]:
        """Invert only movement left after subtracting known journal changes, then consume once."""
        observed = _event_time(timestamp)
        previous_time = self._physical_time
        if observed is not None and previous_time is not None and observed > previous_time:
            self._clear_inferred()
        self._next_frame_start = previous_time
        if self._before is None:
            self._unknown_origin = True
            self._origin_time = observed
        known = self._before is not None
        if not allow_bank_movement:
            self._clear_inferred()
        result = self._reconcile_physical(cargo, allow_bank_movement, carrier_stock=carrier_stock)
        if not self._physical_rejected:
            self._inventory_time = observed
            self._physical_time = observed
            self._reconciled_time = observed if allow_bank_movement and known else None
            self._prove_baseline(observed)
        return result

    def _reconcile_physical(
        self, cargo: Mapping[str, Any], allowed: bool, expected: Optional[Mapping[str, int]] = None,
        frame_accounted: Optional[Mapping[str, int]] = None,
        carrier_stock: Optional[Mapping[str, int]] = None,
    ) -> dict[str, int]:
        self._physical_rejected = False
        allowed = allowed and self._before is not None
        after = cargo_counts(cargo)
        result = {}
        if allowed:
            for key in self._before.keys() | after.keys() | self._accounted.keys():
                delta = self._before.get(key, 0) - after.get(key, 0) + self._accounted.get(key, 0)
                if delta and key not in self._origin_ambiguous:
                    result[key] = delta
        if self._would_clamp_speculation(result, expected or {}, carrier_stock):
            # A speculative withdrawal would be clamped by Raven and cannot be undone
            # by a later journal event. Keep the pre-observation baseline instead.
            if frame_accounted is not None:
                self._accounted = dict(frame_accounted)
            self._deferred_inventory = True
            self._physical_rejected = True
            return dict(expected or {})
        if allowed:
            self._retain_inferred(result, expected or {}, frame_accounted)
        self._inventory_observed = True
        self._before = after
        self._accounted.clear()
        self._deferred_inventory = bool(self._origin_ambiguous)
        return result

    @staticmethod
    def _would_clamp_speculation(
        result: Mapping[str, int], expected: Mapping[str, int], stock: Optional[Mapping[str, int]],
    ) -> bool:
        return stock is not None and any(
            delta < -stock.get(key, 0) and delta != expected.get(key, 0) for key, delta in result.items()
        )

    def _prove_baseline(self, observed: Optional[float]) -> None:
        if observed is not None and self._origin_time is not None and observed > self._origin_time:
            self._baseline_proven = True

    def resolve_origin_movement(self, entry: Mapping[str, Any], carrier_move: bool) -> Optional[dict[str, int]]:
        """Retain ambiguity when an origin-time trade cannot classify speculative stock safely."""
        changes = self._ship_changes(entry)
        affected = changes.keys() & self._origin_ambiguous
        if not self._origin_precedes(entry):
            affected |= changes.keys() & self._origin_exposed
        if not affected:
            return None
        result = {key: -self._origin_exposure.get(key, 0) for key in affected - self._origin_ambiguous}
        if carrier_move:
            for key, amount in changes.items():
                result[key] = result.get(key, 0) - amount
        self.consume_market(entry)
        self._origin_ambiguous.update(affected)
        self._inferred = {key: amount for key, amount in self._inferred.items() if key not in affected}
        if not self._inferred:
            self._clear_inferred()
        self._deferred_inventory = True
        return {key: amount for key, amount in result.items() if amount}

    def _retain_inferred(
        self, result: Mapping[str, int], expected: Mapping[str, int], frame_accounted: Optional[Mapping[str, int]],
    ) -> None:
        extra = {key: result.get(key, 0) - expected.get(key, 0) for key in result.keys() | expected.keys()}
        if self._unknown_origin:
            self._adjust_origin_exposure(extra)
        if any(extra.values()) and self._anchor_before is None:
            self._anchor_before = dict(self._before or {})
            self._anchor_accounted = dict(self._accounted if frame_accounted is None else frame_accounted)
            self._frame_start = self._next_frame_start
        for key, amount in extra.items():
            self._inferred[key] = self._inferred.get(key, 0) + amount
        self._inferred = {key: amount for key, amount in self._inferred.items() if amount}
        if not self._inferred:
            self._clear_inferred()

    def _adjust_origin_exposure(self, changes: Mapping[str, int]) -> None:
        self._origin_exposed.update(key for key, amount in changes.items() if amount)
        for key, amount in changes.items():
            self._origin_exposure[key] = self._origin_exposure.get(key, 0) + amount
        self._origin_exposure = {key: amount for key, amount in self._origin_exposure.items() if amount}

    def _clear_inferred(self) -> None:
        self._inferred.clear()
        self._anchor_before = None
        self._anchor_accounted.clear()
        self._frame_start = None

    def inventory_shares_time(self, entry: Mapping[str, Any]) -> bool:
        """Identify second-precision observations that need a matching complete inventory."""
        stamp = _event_time(entry.get("timestamp"))
        return stamp is not None and stamp == self._physical_time

    def retain_untrusted_movement(self, entry: Mapping[str, Any], carrier_move: bool) -> dict[str, int]:
        """Keep known journal movements while deferring speculative bank attribution to the next snapshot."""
        result = {key: -amount for key, amount in self._inferred.items()}
        if self._unknown_origin:
            self._adjust_origin_exposure(result)
        if self._anchor_before is not None:
            self._before = self._anchor_before
            self._accounted = dict(self._anchor_accounted)
        elif not self._baseline_proven:
            self._before = None
            self._accounted.clear()
            self._inventory_observed = False
        if carrier_move:
            for key, amount in self._ship_changes(entry).items():
                result[key] = result.get(key, 0) - amount
        self._clear_inferred()
        self._reconciled_time = None
        self._deferred_inventory = True
        return {key: amount for key, amount in result.items() if amount}

    def deferred_inventory(self) -> Optional[dict[str, Any]]:
        """Return unresolved physical evidence without making it replayable in another ship context."""
        if not self._deferred_inventory:
            return None
        return {"before": None if self._before is None else dict(self._before),
                "accounted": dict(self._accounted), "inventory_time": self._inventory_time,
                "origin_time": self._origin_time, "unknown_origin": self._unknown_origin,
                "origin_ambiguous": sorted(self._origin_ambiguous), "origin_exposure": dict(self._origin_exposure)}

    def inventory_covers_market(self, entry: Mapping[str, Any]) -> bool:
        """Check whether a strictly newer complete inventory already includes this event's ship changes."""
        stamp = _event_time(entry.get("timestamp"))
        return stamp is not None and self._inventory_time is not None and stamp < self._inventory_time

    def has_known_inventory(self) -> bool:
        """Keep learned ship inventory trustworthy independently of retired bank attribution."""
        return self._before is not None or self._inventory_observed

    def market_was_reconciled(self, entry: Mapping[str, Any]) -> bool:
        """Check whether an earlier inventory callback reported this movement after a known origin."""
        stamp = _event_time(entry.get("timestamp"))
        return (stamp is not None and self._reconciled_time is not None and stamp < self._reconciled_time
                and self._origin_precedes(entry))

    def _origin_precedes(self, entry: Mapping[str, Any]) -> bool:
        if not self._unknown_origin:
            return True
        stamp = _event_time(entry.get("timestamp"))
        return stamp is not None and self._origin_time is not None and stamp > self._origin_time

    def consume_market(self, entry: Mapping[str, Any]) -> None:
        """Remove just this event's deferred attribution, retaining other pending explicit movements."""
        for key, amount in self._ship_changes(entry).items():
            if key in self._accounted:
                self._accounted[key] -= amount

    def covered_movement(self, entry: Mapping[str, Any], carrier_move: bool) -> dict[str, int]:
        """Attribute an older known movement without replaying cargo already covered by an inventory."""
        frame = dict(self._accounted)
        self.consume_market(entry)
        changes = self._ship_changes(entry)
        expected = {key: -amount for key, amount in changes.items()} if carrier_move else {}
        result = {} if carrier_move else changes
        stamp = _event_time(entry.get("timestamp"))
        if self._anchor_before is not None and (
                stamp is None or self._frame_start is None or stamp >= self._frame_start):
            self._retain_inferred(result, expected, frame)
        elif self._unknown_origin:
            self._adjust_origin_exposure({key: result.get(key, 0) - expected.get(key, 0)
                                          for key in result.keys() | expected.keys()})
        return result

    def reconcile_market(
        self, entry: Mapping[str, Any], cargo: Mapping[str, Any], *, complete: bool = False,
        carrier_move: bool = True, carrier_stock: Optional[Mapping[str, int]] = None,
    ) -> Optional[dict[str, int]]:
        """Use physical stock changes for a bank trade, excluding earlier already-reported movements."""
        if self._before is None:
            if complete:
                self.reconcile(cargo, allow_bank_movement=False, timestamp=entry.get("timestamp"))
            return None
        # observe_journal counted this trade for a later Cargo snapshot, but its
        # carrier delta has not been sent yet. Other accounted movements remain excluded.
        frame = dict(self._accounted)
        if carrier_move:
            self.consume_market(entry)
        if not self._origin_precedes(entry):
            self._before = cargo_counts(cargo)
            self._accounted.clear()
            return None
        expected = {key: -amount for key, amount in self._ship_changes(entry).items()} if carrier_move else {}
        self._next_frame_start = self._physical_time
        stamp = _event_time(entry.get("timestamp"))
        result = self._reconcile_physical(cargo, True, expected, frame, carrier_stock)
        if self._physical_rejected:
            return result
        self._physical_time = stamp
        self._prove_baseline(stamp)
        if complete:
            stamp = self._physical_time
            self._inventory_time = max(self._inventory_time or 0, stamp or 0) or None
            self._reconciled_time = max(self._reconciled_time or 0, stamp or 0) or None
        return result
