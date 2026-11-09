"""Attribute ship inventory changes without counting journal movements twice."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

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
        self._unfunded_keys: set[str] = set()
        self._unfunded_changes: dict[str, int] = {}
        self._unfunded_times: dict[str, Optional[float]] = {}
        self._unfunded_ship_point: dict[str, int] = {}
        self._unfunded_point_accounted: dict[str, int] = {}
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
        self._deferred_keys: set[str] = set()
        self._settled_time: Optional[float] = None
        self._settled_credit: dict[str, int] = {}
        self._settled_ship_changes: dict[str, int] = {}
        self._retained_physical_keys: set[str] = set()
        self._manual_coverage_time: Optional[float] = None
        self._manual_point: Optional[dict[str, int]] = None
        self._manual_stock: dict[str, int] = {}
        self._manual_known_ship_changes: dict[str, int] = {}
        self._manual_pending: dict[str, int] = {}
        self._manual_pending_noncarrier: dict[str, int] = {}
        self._manual_uncertain: dict[str, int] = {}
        self._manual_entry: Any = None
        self._manual_entry_covered = False
        self._last_observed_time: Optional[float] = None
        self._last_movement_time: Optional[float] = None
        self._held_complete_inventory: Optional[dict[str, Any]] = None
        self._held_captured_entry: Optional[Mapping[str, Any]] = None
        self._held_carrier_intents: list[dict[str, Any]] = []
        self._held_ship_only: dict[str, int] = {}
        self._held_ship_anchor: dict[str, int] = {}
        self._held_consumed_keys: set[str] = set()
        self._held_later_keys: set[str] = set()
        self._journal_entry: Mapping[str, Any] = {}
        self._context_generation = getattr(self, "_context_generation", 0) + 1

    def context_generation(self) -> int:
        """Identify the dock/vehicle lifetime owning an unresolved physical observation."""
        return self._context_generation

    def has_pending_inventory_placement(self) -> bool:
        """Require complete ship evidence before rebasing an unresolved placement window."""
        held = self._held_complete_inventory
        return bool(held and (held["pending_placement"] or held.get("await_complete_after") is not None))

    def has_held_ship_inventory(self) -> bool:
        """Check for a complete ship hold whose carrier attribution remains unsettled."""
        return self._held_complete_inventory is not None

    def defer_pending_market_inventory(
        self, entry: Mapping[str, Any], *, complete: bool = False, carrier_move: bool = True,
    ) -> bool:
        """Keep partial market state from consuming the window or letting its older point replay."""
        held = self._held_complete_inventory
        if complete or not carrier_move or held is None:
            return False
        stamp = _event_time(entry.get("timestamp"))
        if stamp is not None and stamp < held["time"]:
            self._deferred_inventory = True
            return True
        held["await_complete_after"] = max(
            held.get("await_complete_after") or held["time"], stamp if stamp is not None else held["time"],
        )
        for key, amount in self._ship_changes(entry).items():
            held["pending_placement"][key] = held["pending_placement"].get(key, 0) + amount
        self._deferred_inventory = True
        return True

    def retain_pending_market_trade(
        self, entry: Mapping[str, Any], carrier_stock: Optional[Mapping[str, int]],
    ) -> dict[str, int]:
        """Report a funded trade once, or retain its debit for the physical interval that will include it."""
        if self.inventory_shares_time(entry) and self._reconciled_time == self._physical_time:
            return self.covered_movement(entry, True, carrier_stock=carrier_stock)
        return self._hold_journal_fallback(self.explicit_carrier_movement(entry), None, carrier_stock)

    def cover_manual_manifest(self, cargo: Mapping[str, int]) -> None:
        """Retire covered attribution while keeping its usable physical point for later movement."""
        stamps = [self._last_observed_time, self._last_movement_time, self._physical_time, self._inventory_time]
        covered_at = max((stamp for stamp in stamps if stamp is not None), default=None)
        point = None
        if self._before is not None and not self._deferred_inventory:
            point = cargo_counts({key: self._before.get(key, 0) + self._accounted.get(key, 0)
                                  for key in self._before.keys() | self._accounted.keys()})
        self.reset(point)
        self._manual_coverage_time = covered_at
        self._manual_point = point
        self._manual_stock = cargo_counts(cargo)
        self._inventory_time = covered_at
        self._physical_time = covered_at

    def manual_covers(self, entry: Mapping[str, Any]) -> bool:
        """Identify the current callback whose placement is already covered or explicitly held."""
        return entry is self._manual_entry and self._manual_entry_covered

    def manual_inventory_candidate(self, entry: Mapping[str, Any]) -> bool:
        """Identify callbacks whose matching full hold can resolve placement at the retained manual point."""
        return self.manual_covers(entry) and self.inventory_shares_time(entry)

    def _remember_observation_time(self, timestamp: Any) -> Optional[float]:
        observed = _event_time(timestamp)
        if observed is not None:
            self._last_observed_time = max(self._last_observed_time or observed, observed)
        return observed

    def _observe_manual_coverage(self, entry: Mapping[str, Any]) -> bool:
        self._manual_entry = entry
        self._manual_entry_covered = False
        stamp = _event_time(entry.get("timestamp"))
        changes = self._ship_changes(entry)
        if stamp is None or self._manual_coverage_time is None or not changes:
            return False
        noncarrier = entry.get("event") not in {"MarketBuy", "MarketSell", "CargoTransfer"}
        if stamp > self._manual_coverage_time:
            if noncarrier:
                for key, amount in changes.items():
                    self._manual_known_ship_changes[key] = self._manual_known_ship_changes.get(key, 0) + amount
            return False
        self._manual_entry_covered = True
        if stamp == self._manual_coverage_time:
            for key, amount in changes.items():
                self._manual_pending[key] = self._manual_pending.get(key, 0) + amount
                if noncarrier:
                    self._manual_pending_noncarrier[key] = self._manual_pending_noncarrier.get(key, 0) + amount
            self._deferred_inventory = True
            self._deferred_keys.update(changes)
        return True

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
        self._journal_entry = entry
        self._held_consumed_keys.clear()
        self._held_later_keys.clear()
        self._settled_ship_changes.clear()
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
        if self._observe_manual_coverage(entry):
            return
        changes = self._ship_changes(entry)
        if not changes:
            return
        self._observe_held_ship_change(entry, changes)
        stamp = _event_time(entry.get("timestamp"))
        if stamp is not None:
            self._last_movement_time = max(self._last_movement_time or stamp, stamp)
        if stamp is not None and self._physical_time is not None and stamp > self._physical_time:
            self._retire_inferred()
        if self._before is None:
            return
        self._account_changes(changes, stamp)

    def _observe_held_ship_change(self, entry: Mapping[str, Any], changes: Mapping[str, int]) -> None:
        held = self._held_complete_inventory
        if held is None or entry.get("event") in {"MarketBuy", "MarketSell", "CargoTransfer"}:
            return
        stamp = _event_time(entry.get("timestamp"))
        for key, amount in changes.items():
            if stamp == held["time"]:
                self._observe_same_time_placement(held, key, amount)
            fields = self._held_refinement_fields(held, key, stamp)
            for field in fields:
                _add_signed(held[field], {key: amount})
            if "movement" in fields:
                self._remember_issued_ship_correction(held, key, 0)

    def _observe_same_time_placement(self, held: dict[str, Any], key: str, amount: int) -> None:
        """Keep conditional stock proofs inside their window until a newer complete point consumes them."""
        placement = self._held_ship_placement(held, key, amount)
        if placement == "later":
            self._held_later_keys.add(key)
        elif placement is None:
            self._hold_frozen_placement(held, key, amount)
        if placement is not None and key not in self._origin_ambiguous:
            held["await_complete_after"] = max(held.get("await_complete_after") or held["time"], held["time"])
            if placement == "earlier":
                held["repair_keys"].append(key)

    @staticmethod
    def _held_ship_placement(held: Mapping[str, Any], key: str, amount: int) -> Optional[str]:
        """Choose a placement only when exactly one hypothesis fits the same captured stock position."""
        if key in held["unfunded_times"] or held["issued_ship_corrections"].get(key):
            return None
        stock = held["carrier_stock"]
        if stock is None:
            return None
        movement = held["movement"].get(key, 0)
        earlier = stock.get(key, 0) + movement + amount >= 0
        later = stock.get(key, 0) + movement >= 0
        return ("earlier" if earlier else "later") if earlier != later else None

    def _hold_frozen_placement(self, held: dict[str, Any], key: str, amount: int) -> None:
        """Retain unknown-bound placement until a later full point or a carrier correction resolves it."""
        if (held.get("await_complete_after") is not None
                or (held["carrier_stock"] is None and key not in held["unfunded_times"]
                    and not held["issued_ship_corrections"].get(key))):
            held["pending_placement"][key] = held["pending_placement"].get(key, 0) + amount
            return
        self._origin_ambiguous.add(key)
        held["movement"].pop(key, None)
        issued = held["issued_ship_corrections"].pop(key, 0)
        if issued:
            # This corrects an issued carrier leg, so its lifetime is independent
            # of the physical observation. Covered intents already have that contract.
            self._held_carrier_intents.append({
                "cargo": {key: -issued}, "timestamp": held["timestamp"], "covered_keys": [key],
            })

    def _held_refinement_fields(
        self, held: Mapping[str, Any], key: str, stamp: Optional[float],
    ) -> tuple[str, ...]:
        """Route refinements to the frozen owner of this key's physical interval."""
        if stamp is None or stamp > held["time"] or key in self._held_later_keys:
            return ("later_changes",)
        if key in self._origin_ambiguous or key in held["pending_placement"]:
            return ("accounted",)
        cutoffs = held["unfunded_times"]
        if key not in cutoffs or key in held["released_unfunded_keys"]:
            return ("movement", "accounted")
        return ("accounted",)

    def note_reported_delta(self, delta: Mapping[str, int]) -> None:
        """Exclude issued callbacks from an older held interval without mixing in later ship changes."""
        held = self._held_complete_inventory
        if held is None or not delta:
            return
        self._rebase_held_carrier_stock(held, delta)
        if self._journal_entry is self._held_captured_entry:
            return
        stamp = _event_time(self._journal_entry.get("timestamp"))
        if stamp is not None and stamp <= held["time"]:
            for key, amount in delta.items():
                if key in self._held_consumed_keys:
                    continue
                fields = self._held_refinement_fields(held, key, stamp)
                for field in fields:
                    _add_signed(held[field], {key: amount}, -1)
                if ("movement" in fields
                        and self._journal_entry.get("event") not in {"MarketBuy", "MarketSell", "CargoTransfer"}):
                    self._remember_issued_ship_correction(held, key, amount)
        elif self._journal_entry.get("event") in {"MarketBuy", "MarketSell", "CargoTransfer"}:
            _add_signed(held["later_changes"], delta, -1)

    def _rebase_held_carrier_stock(self, held: dict[str, Any], delta: Mapping[str, int]) -> None:
        """Keep the stock budget at the position of carrier legs already removed from the held movement."""
        if held["carrier_stock"] is None:
            return
        if self._journal_entry is self._held_captured_entry:
            _add_signed(held["carrier_stock"], delta)
            return
        if self._journal_entry.get("event") not in {"MarketBuy", "MarketSell", "CargoTransfer"}:
            return
        stamp = _event_time(self._journal_entry.get("timestamp"))
        if stamp is not None and stamp <= held["time"]:
            _add_signed(held["carrier_stock"], delta)

    @staticmethod
    def _remember_issued_ship_correction(held: dict[str, Any], key: str, amount: int) -> None:
        """Retain issued correction quantities still paired with an opposite unaccepted physical leg."""
        issued = held["issued_ship_corrections"].get(key, 0) + amount
        movement = held["movement"].get(key, 0)
        if issued * movement < 0:
            held["issued_ship_corrections"][key] = (1 if issued > 0 else -1) * min(abs(issued), abs(movement))
        else:
            held["issued_ship_corrections"].pop(key, None)

    def _account_changes(self, changes: Mapping[str, int], stamp: Optional[float]) -> None:
        for key, delta in changes.items():
            settled = self._consume_settled_credit(key, delta, stamp)
            if settled:
                self._settled_ship_changes[key] = settled
            self._accounted[key] = self._accounted.get(key, 0) + delta
            if (self._anchor_before is not None
                    and (stamp is None or self._frame_start is None or stamp >= self._frame_start)):
                self._anchor_accounted[key] = self._anchor_accounted.get(key, 0) + delta - settled

    def _consume_settled_credit(self, key: str, delta: int, stamp: Optional[float]) -> int:
        """Exclude the part already included in the physical inventory at the active frame's boundary."""
        if stamp is None or stamp != self._settled_time:
            return 0
        credited = -self._settled_credit.get(key, 0)
        if delta * credited <= 0:
            return 0
        portion = (1 if delta > 0 else -1) * min(abs(delta), abs(credited))
        self._settled_credit[key] += portion
        return portion

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
        correction_stock: Optional[Mapping[str, int]] = None,
    ) -> dict[str, int]:
        """Invert only movement left after subtracting known journal changes, then consume once."""
        observed = self._remember_observation_time(timestamp)
        previous_time = self._physical_time
        if observed is not None and previous_time is not None and observed > previous_time:
            self._retire_inferred()
        self._next_frame_start = previous_time
        if self._before is None:
            self._unknown_origin = True
            self._origin_time = observed
        known = self._before is not None
        if not allow_bank_movement:
            self._clear_inferred()
        result = self._reconcile_physical(
            cargo, allow_bank_movement, carrier_stock=carrier_stock, observation_time=observed,
            correction_stock=correction_stock,
        )
        self._remember_held_inventory(cargo, timestamp, carrier_stock=carrier_stock)
        if not self._physical_rejected:
            self._inventory_time = observed
            self._physical_time = observed
            self._reconciled_time = observed if allow_bank_movement and known else None
            self._prove_baseline(observed)
            self._advance_unfunded_time(observed)
        return result

    def _reconcile_physical(
        self, cargo: Mapping[str, Any], allowed: bool, expected: Optional[Mapping[str, int]] = None,
        frame_accounted: Optional[Mapping[str, int]] = None,
        carrier_stock: Optional[Mapping[str, int]] = None,
        complete_observation: bool = True,
        unfunded_expected: Optional[Mapping[str, int]] = None,
        observation_time: Optional[float] = None,
        reclassify_credit: bool = False,
        correction_stock: Optional[Mapping[str, int]] = None,
    ) -> dict[str, int]:
        self._physical_rejected = False
        allowed = allowed and self._before is not None
        after = cargo_counts(cargo)
        # Ship inventory is valid even when its proposed bank attribution is unsafe.
        self._inventory_observed = True
        if self._await_complete_market_inventory(complete_observation, observation_time):
            self._physical_rejected = True
            self._deferred_inventory = True
            result = self._hold_journal_fallback(expected or {}, frame_accounted, correction_stock)
            _add_signed(result, self._retract_unchanged_ship_credit(
                after, correction_stock, complete_ship_change=complete_observation and reclassify_credit,
            ))
            return result
        if self._await_manual_inventory(after, complete_observation, frame_accounted):
            return dict(expected or {})
        result = self._physical_movement(after) if allowed else {}
        if self._would_clamp_movement(result, expected or {}, carrier_stock, correction_stock):
            # With a known baseline, even a physical delta matching a journal
            # trade must fit stock remaining after reserved writes.
            fallback = self._hold_journal_fallback(expected or {}, frame_accounted, correction_stock)
            self._deferred_inventory = True
            self._deferred_keys.update(key for key in self._before.keys() | after.keys()
                                       if self._before.get(key, 0) != after.get(key, 0))
            self._deferred_keys.update(key for key, amount in self._accounted.items() if amount)
            self._physical_rejected = True
            return fallback
        if allowed:
            self._retain_inferred(result, expected or {}, self._inference_accounting(frame_accounted))
            self._retain_unfunded_physical(after, unfunded_expected or {})
        self._before = after
        self._accounted.clear()
        self._retire_unfunded_anchor_accounting()
        self._retain_unfunded_intents()
        self._held_ship_only.clear()
        self._held_ship_anchor.clear()
        self._deferred_inventory = bool(self._origin_ambiguous or self._unfunded_keys or self._held_carrier_intents)
        self._deferred_keys.clear()
        return result

    def _await_complete_market_inventory(self, complete: bool, observed: Optional[float]) -> bool:
        """Keep a pending trade's partial or same-second observation behind its complete-evidence cutoff."""
        held = self._held_complete_inventory
        if not complete and held is not None:
            return True
        cutoff = held.get("await_complete_after") if held is not None else None
        return cutoff is not None and not (complete and observed is not None and observed > cutoff)

    def _retract_unchanged_ship_credit(
        self, after: Mapping[str, int], available: Optional[Mapping[str, int]],
        *, complete_ship_change: bool,
    ) -> dict[str, int]:
        """Cancel only funded old credit explained by known net changes at an unchanged validated hold."""
        if not complete_ship_change or available is None:
            return {}
        changes = {key: self._accounted.get(key, 0) for key in self._ship_changes(self._journal_entry)
                   if (self._before or {}).get(key, 0) == after.get(key, 0)
                   and self._inferred.get(key, 0) > 0 and key not in self._origin_ambiguous | self._unfunded_keys}
        return self._reclassify_credited_changes(changes, available) or {}

    def _retain_unfunded_intents(self, cutoff: Optional[float] = None) -> None:
        remaining = []
        for intent in self._held_carrier_intents:
            keep = self._unfunded_keys | set(intent.get("covered_keys", []))
            cargo = {key: amount for key, amount in intent["cargo"].items() if key in keep}
            if cutoff is not None and (_event_time(intent["timestamp"]) or 0) > cutoff:
                cargo = dict(intent["cargo"])
            if cargo:
                remaining.append({**intent, "cargo": cargo})
        self._held_carrier_intents = remaining

    def _retain_unfunded_physical(
        self, after: Mapping[str, int], expected: Mapping[str, int], *, cutoff: Optional[float] = None,
    ) -> None:
        self._absorb_unfunded_intents(self._unfunded_keys, cutoff=cutoff)
        for key in self._unfunded_keys:
            residual = (self._unfunded_ship_point[key] - after.get(key, 0)
                        + self._accounted.get(key, 0) - self._unfunded_point_accounted.get(key, 0)
                        - expected.get(key, 0))
            self._unfunded_changes[key] += residual
            self._unfunded_ship_point[key] = after.get(key, 0)
            self._unfunded_point_accounted[key] = 0

    def _advance_unfunded_time(self, observed: Optional[float]) -> None:
        if observed is None:
            return
        for key in self._unfunded_keys:
            self._unfunded_times[key] = observed
        for intent in self._held_carrier_intents:
            if (_event_time(intent["timestamp"]) or 0) <= observed:
                keys = set(intent.get("covered_keys", [])) | (intent["cargo"].keys() & self._unfunded_keys)
                if keys:
                    intent["covered_keys"] = sorted(keys)

    def _hold_journal_fallback(
        self, expected: Mapping[str, int], frame: Optional[Mapping[str, int]],
        stock: Optional[Mapping[str, int]],
    ) -> dict[str, int]:
        if frame is not None:
            self._accounted = dict(frame)
        omitted = self._unverified_withdrawals(expected, stock)
        for key in omitted:
            self._accounted[key] = self._accounted.get(key, 0) + expected[key]
        if omitted:
            self._held_carrier_intents.append({"cargo": {key: expected[key] for key in omitted},
                                               "timestamp": self._journal_entry.get("timestamp")})
        return {key: amount for key, amount in expected.items() if key not in omitted}

    def _await_manual_inventory(
        self, after: Mapping[str, int], complete: bool, frame_accounted: Optional[Mapping[str, int]],
    ) -> bool:
        """Keep partial EDMC state from retiring an unresolved manual-placement observation."""
        if not self._manual_pending:
            return False
        if complete:
            self._resolve_manual_pending(after)
            return False
        if frame_accounted is not None:
            self._accounted = dict(frame_accounted)
        self._deferred_inventory = True
        self._physical_rejected = True
        return True

    def _resolve_manual_pending(self, after: Mapping[str, int]) -> None:
        """Use stock bounds to resolve old/new placement, retaining indistinguishable cases for full proof."""
        for key, amount in self._manual_pending.items():
            change = self._manual_pending_noncarrier.get(key, 0)
            covered_stock = (self._manual_stock.get(key, 0) + (self._manual_point or {}).get(key, 0)
                             + self._manual_known_ship_changes.get(key, 0) - after.get(key, 0))
            new_stock = covered_stock + change
            if self._manual_point is None or covered_stock >= 0 and new_stock >= 0 and change:
                self._origin_ambiguous.add(key)
                self._manual_uncertain[key] = amount
            elif covered_stock < 0 <= new_stock:
                self._accounted[key] = self._accounted.get(key, 0) + change
                self._manual_known_ship_changes[key] = self._manual_known_ship_changes.get(key, 0) + change
            elif covered_stock < 0 and new_stock < 0:
                self._origin_ambiguous.add(key)
                self._manual_uncertain[key] = amount
        self._manual_pending.clear()
        self._manual_pending_noncarrier.clear()

    def _physical_movement(self, after: Mapping[str, int]) -> dict[str, int]:
        if self._before is None:
            return {}
        result = {}
        for key in self._before.keys() | after.keys() | self._accounted.keys() | self._held_ship_only.keys():
            delta = (self._before.get(key, 0) - after.get(key, 0) + self._accounted.get(key, 0)
                     + self._held_ship_only.get(key, 0))
            if delta and key not in self._origin_ambiguous | self._unfunded_keys:
                result[key] = delta
        return result

    @staticmethod
    def _unverified_withdrawals(cargo: Mapping[str, int], stock: Optional[Mapping[str, int]]) -> set[str]:
        return {key for key, delta in cargo.items()
                if delta < 0 and (stock is None or -delta > stock.get(key, 0))}

    @classmethod
    def _would_clamp_movement(
        cls, result: Mapping[str, int], expected: Mapping[str, int],
        baseline: Optional[Mapping[str, int]], available: Optional[Mapping[str, int]],
    ) -> bool:
        """Require reserved stock except for known startup trades queued behind the unloaded baseline."""
        # Known startup trades enter the initial queue; its dispatch guard waits
        # for sufficient confirmed stock. A known empty manifest or pending full
        # target never gets this exception: those need an execution budget now.
        bounded = {key: delta for key, delta in result.items()
                   if baseline is not None or delta != expected.get(key, 0)}
        return bool(cls._unverified_withdrawals(bounded, available))

    def _prove_baseline(self, observed: Optional[float]) -> None:
        if observed is not None and self._origin_time is not None and observed > self._origin_time:
            self._baseline_proven = True
            self._retained_physical_keys.clear()

    def _remember_held_inventory(
        self, cargo: Mapping[str, Any], timestamp: Any, *, complete: bool = True,
        carrier_stock: Optional[Mapping[str, int]] = None,
    ) -> None:
        if not self._physical_rejected:
            self._held_complete_inventory = None
        elif complete:
            after = cargo_counts(cargo)
            previous = self._held_complete_inventory or {}
            observed = _event_time(timestamp)
            pending, cutoff = self._remaining_placement_uncertainty(previous, observed)
            self._held_captured_entry = self._journal_entry
            self._held_complete_inventory = {
                "cargo": after, "timestamp": timestamp, "time": _event_time(timestamp) or 0,
                "before": dict(self._before or {}), "accounted": dict(self._accounted),
                "movement": self._physical_movement(after), "later_changes": {},
                "physical_time": self._physical_time,
                "unfunded_times": dict(self._unfunded_times),
                "unfunded_ship_point": dict(self._unfunded_ship_point),
                "unfunded_point_accounted": dict(self._unfunded_point_accounted),
                "released_unfunded_keys": [],
                "issued_ship_corrections": {},
                "carrier_stock": None if carrier_stock is None else dict(carrier_stock),
                "pending_placement": dict(pending),
                "await_complete_after": cutoff,
                "repair_keys": [],
            }
            for key, amount in previous.get("issued_ship_corrections", {}).items():
                self._remember_issued_ship_correction(self._held_complete_inventory, key, amount)

    @staticmethod
    def _remaining_placement_uncertainty(
        previous: Mapping[str, Any], observed: Optional[float],
    ) -> tuple[dict[str, int], Optional[float]]:
        """Expire only placement evidence consumed by a strictly newer complete observation."""
        previous_time = previous.get("time")
        newer = observed is not None and (previous_time is None or observed > previous_time)
        pending = {} if newer else dict(previous.get("pending_placement", {}))
        cutoff = previous.get("await_complete_after")
        if cutoff is not None and observed is not None and observed > cutoff:
            cutoff = None
        return pending, cutoff

    def retry_held_inventory(self, carrier_stock: Mapping[str, int]) -> Optional[dict[str, int]]:
        """Reconcile a complete held observation once this context's carrier stock becomes known."""
        held = self._held_complete_inventory
        retain_window = False
        if held is not None:
            blocked = self._origin_ambiguous | held["pending_placement"].keys()
            movement = {key: amount for key, amount in held["movement"].items()
                        if amount and key not in blocked}
            if held.get("await_complete_after") is not None:
                if not self._can_issue_held_withdrawals(held, movement, carrier_stock):
                    return {}
                retain_window = True
            self._origin_ambiguous.update(held["pending_placement"])
            if self._unverified_withdrawals(movement, carrier_stock):
                return {}
            result = dict(movement)
            self._accept_held_interval(held, movement)
        else:
            result = {}
        available = dict(carrier_stock)
        _add_signed(available, result)
        if held is not None:
            _add_signed(result, self._release_funded_unfunded(held["unfunded_times"].keys(), available))
        released = self._release_held_journal(available)
        _add_signed(result, released)
        if held is None:
            _add_signed(result, self._release_held_ship_only(available))
        if retain_window:
            self._retain_accepted_placement_window(held, movement)
        return result if held is not None or result else None

    def _can_issue_held_withdrawals(
        self, held: Mapping[str, Any], movement: Mapping[str, int], available: Mapping[str, int],
    ) -> bool:
        """Allow only reversible funded debits while their placement evidence remains unresolved."""
        return bool(
            movement and all(amount < 0 for amount in movement.values())
            and movement.keys() <= set(held["repair_keys"])
            and held["await_complete_after"] == held["time"]
            and not (held["pending_placement"] or held["later_changes"] or self._origin_ambiguous
                     or self._unfunded_keys or self._held_carrier_intents)
            and (self._last_movement_time is None or self._last_movement_time <= held["time"])
            and held["carrier_stock"] is not None
            and not self._unverified_withdrawals(movement, held["carrier_stock"])
            and not self._unverified_withdrawals(movement, available)
            and self._physical_movement(held["cargo"]) == movement
        )

    def _retain_accepted_placement_window(self, held: Mapping[str, Any], movement: Mapping[str, int]) -> None:
        """Keep coverage and the cutoff after publishing a funded repair; no quantity is left to replay."""
        window = deepcopy(held)
        window.update({"before": dict(self._before or {}), "accounted": dict(self._accounted), "movement": {},
                       "later_changes": dict(self._accounted), "physical_time": self._physical_time,
                       "issued_ship_corrections": {}, "repair_keys": []})
        _add_signed(window["carrier_stock"], movement)
        self._held_complete_inventory = window
        self._held_captured_entry = None
        self._deferred_keys.update(held["before"].keys() | held["cargo"].keys() | held["accounted"].keys()
                                   | held["movement"].keys() | held["later_changes"].keys() | set(held["repair_keys"]))
        self._deferred_inventory = True

    def _release_held_ship_only(self, available: dict[str, int]) -> dict[str, int]:
        """Release funded corrections without recreating a retired physical rollback anchor."""
        omitted = self._blocked_ship_corrections(self._held_ship_only, available)
        result = {key: amount for key, amount in self._held_ship_only.items() if key not in omitted}
        if not result:
            return {}
        self._held_ship_only = {key: amount for key, amount in self._held_ship_only.items() if key in omitted}
        _add_signed(available, result)
        owned = {}
        if self._anchor_before is not None:
            owned = {key: -min(-amount, -self._held_ship_anchor[key]) for key, amount in result.items()
                     if amount < 0 and self._held_ship_anchor.get(key, 0) < 0}
            _add_signed(self._held_ship_anchor, owned, -1)
            if owned:
                self._retain_inferred(owned, {}, self._accounted)
        if self._unknown_origin:
            remainder = dict(result)
            _add_signed(remainder, owned, -1)
            self._adjust_origin_exposure(remainder)
        self._retire_held_ship_deferral()
        return result

    def _retire_held_ship_deferral(self) -> None:
        """Retire only deferral owned by a completed or canceled ship-only correction."""
        self._deferred_inventory = bool(
            self._held_ship_only or self._held_complete_inventory
            or self._deferred_keys or any(self._accounted.values()) or self._origin_ambiguous or self._unfunded_keys
            or self._held_carrier_intents or self._manual_pending or self._manual_uncertain
        )

    def _release_funded_unfunded(self, keys: Iterable[str], available: dict[str, int]) -> dict[str, int]:
        """Issue a funded quantitative remainder after its complete physical interval is accepted."""
        result = {}
        for key in (set(keys) & self._unfunded_keys) - self._origin_ambiguous:
            amount = self._unfunded_changes[key]
            if self._unverified_withdrawals({key: amount}, available):
                continue
            _add_signed(result, {key: amount})
            _add_signed(available, {key: amount})
            self._settle_unfunded_key(key)
        self._deferred_inventory = bool(self._origin_ambiguous or self._unfunded_keys or self._held_carrier_intents)
        return result

    def _accept_held_interval(self, held: Mapping[str, Any], movement: Mapping[str, int]) -> None:
        self._before = dict(held["before"])
        self._accounted = dict(held["accounted"])
        self._next_frame_start = held["physical_time"]
        inference = {key: amount for key, amount in movement.items() if key not in self._origin_ambiguous}
        self._retain_inferred(inference, {}, self._inference_accounting(held["accounted"]))
        self._retain_unfunded_physical(held["cargo"], {}, cutoff=held["time"])
        self._advance_unfunded_time(held["time"])
        self._before = dict(held["cargo"])
        self._accounted = dict(held["later_changes"])
        self._retire_unfunded_anchor_accounting()
        self._physical_time = self._inventory_time = self._reconciled_time = held["time"]
        self._held_complete_inventory = None
        self._held_ship_only.clear()
        self._held_ship_anchor.clear()
        self._retain_unfunded_intents(held["time"])
        self._deferred_inventory = bool(self._origin_ambiguous or self._unfunded_keys or self._held_carrier_intents)
        self._deferred_keys.clear()
        self._prove_baseline(held["time"])
        if self._last_movement_time is not None and self._last_movement_time > held["time"]:
            self._retire_inferred()

    def _release_held_journal(self, available: dict[str, int]) -> dict[str, int]:
        remaining, result = [], {}
        for intent in self._held_carrier_intents:
            cargo = intent["cargo"]
            if self._unverified_withdrawals(cargo, available):
                remaining.append(intent)
                continue
            _add_signed(result, cargo)
            _add_signed(available, cargo)
            uncovered = {key: amount for key, amount in cargo.items() if key not in intent.get("covered_keys", [])}
            _add_signed(self._accounted, uncovered, -1)
            self._deferred_keys.update(cargo)
            self._deferred_inventory = True
        self._held_carrier_intents = remaining
        return result

    def resolve_origin_movement(
        self, entry: Mapping[str, Any], carrier_move: bool,
    ) -> tuple[Optional[dict[str, int]], Optional[Mapping[str, Any]]]:
        """Resolve only ambiguous components, leaving other commodities for physical reconciliation."""
        changes = self._ship_changes(entry)
        affected = changes.keys() & self._origin_ambiguous
        if not self._origin_precedes(entry):
            affected |= changes.keys() & self._origin_exposed
        if not affected:
            return None, entry
        result = {key: -self._origin_exposure.get(key, 0) for key in affected - self._origin_ambiguous}
        if carrier_move:
            for key, amount in changes.items():
                if key in affected:
                    result[key] = result.get(key, 0) - amount
        self.consume_market(entry, affected)
        self._origin_ambiguous.update(affected)
        self._inferred = {key: amount for key, amount in self._inferred.items() if key not in affected}
        if not self._inferred:
            self._clear_inferred()
        self._deferred_inventory = True
        remaining = changes.keys() - affected
        next_entry = None
        if remaining:
            next_entry = {**entry, "Transfers": [item for item in entry.get("Transfers", [])
                          if isinstance(item, Mapping)
                          and normalize_commodity_key(str(item.get("Type") or "").lower()) in remaining]}
        return {key: amount for key, amount in result.items() if amount}, next_entry

    def explicit_carrier_movement(self, entry: Mapping[str, Any]) -> dict[str, int]:
        """Return the journal's carrier movement when no physical baseline can classify it."""
        return {key: -amount for key, amount in self._ship_changes(entry).items()}

    def movement_awaits_inventory(self, entry: Mapping[str, Any]) -> bool:
        """Keep deferred physical attribution scoped to the commodities whose baseline was restored."""
        return bool(self._ship_changes(entry).keys() & self._deferred_keys)

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

    def _inference_accounting(self, frame: Optional[Mapping[str, int]]) -> dict[str, int]:
        """Exclude accounting consumed by the separate unfunded physical point from a successful rollback frame."""
        source = self._accounted if frame is None else frame
        return {key: amount for key, amount in source.items() if key not in self._unfunded_keys}

    def _retire_unfunded_anchor_accounting(self) -> None:
        """Retain only still-live unfunded accounting in an existing ordinary rollback anchor."""
        if self._anchor_before is None:
            return
        for key in self._unfunded_keys:
            self._anchor_accounted.pop(key, None)
            if self._accounted.get(key, 0):
                self._anchor_accounted[key] = self._accounted[key]

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
        self._held_ship_anchor.clear()

    def _retire_inferred(self) -> None:
        """Retain the last interval's credited movement before starting a newer physical interval."""
        if self._settled_time != self._physical_time:
            self._settled_time = self._physical_time
            self._settled_credit = {}
        for key, amount in self._inferred.items():
            self._settled_credit[key] = self._settled_credit.get(key, 0) + amount
        self._clear_inferred()

    def inventory_shares_time(self, entry: Mapping[str, Any]) -> bool:
        """Identify second-precision observations that need a matching complete inventory."""
        stamp = _event_time(entry.get("timestamp"))
        return stamp is not None and stamp == self._physical_time

    def retain_untrusted_movement(
        self, entry: Mapping[str, Any], carrier_move: bool, carrier_stock: Optional[Mapping[str, int]] = None,
        *, reversal_stock: Optional[Mapping[str, int]] = None,
    ) -> dict[str, int]:
        """Keep known journal movements while deferring speculative bank attribution to the next snapshot."""
        if not carrier_move:
            available = carrier_stock if carrier_stock is not None else reversal_stock
            classified = self._reclassify_credited_ship_change(entry, available)
            if classified is not None:
                return classified
        reversal = {key: -amount for key, amount in self._inferred.items()}
        explicit = self.explicit_carrier_movement(entry) if carrier_move else {}
        result = {key: reversal.get(key, 0) + explicit.get(key, 0) for key in reversal.keys() | explicit.keys()}
        omitted = self._unverified_withdrawals(explicit, carrier_stock)
        self.consume_market(entry, omitted)
        speculative = {key: delta for key, delta in result.items() if delta != explicit.get(key, 0)}
        reversal_available = carrier_stock if carrier_stock is not None else reversal_stock
        keep_current = omitted | self._unverified_withdrawals(speculative, reversal_available)
        self._deferred_keys.update(key for key, amount in self._accounted.items() if amount)
        self._deferred_keys.update(keep_current)
        self._deferred_keys.update(key for key in self._inferred if key not in keep_current)
        if self._unknown_origin:
            self._adjust_origin_exposure({key: amount for key, amount in reversal.items() if key not in keep_current})
        self._restore_untrusted_anchor(keep_current)
        result = {key: explicit.get(key, 0) if key in keep_current else delta
                  for key, delta in result.items() if key not in omitted}
        self._clear_inferred()
        self._reconciled_time = None
        self._deferred_inventory = True
        return {key: amount for key, amount in result.items() if amount}

    def _reclassify_credited_ship_change(
        self, entry: Mapping[str, Any], available: Optional[Mapping[str, int]],
    ) -> Optional[dict[str, int]]:
        """Remove a proved ship-only component from earlier bank inference without rewinding its physical point."""
        return self._reclassify_credited_changes(self._ship_changes(entry), available)

    def _reclassify_credited_changes(
        self, changes: Mapping[str, int], available: Optional[Mapping[str, int]],
    ) -> Optional[dict[str, int]]:
        """Consume a funded reversal of existing inference exactly once in the active accounting."""
        correction = {}
        for key, change in changes.items():
            inferred = self._inferred.get(key, 0)
            if change * inferred < 0:
                amount = (1 if change > 0 else -1) * min(abs(change), abs(inferred))
                correction[key] = amount
        if not correction or self._unverified_withdrawals(correction, available):
            return None
        for key, amount in correction.items():
            self._accounted[key] = self._accounted.get(key, 0) - amount
            self._inferred[key] += amount
        if self._unknown_origin:
            self._adjust_origin_exposure(correction)
        self._inferred = {key: amount for key, amount in self._inferred.items() if amount}
        if not self._inferred:
            self._clear_inferred()
        self._deferred_keys.update(correction)
        self._deferred_inventory = True
        return correction

    def _restore_untrusted_anchor(self, keep_current: set[str]) -> None:
        if self._anchor_before is not None:
            before = self._before or {}
            self._deferred_keys.update(key for key in before.keys() | self._anchor_before.keys()
                                       if key not in keep_current
                                       and before.get(key, 0) != self._anchor_before.get(key, 0))
            self._before = cargo_counts(self._restore_other_keys(before, self._anchor_before, keep_current))
            self._accounted = self._restore_other_keys(self._accounted, self._anchor_accounted, keep_current)
            restored = {key: amount for key, amount in self._held_ship_anchor.items() if key not in keep_current}
            _add_signed(self._accounted, restored, -1)
        elif not self._baseline_proven:
            self._retain_initial_physical_point(keep_current)

    def _retain_initial_physical_point(self, keep_current: set[str]) -> None:
        retained = keep_current | self._retained_physical_keys
        if not retained:
            self._before = None
            self._accounted.clear()
            self._inventory_observed = False
            return
        # The omitted withdrawal still has a valid physical starting point. Other
        # initially ambiguous components require a full carrier manifest, not a zero baseline.
        self._retained_physical_keys.update(retained)
        ambiguous = {key for key, amount in self._accounted.items() if amount and key not in retained}
        self._origin_ambiguous.update(ambiguous)
        for key in ambiguous:
            self._accounted[key] = 0

    @staticmethod
    def _restore_other_keys(
        current: Mapping[str, int], anchor: Mapping[str, int], keep_current: set[str],
    ) -> dict[str, int]:
        return {key: current.get(key, 0) if key in keep_current else anchor.get(key, 0)
                for key in current.keys() | anchor.keys()}

    def deferred_inventory(self) -> Optional[dict[str, Any]]:
        """Return unresolved physical evidence without making it replayable in another ship context."""
        if not self._deferred_inventory:
            return None
        return {"before": None if self._before is None else dict(self._before),
                "accounted": dict(self._accounted), "inventory_time": self._inventory_time,
                "origin_time": self._origin_time, "unknown_origin": self._unknown_origin,
                "origin_ambiguous": sorted(self._origin_ambiguous), "origin_exposure": dict(self._origin_exposure),
                "deferred_keys": sorted(self._deferred_keys),
                "retained_physical_keys": sorted(self._retained_physical_keys),
                "unfunded_keys": sorted(self._unfunded_keys),
                "unfunded_changes": dict(self._unfunded_changes),
                "unfunded_times": dict(self._unfunded_times),
                "unfunded_ship_point": dict(self._unfunded_ship_point),
                "unfunded_point_accounted": dict(self._unfunded_point_accounted),
                "held_carrier_intents": deepcopy(self._held_carrier_intents),
                "held_ship_only": dict(self._held_ship_only),
                "held_complete_inventory": deepcopy(self._held_complete_inventory),
                "manual_coverage_time": self._manual_coverage_time,
                "manual_pending_changes": dict(self._manual_pending),
                "manual_uncertain_changes": dict(self._manual_uncertain)}

    def ship_inventory_covers_market(self, entry: Mapping[str, Any]) -> bool:
        """Ship freshness includes validated held cargo, independently of reported carrier movement."""
        stamp = _event_time(entry.get("timestamp"))
        point = self._complete_ship_inventory_time()
        return stamp is not None and point is not None and stamp < point

    def ship_inventory_shares_time(self, entry: Mapping[str, Any]) -> bool:
        """Identify callbacks sharing a complete or accepted partial ship point."""
        stamp = _event_time(entry.get("timestamp"))
        return stamp is not None and (stamp == self._physical_time or stamp == self._complete_ship_inventory_time())

    def _complete_ship_inventory_time(self) -> Optional[float]:
        held = self._held_complete_inventory
        points = [self._inventory_time, _event_time(held["timestamp"]) if held is not None else None]
        return max((point for point in points if point is not None), default=None)

    def inventory_covers_market(self, entry: Mapping[str, Any]) -> bool:
        """Check whether a strictly newer complete inventory already includes this event's ship changes."""
        stamp = _event_time(entry.get("timestamp"))
        return self.manual_covers(entry) or (
            stamp is not None and self._inventory_time is not None and stamp < self._inventory_time
        )

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

    def consume_market(self, entry: Mapping[str, Any], commodities: Optional[set[str]] = None) -> None:
        """Remove just this event's deferred attribution, retaining other pending explicit movements."""
        for key, amount in self._ship_changes(entry).items():
            if key in self._accounted and (commodities is None or key in commodities):
                self._accounted[key] -= amount

    def covered_movement(
        self, entry: Mapping[str, Any], carrier_move: bool, *, carrier_stock: Optional[Mapping[str, int]] = None,
    ) -> dict[str, int]:
        """Attribute an older known movement without replaying cargo already covered by an inventory."""
        frame = dict(self._accounted)
        self.consume_market(entry)
        changes = self._ship_changes(entry)
        expected = {key: -amount for key, amount in changes.items()} if carrier_move else {}
        result = {} if carrier_move else changes
        quarantined = changes.keys() & self._unfunded_keys
        if not carrier_move:
            result = self._bounded_covered_ship_change(entry, changes, carrier_stock)
            anchored = {key: amount for key, amount in changes.items() if key not in quarantined}
            reported = {key: amount for key, amount in result.items() if key not in quarantined}
            self._remember_covered_anchor(entry, anchored, reported)
        stamp = _event_time(entry.get("timestamp"))
        if self._anchor_before is not None and (
                stamp is None or self._frame_start is None or stamp >= self._frame_start):
            settled = {key: self._settled_ship_changes.get(key, 0) for key in changes}
            active_expected = {key: expected.get(key, 0) + settled.get(key, 0)
                               for key in expected.keys() | settled.keys()}
            inferred = {key: amount for key, amount in result.items() if key not in quarantined}
            active_expected = {key: amount for key, amount in active_expected.items() if key not in quarantined}
            self._retain_inferred(inferred, active_expected, frame)
            if self._unknown_origin:
                self._adjust_origin_exposure(settled)
        elif self._unknown_origin:
            self._adjust_origin_exposure({key: result.get(key, 0) - expected.get(key, 0)
                                          for key in result.keys() | expected.keys()})
        return result

    def _remember_covered_anchor(
        self, entry: Mapping[str, Any], changes: Mapping[str, int], result: Mapping[str, int],
    ) -> None:
        if self._anchor_before is None:
            return
        stamp = _event_time(entry.get("timestamp"))
        if stamp is None or self._frame_start is None or stamp >= self._frame_start:
            _add_signed(self._held_ship_anchor, changes)
        reported = {key: amount for key, amount in result.items() if key in self._held_ship_anchor}
        _add_signed(self._held_ship_anchor, reported, -1)

    def _bounded_covered_ship_change(
        self, entry: Mapping[str, Any], changes: Mapping[str, int], carrier_stock: Optional[Mapping[str, int]],
    ) -> dict[str, int]:
        candidate = dict(self._held_ship_only)
        _add_signed(candidate, {key: amount for key, amount in changes.items() if key not in self._unfunded_keys})
        omitted = self._blocked_ship_corrections(candidate, carrier_stock)
        was_pending = bool(self._held_ship_only)
        self._held_ship_only = {key: amount for key, amount in candidate.items() if key in omitted}
        if self._held_ship_only:
            self._deferred_inventory = True
        elif was_pending:
            self._retire_held_ship_deferral()
        result = {key: amount for key, amount in candidate.items() if key not in omitted}
        _add_signed(result, self._refine_unfunded_changes(entry, changes, carrier_stock))
        return result

    def _blocked_ship_corrections(
        self, cargo: Mapping[str, int], stock: Optional[Mapping[str, int]],
    ) -> set[str]:
        """Apply the same funding and physical-ownership requirements at every correction release seam."""
        return (self._unverified_withdrawals(cargo, stock)
                | (cargo.keys() & (self._origin_ambiguous | self._deferred_keys)))

    def _refine_unfunded_changes(
        self, entry: Mapping[str, Any], changes: Mapping[str, int], stock: Optional[Mapping[str, int]],
    ) -> dict[str, int]:
        result = {}
        stamp = _event_time(entry.get("timestamp"))
        for key in changes.keys() & self._unfunded_keys:
            cutoff = self._unfunded_times.get(key)
            if stamp is not None and cutoff is not None and stamp > cutoff:
                continue
            self._consume_frozen_refinement(key, changes[key], stamp)
            amount = self._unfunded_changes.get(key, 0) + changes[key]
            if self._unverified_withdrawals({key: amount}, stock):
                self._unfunded_changes[key] = amount
                continue
            result[key] = amount
            self._settle_unfunded_key(key)
        return result

    def _consume_frozen_refinement(self, key: str, amount: int, stamp: Optional[float]) -> None:
        """Remove a pending refinement only when the quantitative point actually consumes it."""
        held = self._held_complete_inventory
        if held is None or key not in held["unfunded_times"] or stamp is None or stamp > held["time"]:
            return
        _add_signed(held["accounted"], {key: amount}, -1)
        self._held_consumed_keys.add(key)

    def _settle_unfunded_key(self, key: str) -> None:
        self._release_frozen_unfunded_key(key)
        self._unfunded_changes.pop(key, None)
        self._unfunded_times.pop(key, None)
        self._unfunded_ship_point.pop(key, None)
        self._unfunded_point_accounted.pop(key, None)
        self._unfunded_keys.discard(key)
        self._rebase_refined_key(key)

    def _release_frozen_unfunded_key(self, key: str) -> None:
        """Transfer the unaccepted interval once when its previous quantitative owner is settled."""
        held = self._held_complete_inventory
        if held is None or key not in held["unfunded_times"] or key in held["released_unfunded_keys"]:
            return
        point = held["unfunded_ship_point"][key]
        accounted = held["accounted"].get(key, 0) - held["unfunded_point_accounted"].get(key, 0)
        held["before"][key] = point
        held["accounted"][key] = accounted
        held["movement"][key] = point - held["cargo"].get(key, 0) + accounted
        held["released_unfunded_keys"].append(key)

    def _rebase_refined_key(self, key: str) -> None:
        """Keep a settled quarantined interval out of another commodity's older rollback anchor."""
        if self._anchor_before is not None:
            self._anchor_before[key] = (self._before or {}).get(key, 0)
            self._anchor_accounted[key] = self._accounted.get(key, 0)
        self._inferred.pop(key, None)
        self._held_ship_anchor.pop(key, None)

    def reconcile_market(
        self, entry: Mapping[str, Any], cargo: Mapping[str, Any], *, complete: bool = False,
        carrier_move: bool = True, carrier_stock: Optional[Mapping[str, int]] = None,
        correction_stock: Optional[Mapping[str, int]] = None,
    ) -> Optional[dict[str, int]]:
        """Use physical stock changes for a bank trade, excluding earlier already-reported movements."""
        self._remember_observation_time(entry.get("timestamp"))
        if self.defer_pending_market_inventory(entry, complete=complete, carrier_move=carrier_move):
            return self.retain_pending_market_trade(entry, correction_stock)
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
        newer_unfunded = {key: amount for key, amount in expected.items() if key in self._unfunded_keys}
        after = cargo_counts(cargo)
        held = (self._hold_additional_withdrawal(after, expected, correction_stock, complete=complete)
                | self._unfunded_keys)
        expected = {key: amount for key, amount in expected.items() if key not in held}
        frame = {key: self._accounted.get(key, 0) if key in held else amount for key, amount in frame.items()}
        self._next_frame_start = self._physical_time
        stamp = _event_time(entry.get("timestamp"))
        result = self._reconcile_physical(
            cargo, True, expected, frame, carrier_stock, complete_observation=complete,
            unfunded_expected=newer_unfunded, observation_time=stamp,
            reclassify_credit=not carrier_move, correction_stock=correction_stock,
        )
        _add_signed(result, self._retain_new_unfunded_trades(newer_unfunded, entry, correction_stock))
        self._remember_held_inventory(cargo, entry.get("timestamp"), complete=complete, carrier_stock=carrier_stock)
        if self._physical_rejected:
            return result
        self._accept_market_observation_time(stamp, complete)
        return result

    def _accept_market_observation_time(self, stamp: Optional[float], complete: bool) -> None:
        """Advance accepted market evidence, keeping complete inventory coverage separate from partial state."""
        self._physical_time = max((point for point in (self._physical_time, stamp) if point is not None), default=None)
        self._advance_unfunded_time(self._physical_time)
        self._prove_baseline(stamp)
        if complete:
            self._inventory_time = max(self._inventory_time or 0, stamp or 0) or None
            self._reconciled_time = max(self._reconciled_time or 0, stamp or 0) or None

    def _retain_new_unfunded_trades(
        self, cargo: Mapping[str, int], entry: Mapping[str, Any], stock: Optional[Mapping[str, int]],
    ) -> dict[str, int]:
        omitted = self._unverified_withdrawals(cargo, stock)
        if omitted:
            intent = {"cargo": {key: cargo[key] for key in omitted}, "timestamp": entry.get("timestamp")}
            if not self._physical_rejected:
                intent["covered_keys"] = sorted(omitted)
            self._held_carrier_intents.append(intent)
            self._deferred_inventory = True
        result = {key: amount for key, amount in cargo.items() if key not in omitted}
        if self._physical_rejected:
            _add_signed(self._accounted, result, -1)
        return result

    def _hold_additional_withdrawal(
        self, after: Mapping[str, int], expected: Mapping[str, int],
        carrier_stock: Optional[Mapping[str, int]], *, complete: bool,
    ) -> set[str]:
        """Keep a proved but unreportable withdrawal pending until the carrier's full stock is confirmed."""
        if not complete or carrier_stock is None:
            return set()
        physical = self._physical_movement(after)
        omitted = (self._unverified_withdrawals(expected, carrier_stock)
                   & self._unverified_withdrawals(physical, carrier_stock))
        if not omitted:
            return set()
        # The complete ship point is valid, but Raven cannot support this relative
        # withdrawal. Hold that commodity for full carrier proof while the others
        # pass through normal stock checks and physical/timestamp reconciliation.
        self._unfunded_keys.update(omitted)
        self._absorb_unfunded_intents(omitted)
        for key in omitted:
            self._unfunded_changes[key] = physical[key]
            self._unfunded_times[key] = _event_time(self._journal_entry.get("timestamp"))
            self._unfunded_ship_point[key] = after.get(key, 0)
            self._unfunded_point_accounted[key] = self._accounted.get(key, 0)
            self._held_ship_only.pop(key, None)
            self._held_ship_anchor.pop(key, None)
            self._inferred.pop(key, None)
        if not self._inferred:
            self._clear_inferred()
        return omitted

    def _absorb_unfunded_intents(self, keys: set[str], *, cutoff: Optional[float] = None) -> None:
        """Transfer older unissued quantities into the new complete physical balance that already includes them."""
        if cutoff is None:
            cutoff = _event_time(self._journal_entry.get("timestamp"))
        remaining = []
        for intent in self._held_carrier_intents:
            stamp = _event_time(intent.get("timestamp"))
            absorbed = keys - set(intent.get("covered_keys", []))
            if stamp is not None and cutoff is not None and stamp > cutoff:
                absorbed = set()
            cargo = {key: amount for key, amount in intent["cargo"].items() if key not in absorbed}
            if cargo:
                remaining.append({**intent, "cargo": cargo})
        self._held_carrier_intents = remaining
