"""Fleet Carrier Market.json parsing and partial stock sync (SrvSurvey-XP parity)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

try:
    from .api.client import normalize_commodity_key
except ImportError:  # pragma: no cover - standalone test/module loading
    from api.client import normalize_commodity_key

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MarketItemSnapshot:
    """Normalized market row read from Elite Dangerous Market.json."""

    commodity: str
    stock: int
    producer: bool
    consumer: bool


@dataclass(frozen=True)
class FleetCarrierMarketSnapshot:
    """Parsed Market.json payload for a Fleet Carrier market view."""

    market_id: int
    timestamp: str
    items: tuple[MarketItemSnapshot, ...]


def _coerce_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_market_items(raw_items: Any) -> tuple[MarketItemSnapshot, ...]:
    if not isinstance(raw_items, list):
        return ()
    parsed: list[MarketItemSnapshot] = []
    for item in raw_items:
        if not isinstance(item, Mapping):
            continue
        commodity = normalize_commodity_key(str(item.get("Name") or ""))
        if not commodity:
            continue
        stock_val = _coerce_int(item.get("Stock", item.get("stock", 0)))
        if stock_val is None:
            continue
        parsed.append(
            MarketItemSnapshot(
                commodity=commodity,
                stock=max(0, stock_val),
                producer=bool(item.get("Producer", item.get("producer", False))),
                consumer=bool(item.get("Consumer", item.get("consumer", False))),
            )
        )
    return tuple(parsed)


def _find_market_json_path(journal_dir: str) -> Optional[Path]:
    root = Path(journal_dir)
    for name in ("Market.json", "market.json"):
        candidate = root / name
        if candidate.is_file():
            return candidate
    return None


def read_fc_market_snapshot(
    entry: Mapping[str, Any],
    journal_dir: Optional[str],
) -> Optional[FleetCarrierMarketSnapshot]:
    """Read and validate Market.json for a FleetCarrier Market journal event."""
    if not journal_dir:
        return None
    expected_mid = _coerce_int(entry.get("MarketID"))
    if expected_mid is None:
        return None
    path = _find_market_json_path(journal_dir)
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        logger.debug("Market.json read failed for marketId=%s: %s", expected_mid, exc)
        return None
    if not isinstance(data, Mapping):
        return None
    file_mid = _coerce_int(data.get("MarketID"))
    if file_mid != expected_mid:
        logger.debug("Market.json MarketID=%s does not match event MarketID=%s", file_mid, expected_mid)
        return None
    station_type = str(data.get("StationType") or "").strip()
    if station_type and station_type.lower() != "fleetcarrier":
        return None
    raw_items = data.get("Items")
    if raw_items is None:
        raw_items = data.get("Commodities")
    if not isinstance(raw_items, list):
        return None
    timestamp = str(data.get("timestamp") or entry.get("timestamp") or "").strip()
    return FleetCarrierMarketSnapshot(
        market_id=expected_mid,
        timestamp=timestamp,
        items=_parse_market_items(raw_items),
    )


def compute_fc_market_replacements(
    market_items: Iterable[MarketItemSnapshot],
    server_cargo: Mapping[str, Any],
) -> Dict[str, int]:
    """Compute partial POST /api/fc/{marketId}/cargo updates matching SrvSurvey-XP.

    Only commodities listed for sale whose stock differs from server cargo, or
    listed commodities that are neither Producer nor Consumer while server cargo
    still reports positive stock (sold out), are included. Unlisted carrier
    cargo is never touched.
    """
    current_cargo: Dict[str, int] = {}
    for raw_key, raw_value in (server_cargo or {}).items():
        key = normalize_commodity_key(str(raw_key))
        amount = _coerce_int(raw_value)
        if not key or amount is None:
            continue
        current_cargo[key] = current_cargo.get(key, 0) + max(0, amount)

    replacements: Dict[str, int] = {}
    for item in market_items:
        if not item.commodity:
            continue
        stock = max(0, int(item.stock))
        tracked = current_cargo.get(item.commodity, 0)
        if (item.producer and tracked != stock) or (not item.producer and not item.consumer and tracked > 0):
            replacements[item.commodity] = stock
    return replacements
