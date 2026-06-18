"""Elite market commodity categories (EDCD FDevIDs, in-game market tab order)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Tuple

try:
    from ..api.client import normalize_commodity_key
except ImportError:  # pragma: no cover
    from api.client import normalize_commodity_key

# In-game Commodities market tab order (trade goods); Salvage last; unknowns under Other.
MARKET_CATEGORY_ORDER: Tuple[str, ...] = (
    "Chemicals",
    "Consumer Items",
    "Foods",
    "Industrial Materials",
    "Legal Drugs",
    "Machinery",
    "Medicines",
    "Metals",
    "Minerals",
    "Slavery",
    "Technology",
    "Textiles",
    "Waste",
    "Weapons",
    "Salvage",
    "Other",
)

_CATEGORY_RANK = {name: idx for idx, name in enumerate(MARKET_CATEGORY_ORDER)}
_OTHER = "Other"
_DATA_FILE = Path(__file__).resolve().parent / "fdev_commodity_categories.json"


@lru_cache(maxsize=1)
def _load_fdev_category_map() -> Dict[str, str]:
    try:
        raw = json.loads(_DATA_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, str] = {}
    for key, value in raw.items():
        if isinstance(key, str) and isinstance(value, str) and key and value:
            out[key.lower()] = value
    return out


def _lookup_variants(normalized_key: str) -> List[str]:
    variants = [normalized_key]
    collapsed = normalized_key.replace("_", "")
    if collapsed != normalized_key:
        variants.append(collapsed)
    return variants


def category_for_commodity_key(key: str) -> str:
    """Return market category for a RavenColonial / journal commodity key."""
    nk = normalize_commodity_key(str(key))
    if not nk:
        return _OTHER
    fdev = _load_fdev_category_map()
    for variant in _lookup_variants(nk):
        cat = fdev.get(variant)
        if cat:
            return cat
    return _OTHER


def category_sort_key(category: str) -> int:
    return _CATEGORY_RANK.get(category, _CATEGORY_RANK[_OTHER])


def format_category_separator(category: str, width: int) -> str:
    """Groove-style category line (text overlay; no vector drawing)."""
    try:
        from .l10n_helpers import tr_category
    except ImportError:  # pragma: no cover
        try:
            from overlay.l10n_helpers import tr_category  # type: ignore[no-redef]
        except ImportError:
            from l10n_helpers import tr_category  # type: ignore[no-redef]
    label = tr_category(category)
    if width < len(label) + 4:
        return f"-- {label} --"
    pad = max(2, (width - len(label) - 2) // 2)
    line = ("-" * pad) + f" {label} " + ("-" * pad)
    if len(line) < width:
        line += "-" * (width - len(line))
    return line[:width]
