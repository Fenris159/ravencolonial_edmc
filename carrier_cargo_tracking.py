"""Attribute ship inventory changes without counting journal movements twice."""

from __future__ import annotations

import json
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
    if not isinstance(inventory, list):
        return None
    cargo: dict[str, int] = {}
    for item in inventory:
        if not isinstance(item, Mapping):
            return None
        key = normalize_commodity_key(str(item["Name"]))
        amount = int(item["Count"])
        if not key or amount < 0:
            return None
        cargo[key] = cargo.get(key, 0) + amount
    if sum(cargo.values()) != int(data["Count"]):
        return None
    return cargo_counts(cargo)


class CarrierShipCargoTracker:
    """Keep one dock's ship baseline and exclude already-attributed cargo mutations."""

    def __init__(self) -> None:
        self.in_main_ship = True
        self._before: Optional[dict[str, int]] = None
        self._accounted: dict[str, int] = {}
        self._inventory_observed = False

    def reset(self, cargo: Optional[Mapping[str, Any]] = None) -> None:
        """Rebase on context changes; an unknown hold cannot generate a delivery."""
        self._before = cargo_counts(cargo) if cargo is not None else None
        self._accounted.clear()

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
        if self._before is None:
            return
        for key, delta in changes.items():
            self._accounted[key] = self._accounted.get(key, 0) + delta

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

    def reconcile(self, cargo: Mapping[str, Any], *, allow_bank_movement: bool) -> dict[str, int]:
        """Invert only movement left after subtracting known journal changes, then consume once."""
        after = cargo_counts(cargo)
        result = {}
        if allow_bank_movement and self._before is not None:
            for key in self._before.keys() | after.keys() | self._accounted.keys():
                delta = self._before.get(key, 0) - after.get(key, 0) + self._accounted.get(key, 0)
                if delta:
                    result[key] = delta
        self._inventory_observed = True
        self.reset(after)
        return result

    def reconcile_market(self, entry: Mapping[str, Any], cargo: Mapping[str, Any]) -> Optional[dict[str, int]]:
        """Use physical stock changes for a bank trade, excluding earlier already-reported movements."""
        if self._before is None:
            self._inventory_observed = True
            self.reset(cargo)
            return None
        # observe_journal counted this trade for a later Cargo snapshot, but its
        # carrier delta has not been sent yet. Other accounted movements remain excluded.
        for key, amount in self._ship_changes(entry).items():
            self._accounted[key] = self._accounted.get(key, 0) - amount
        return self.reconcile(cargo, allow_bank_movement=True)
