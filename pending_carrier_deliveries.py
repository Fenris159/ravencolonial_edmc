"""Durable, ordered carrier movements and evidence for uncertain HTTP outcomes."""

from __future__ import annotations

import copy
import json
import logging
import time
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)
Pending = Dict[str, Dict[int, Dict[str, int]]]


class PendingCarrierDeliveries:
    """Retain transactions until acknowledged, keeping the legacy unsent checkpoint readable."""

    def __init__(self) -> None:
        self._path: Optional[Path] = None
        self._recovery_path: Optional[Path] = None
        self._records: list[dict[str, Any]] = []
        self._next_id = 1
        self._load_error = False
        self._lock = Lock()

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
        except (OSError, ValueError, TypeError, AttributeError, KeyError) as error:
            self._load_error = True
            logger.error("Could not read pending carrier deliveries: %s", error)
            return
        with self._lock:
            self._records = records
            self._load_error = False
            self._next_id = max((record["id"] for record in records), default=0) + 1

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
            return self._unsent(self._records)

    def records(self, commander: Optional[str] = None, market_id: Optional[int] = None) -> list[dict[str, Any]]:
        """Return ordered, independent evidence, including attempted transactions."""
        with self._lock:
            return copy.deepcopy([
                record for record in self._records
                if (commander is None or record["commander"] == commander)
                and (market_id is None or record["market_id"] == market_id)
            ])

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
            first = next(item for item in updated if (
                item["commander"] == record["commander"] and item["market_id"] == record["market_id"]
            ))
            if first["id"] != identity:
                return False
            record.update(attempted=True, uncertain=True, before=copy.deepcopy(before))
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
            self._write(updated)
            self._records = updated

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
    def _unsent(records: list[dict[str, Any]]) -> Pending:
        pending: Pending = {}
        for record in records:
            if record["attempted"]:
                continue
            cargo = pending.setdefault(record["commander"], {}).setdefault(record["market_id"], {})
            for key, amount in record["cargo"].items():
                cargo[key] = cargo.get(key, 0) + amount
        return {
            name: {mid: {key: amount for key, amount in cargo.items() if amount}
                   for mid, cargo in markets.items() if any(cargo.values())}
            for name, markets in pending.items() if any(any(cargo.values()) for cargo in markets.values())
        }

    def _write(self, records: list[dict[str, Any]]) -> None:
        if self._load_error:
            raise OSError("Carrier recovery checkpoint could not be loaded; preserving existing evidence")
        if self._path is None:
            return
        # This file is authoritative. The old file remains an unsent-only compatibility view.
        self._write_json(self._recovery_path, {"version": 1, "records": records})
        self._write_json(self._path, self._unsent(records))

    @staticmethod
    def _write_json(path: Path, payload: Any) -> None:
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        temporary.replace(path)
