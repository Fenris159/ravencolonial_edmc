"""Checkpoint signed carrier movements which have not reached their first HTTP attempt."""

from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from threading import Lock
from typing import Dict, Optional

logger = logging.getLogger(__name__)
Pending = Dict[str, Dict[int, Dict[str, int]]]


class PendingCarrierDeliveries:
    """Keep unsent movements durable without replaying ambiguous issued writes."""

    def __init__(self) -> None:
        self._path: Optional[Path] = None
        self._pending: Pending = {}
        self._lock = Lock()

    def configure(self, data_dir: str) -> None:
        """Read a checkpoint in EDMC user data, outside replaceable plugin files."""
        self._path = Path(data_dir) / "RavenColonial.pending-carrier-deliveries.json"
        if not self._path.exists():
            return
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            pending = {
                str(name): {
                    int(mid): {str(key): int(amount) for key, amount in cargo.items() if int(amount)}
                    for mid, cargo in markets.items()
                }
                for name, markets in payload.items()
            }
        except (OSError, ValueError, TypeError, AttributeError) as error:
            logger.error("Could not read pending carrier deliveries: %s", error)
            return
        with self._lock:
            self._pending = pending

    def snapshot(self) -> Pending:
        """Return an independent copy for recovery initialization."""
        with self._lock:
            return copy.deepcopy(self._pending)

    def record(self, commander: str, market_id: int, cargo: Dict[str, int]) -> None:
        """Record an observed movement before it can be queued or deferred."""
        with self._lock:
            updated = self._changed(commander, market_id, cargo, 1)
            self._pending = updated
            try:
                self._write(updated)
            except OSError as error:
                logger.error("Could not checkpoint unsent carrier deliveries: %s", error)

    def consume(self, commander: str, market_id: int, cargo: Dict[str, int]) -> None:
        """Remove work immediately before its first HTTP attempt or a known ineligible discard."""
        with self._lock:
            updated = self._changed(commander, market_id, cargo, -1)
            self._write(updated)
            self._pending = updated

    def _changed(self, commander: str, market_id: int, cargo: Dict[str, int], sign: int) -> Pending:
        updated = copy.deepcopy(self._pending)
        markets = updated.setdefault(commander, {})
        pending = markets.setdefault(int(market_id), {})
        for key, amount in cargo.items():
            pending[key] = pending.get(key, 0) + sign * int(amount)
            if not pending[key]:
                pending.pop(key)
        if not pending:
            markets.pop(int(market_id))
        if not markets:
            updated.pop(commander)
        return updated

    def _write(self, pending: Pending) -> None:
        if self._path is None:
            return
        temporary = self._path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(pending, sort_keys=True), encoding="utf-8")
        temporary.replace(self._path)
