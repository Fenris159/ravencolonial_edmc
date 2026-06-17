#!/usr/bin/env python3
"""Regenerate overlay/fdev_commodity_categories.json from EDCD FDevIDs commodity.csv."""

from __future__ import annotations

import csv
import json
import urllib.request
from pathlib import Path

FDEV_URL = "https://raw.githubusercontent.com/EDCD/FDevIDs/master/commodity.csv"
OUT = Path(__file__).resolve().parents[1] / "overlay" / "fdev_commodity_categories.json"


def main() -> None:
    with urllib.request.urlopen(FDEV_URL, timeout=60) as resp:  # nosec B310
        text = resp.read().decode("utf-8")
    mapping: dict[str, str] = {}
    for row in csv.DictReader(text.splitlines()):
        sym = (row.get("symbol") or "").strip()
        cat = (row.get("category") or "").strip()
        if not sym or not cat or cat == "NonMarketable":
            continue
        mapping[sym.lower()] = cat
    OUT.write_text(json.dumps(mapping, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {len(mapping)} commodities to {OUT}")


if __name__ == "__main__":
    main()
