"""Durable, ordered carrier movements and evidence for uncertain HTTP outcomes."""

from __future__ import annotations

import copy
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock, RLock
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)
Pending = Dict[str, Dict[int, Dict[str, int]]]


@dataclass
class CarrierCargoQueueState:
    """Share physical-market deferral throughout baseline reads and snapshot handoffs."""

    lock: Any = field(default_factory=RLock)
    baseline_pending: set[int] = field(default_factory=set)
    deltas: dict[int, list[tuple[Dict[str, int], Optional[int], Any]]] = field(default_factory=dict)
    snapshots: Dict[int, Dict[str, int]] = field(default_factory=dict)
    snapshot_coverage: dict[int, list[int]] = field(default_factory=dict)
    capi_received: set[int] = field(default_factory=set)


class PendingCarrierDeliveries:
    """Retain transactions until acknowledged, keeping the legacy unsent checkpoint readable."""

    def __init__(self) -> None:
        self._path: Optional[Path] = None
        self._recovery_path: Optional[Path] = None
        self._records: list[dict[str, Any]] = []
        self._replacements: list[dict[str, Any]] = []
        self._next_id = 1
        self._load_error = False
        self._cargo_revision = 0
        self._confirmed_cargo: dict[int, tuple[int, Dict[str, int]]] = {}
        self._cargo_observations: dict[int, float] = {}
        self._lock = Lock()
        self._cargo_write_lock = RLock()
        self._cargo_queue = CarrierCargoQueueState()

    def configure(self, data_dir: str) -> None:
        """Read a checkpoint in EDMC user data, outside replaceable plugin files."""
        self._path = Path(data_dir) / "RavenColonial.pending-carrier-deliveries.json"
        self._recovery_path = Path(data_dir) / "RavenColonial.carrier-cargo-recovery.json"
        path = self._recovery_path if self._recovery_path.exists() else self._path
        if not path.exists():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            records = self._read_records(payload, path == self._recovery_path)
            replacements = payload.get("replacements", []) if path == self._recovery_path else []
            if not isinstance(replacements, list):
                raise ValueError("Invalid carrier replacement checkpoint")
            for replacement in replacements:
                self._validate_replacement(replacement)
            observations = payload.get("cargo_observations", {}) if path == self._recovery_path else {}
            observations = {int(mid): float(value) for mid, value in observations.items()}
        except (OSError, ValueError, TypeError, AttributeError, KeyError) as error:
            self._load_error = True
            logger.error("Could not read pending carrier deliveries: %s", error)
            return
        with self._lock:
            self._records = records
            self._replacements = replacements
            self._cargo_observations = observations
            self._load_error = False
            self._next_id = max((record["id"] for record in records + replacements), default=0) + 1

    @staticmethod
    def _validate_replacement(replacement: dict[str, Any]) -> None:
        if (not isinstance(replacement["id"], int) or not isinstance(replacement["commander"], str)
                or not isinstance(replacement["market_id"], int) or not isinstance(replacement["cargo"], dict)
                or not isinstance(replacement["covered_ids"], list)
                or any(not isinstance(identity, int) for identity in replacement["covered_ids"])):
            raise ValueError("Invalid carrier replacement evidence")
        replacement["cargo"] = {str(key): int(amount) for key, amount in replacement["cargo"].items()}
        if any(amount < 0 for amount in replacement["cargo"].values()):
            raise ValueError("Negative carrier replacement amount")

    @staticmethod
    def _read_records(payload: Any, recovery: bool) -> list[dict[str, Any]]:
        if recovery:
            if payload.get("version") != 1 or not isinstance(payload.get("records"), list):
                raise ValueError("Unsupported carrier recovery checkpoint")
            records = payload["records"]
            identities = set()
            for record in records:
                PendingCarrierDeliveries._validate_record(record)
                if record["id"] in identities:
                    raise ValueError("Duplicate carrier recovery identity")
                identities.add(record["id"])
            return records
        records = []
        for name, markets in payload.items():
            for mid, cargo in markets.items():
                records.append(PendingCarrierDeliveries._record(
                    len(records) + 1, str(name), int(mid), cargo,
                ))
        return records

    @staticmethod
    def _validate_record(record: dict[str, Any]) -> None:
        if (not isinstance(record["id"], int) or not isinstance(record["commander"], str)
                or not isinstance(record["market_id"], int) or not isinstance(record["cargo"], dict)
                or not isinstance(record["attempted"], bool) or not isinstance(record["uncertain"], bool)):
            raise ValueError("Invalid carrier recovery record")
        record["cargo"] = {str(key): int(amount) for key, amount in record["cargo"].items()}
        if record["before"] is not None:
            record["before"] = {str(key): int(amount) for key, amount in record["before"].items()}
        record["observed_at"] = float(record["observed_at"]) if record["observed_at"] is not None else None

    @staticmethod
    def _record(identity: int, commander: str, market_id: int, cargo: Dict[str, int]) -> dict[str, Any]:
        return {
            "id": identity, "commander": commander, "market_id": int(market_id),
            "cargo": {str(key): int(amount) for key, amount in cargo.items() if int(amount)},
            "attempted": False, "uncertain": False, "before": None, "observed_at": time.time(),
        }

    def snapshot(self) -> Pending:
        """Return aggregate unissued work, compatible with the original checkpoint."""
        with self._lock:
            return self._unsent(self._records, {item["market_id"] for item in self._replacements})

    def records(self, commander: Optional[str] = None, market_id: Optional[int] = None) -> list[dict[str, Any]]:
        """Return ordered, independent evidence, including attempted transactions."""
        with self._lock:
            return copy.deepcopy([
                record for record in self._records
                if (commander is None or record["commander"] == commander)
                and (market_id is None or record["market_id"] == market_id)
            ])

    def cargo_revision(self) -> int:
        """Order a new read request alongside acknowledged writes, independently of completion order."""
        with self._lock:
            self._cargo_revision += 1
            return self._cargo_revision

    def cargo_write_scope(self) -> Any:
        """Serialize carrier writers without blocking EDMC's UI thread."""
        return self._cargo_write_lock

    def cargo_queue_state(self) -> CarrierCargoQueueState:
        """Return the transient market coordinator shared by active and retired commander handlers."""
        return self._cargo_queue

    def cargo_observed_at(self, market_id: int) -> Optional[float]:
        """Keep completed movement evidence after its transaction has been retired."""
        with self._lock:
            return self._cargo_observations.get(market_id)

    def cargo_for_display(self, market_id: int, fallback: Dict[str, int]) -> Dict[str, int]:
        """Project confirmed stock without publishing a new observation or revision."""
        with self._lock:
            current = self._confirmed_cargo.get(market_id)
            return dict(current[1] if current is not None else fallback)

    def remember_cargo(
        self, market_id: int, cargo: Dict[str, int], *,
        read_revision: Optional[int] = None, written: bool = False,
    ) -> Dict[str, int]:
        """Accept later-requested reads unless an acknowledged write has since invalidated them."""
        with self._lock:
            current = self._confirmed_cargo.get(market_id)
            if current is None or written or read_revision is not None and read_revision >= current[0]:
                if written or read_revision is None:
                    self._cargo_revision += 1
                    read_revision = self._cargo_revision
                current = read_revision, dict(cargo)
                self._confirmed_cargo[market_id] = current
            return dict(current[1])

    def replacements(self, commander: Optional[str] = None, market_id: Optional[int] = None) -> list[dict[str, Any]]:
        """Return durable full-write targets that hold all dependent relative movements."""
        with self._lock:
            return copy.deepcopy([
                item for item in self._replacements
                if (commander is None or item["commander"] == commander)
                and (market_id is None or item["market_id"] == market_id)
            ])

    def begin_replacement(
        self, commander: str, market_id: int, cargo: Dict[str, int], covered_ids: list[int],
        *, attempted: bool = True, source: str = "automatic",
    ) -> int:
        """Commit the absolute target and covered identities before any full-write HTTP request."""
        with self._lock:
            covered = set(covered_ids)
            for item in self._replacements:
                if item["market_id"] == market_id:
                    covered.update(item["covered_ids"])
            replacement = {
                "id": self._next_id, "commander": commander, "market_id": market_id,
                "cargo": dict(cargo), "covered_ids": sorted(covered),
                "attempted": attempted, "source": source, "observed_at": time.time(),
            }
            updated = [item for item in self._replacements if item["market_id"] != market_id] + [replacement]
            self._next_id += 1
            try:
                self._write(self._records, updated)
            except OSError:
                # HTTP has not started. Retain intent and hold later relative work
                # until this target can be durably checkpointed and sent.
                replacement["attempted"] = False
                self._replacements = updated
                raise
            self._replacements = updated
            return replacement["id"]

    def acknowledge_replacement(self, identity: int, cargo: Dict[str, int]) -> bool:
        """Retire coverage atomically only when the observed stock confirms every target, including zeros."""
        with self._lock:
            replacement = next((item for item in self._replacements if item["id"] == identity), None)
            if replacement is None:
                return False
            expected = {key: amount for key, amount in replacement["cargo"].items() if amount > 0}
            if {key: amount for key, amount in cargo.items() if amount > 0} != expected:
                return False
            records = [item for item in self._records if item["id"] not in replacement["covered_ids"]]
            replacements = [item for item in self._replacements if item["id"] != identity]
            observations = self._completed_observations(replacement["covered_ids"], replacement)
            self._write(records, replacements, observations)
            self._records, self._replacements = records, replacements
            self._cargo_observations = observations
            return True

    def _completed_observations(self, identities: list[int], replacement: Optional[dict] = None) -> dict[int, float]:
        observations = dict(self._cargo_observations)
        completed = [item for item in self._records if item["id"] in identities]
        if replacement is not None:
            completed.append(replacement)
        for item in completed:
            observed = item.get("observed_at")
            mid = item["market_id"]
            if observed is not None:
                observations[mid] = max(observations.get(mid, 0), float(observed))
        return observations

    def is_first(self, identity: int, market_id: int) -> bool:
        """Relative writes depend on the earliest unresolved movement for the entire market."""
        with self._lock:
            first = next((item for item in self._records if item["market_id"] == market_id), None)
            return first is not None and first["id"] == identity and not any(
                item["market_id"] == market_id for item in self._replacements
            )

    def record(self, commander: str, market_id: int, cargo: Dict[str, int]) -> int:
        """Record an observed movement before it can be queued or deferred."""
        with self._lock:
            record = self._record(self._next_id, commander, market_id, cargo)
            self._next_id += 1
            self._records.append(record)
            try:
                self._write(self._records)
            except OSError as error:
                logger.error("Could not checkpoint unsent carrier deliveries: %s", error)
            return record["id"]

    def consume(
        self, commander: str, market_id: int, cargo: Dict[str, int], identity: Optional[int] = None,
    ) -> None:
        """Discard known ineligible work, or consume a legacy unsent transaction."""
        with self._lock:
            matched = next((record for record in self._records if (
                record["commander"] == commander and record["market_id"] == market_id
                and not record["attempted"] and record["cargo"] == cargo
                and (identity is None or record["id"] == identity)
            )), None)
            updated = [record for record in self._records if record is not matched]
            self._write(updated)
            self._records = updated

    def begin(self, identity: int, before: Optional[Dict[str, int]]) -> bool:
        """Persist an attempt before HTTP, refusing to overtake an earlier transaction."""
        with self._lock:
            updated = copy.deepcopy(self._records)
            record = next((item for item in updated if item["id"] == identity), None)
            if record is None or record["attempted"]:
                return False
            if any(item["market_id"] == record["market_id"] for item in self._replacements):
                return False
            first = next(item for item in updated if item["market_id"] == record["market_id"])
            if first["id"] != identity:
                return False
            confirmed = self._confirmed_cargo.get(record["market_id"])
            baseline = confirmed[1] if confirmed is not None else before
            record.update(attempted=True, uncertain=True, before=copy.deepcopy(baseline))
            self._write(updated)
            self._records = updated
            return True

    def failed(self, identity: int, *, definite_rejection: bool = False) -> None:
        """Keep evidence after failure; only an explicit rejection permits relative replay."""
        with self._lock:
            updated = copy.deepcopy(self._records)
            for record in updated:
                if record["id"] == identity:
                    record["uncertain"] = not definite_rejection
            self._write(updated)
            self._records = updated

    def acknowledge(self, identities: list[int]) -> None:
        """Retire only transactions covered by an acknowledged write or authoritative baseline."""
        with self._lock:
            updated = [record for record in self._records if record["id"] not in identities]
            observations = self._completed_observations(identities)
            self._write(updated, observations=observations)
            self._records = updated
            self._cargo_observations = observations

    def allow_retry(self, identity: int) -> None:
        """Release a definitely rejected transaction after checking its remote baseline."""
        with self._lock:
            updated = copy.deepcopy(self._records)
            for record in updated:
                if record["id"] == identity and not record["uncertain"]:
                    record["attempted"] = False
            self._write(updated)
            self._records = updated

    @staticmethod
    def _unsent(records: list[dict[str, Any]], held_markets: Optional[set[int]] = None) -> Pending:
        pending: Pending = {}
        for record in records:
            if record["attempted"] or record["market_id"] in (held_markets or set()):
                continue
            cargo = pending.setdefault(record["commander"], {}).setdefault(record["market_id"], {})
            for key, amount in record["cargo"].items():
                cargo[key] = cargo.get(key, 0) + amount
        return {
            name: {mid: {key: amount for key, amount in cargo.items() if amount}
                   for mid, cargo in markets.items() if any(cargo.values())}
            for name, markets in pending.items() if any(any(cargo.values()) for cargo in markets.values())
        }

    def _write(
        self, records: list[dict[str, Any]], replacements: Optional[list[dict[str, Any]]] = None,
        observations: Optional[dict[int, float]] = None,
    ) -> None:
        if self._load_error:
            raise OSError("Carrier recovery checkpoint could not be loaded; preserving existing evidence")
        if self._path is None:
            return
        # This file is authoritative. The old file remains an unsent-only compatibility view.
        snapshots = self._replacements if replacements is None else replacements
        self._write_json(self._recovery_path, {
            "version": 1, "records": records, "replacements": snapshots,
            "cargo_observations": self._cargo_observations if observations is None else observations,
        })
        try:
            self._write_json(self._path, self._unsent(records, {item["market_id"] for item in snapshots}))
        except OSError as error:
            # The transaction already committed. A failed compatibility mirror cannot roll it back.
            logger.warning("Carrier compatibility checkpoint was not refreshed: %s", error)

    @staticmethod
    def _write_json(path: Path, payload: Any) -> None:
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        temporary.replace(path)
