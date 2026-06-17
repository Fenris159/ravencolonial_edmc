#!/usr/bin/env python3
"""
Patch overlay + commodity l10n into L10n/*.strings for Latin/Cyrillic locales only.

- Overlay UI (trips, headers, categories without EDDI): Google Translate from en.overlay.template msgstr.
- Commodity + market category names: EDDI game strings (EDCD/EDDI Commodities*.resx) when available;
  Google Translate fallback for gaps (partial EDDI locales, cs/fi/pl/…).

Skips ja, ko, zh-Hans (overlay keeps English fallback via tr()).

  python scripts/refresh_overlay_l10n.py
  python scripts/refresh_overlay_l10n.py --only de,fr,ru
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET  # nosec B405
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_plugin_l10n import (  # noqa: E402
    LANG_STEMS,
    TRANS_RE,
    escape_strings,
    parse_template,
    translate_rows_google,
    unescape_strings,
)

EDDI_BASE = (
    "https://raw.githubusercontent.com/EDCD/EDDI/develop/DataDefinitions/Properties"
)
FDEV_COMMODITY_URL = "https://raw.githubusercontent.com/EDCD/FDevIDs/master/commodity.csv"

# Plugin locales using Latin or Cyrillic scripts (overlay translation target).
LATIN_CYRILLIC_STEMS = frozenset(
    stem for stem, _ in LANG_STEMS if stem not in {"ja", "ko", "zh-Hans"}
)

# Ravencolonial stem -> EDDI Commodities/CommodityCategories resx suffix (None = no commodity file).
EDDI_LANG_MAP: dict[str, str | None] = {
    "cs": None,
    "de": "de",
    "es": "es",
    "fi": None,
    "fr": "fr",
    "hu": "hu",
    "it": "it",
    "lv": None,
    "nl": None,
    "pl": None,
    "pt-BR": "pt-BR",
    "pt-PT": "pt-PT",
    "ru": "ru",
    "sl": None,
    "sr-Latn-BA": None,
    "sr-Latn": None,
    "sv-SE": None,
    "tr": None,
    "uk": None,
}

# Google Translate target for each plugin stem (same as generate_plugin_l10n.py).
GOOGLE_BY_STEM = dict(LANG_STEMS)

# Overlay category key (English label) -> EDDI CommodityCategories resource name.
CATEGORY_EDDI_ALIAS: dict[str, str] = {
    "Legal Drugs": "Narcotics",
    "Other": "Unknown",
}

OVERLAY_CATEGORY_KEYS = frozenset(
    {
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
    }
)


def _safe_print(text: str) -> None:
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        print(text.encode("ascii", "backslashreplace").decode("ascii"), flush=True)


def fetch_resx(url: str) -> dict[str, str]:
    text = urllib.request.urlopen(url, timeout=90).read().decode("utf-8")  # nosec B310
    root = ET.fromstring(text)  # nosec B314
    out: dict[str, str] = {}
    for node in root.findall("data"):
        name = node.get("name")
        val = node.find("value")
        if name and val is not None and val.text:
            out[name] = val.text.strip()
    return out


def load_eddi_tables() -> tuple[dict[str, str], dict[str, str], dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    """Return English category maps + per-EDDI-lang commodity/category tables."""
    en_commodities = fetch_resx(f"{EDDI_BASE}/Commodities.resx")
    en_categories = fetch_resx(f"{EDDI_BASE}/CommodityCategories.resx")
    cat_value_to_eddi_key = {v: k for k, v in en_categories.items()}

    eddi_langs = sorted({v for v in EDDI_LANG_MAP.values() if v})
    commodities_by_lang: dict[str, dict[str, str]] = {"en": en_commodities}
    categories_by_lang: dict[str, dict[str, str]] = {"en": en_categories}

    for eddi_lang in eddi_langs:
        try:
            commodities_by_lang[eddi_lang] = fetch_resx(
                f"{EDDI_BASE}/Commodities.{eddi_lang}.resx"
            )
        except Exception as exc:
            _safe_print(f"  warn: Commodities.{eddi_lang}.resx unavailable: {exc}")
            commodities_by_lang[eddi_lang] = {}
        try:
            categories_by_lang[eddi_lang] = fetch_resx(
                f"{EDDI_BASE}/CommodityCategories.{eddi_lang}.resx"
            )
        except Exception as exc:
            _safe_print(f"  warn: CommodityCategories.{eddi_lang}.resx unavailable: {exc}")
            categories_by_lang[eddi_lang] = {}

    # EDDI pt-PT commodity resx is empty; European Portuguese uses Brazilian game strings.
    if not commodities_by_lang.get("pt-PT") and commodities_by_lang.get("pt-BR"):
        commodities_by_lang["pt-PT"] = commodities_by_lang["pt-BR"]
    if not categories_by_lang.get("pt-PT") and categories_by_lang.get("pt-BR"):
        categories_by_lang["pt-PT"] = categories_by_lang["pt-BR"]

    # Czech has category file but empty commodities — still load categories under 'cs'.
    if "cs" not in categories_by_lang:
        try:
            categories_by_lang["cs"] = fetch_resx(f"{EDDI_BASE}/CommodityCategories.cs.resx")
        except Exception:
            categories_by_lang["cs"] = {}

    return en_commodities, cat_value_to_eddi_key, commodities_by_lang, categories_by_lang


def fdev_symbol_by_lower() -> dict[str, str]:
    text = urllib.request.urlopen(FDEV_COMMODITY_URL, timeout=90).read().decode("utf-8")  # nosec B310
    out: dict[str, str] = {}
    for row in csv.DictReader(StringIO(text)):
        sym = (row.get("symbol") or "").strip()
        cat = (row.get("category") or "").strip()
        if sym and cat != "NonMarketable":
            out[sym.lower()] = sym
    return out


def overlay_template_rows(l10n_dir: Path) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Return (ui_rows, commodity_rows) from overlay templates."""
    ui: list[tuple[str, str]] = []
    commodities: list[tuple[str, str]] = []
    for name in ("en.overlay.template", "en.commodities.template"):
        path = l10n_dir / name
        if not path.exists():
            continue
        for key, val in parse_template(path):
            if key.startswith("commodity:"):
                commodities.append((key, val))
            else:
                ui.append((key, val))
    return ui, commodities


def eddi_category_key(overlay_key: str, cat_value_to_eddi_key: dict[str, str]) -> str | None:
    if overlay_key in CATEGORY_EDDI_ALIAS:
        return CATEGORY_EDDI_ALIAS[overlay_key]
    return cat_value_to_eddi_key.get(overlay_key)


def translate_commodity_key(
    key: str,
    english: str,
    *,
    stem: str,
    symbol_by_lower: dict[str, str],
    commodities_by_lang: dict[str, dict[str, str]],
) -> str | None:
    sym_lower = key.removeprefix("commodity:")
    eddi_sym = symbol_by_lower.get(sym_lower)
    eddi_lang = EDDI_LANG_MAP.get(stem)
    if eddi_sym and eddi_lang:
        translated = commodities_by_lang.get(eddi_lang, {}).get(eddi_sym)
        if translated:
            return translated
    return None


def translate_category_key(
    key: str,
    *,
    stem: str,
    cat_value_to_eddi_key: dict[str, str],
    categories_by_lang: dict[str, dict[str, str]],
) -> str | None:
    eddi_lang = EDDI_LANG_MAP.get(stem) or (stem if stem in categories_by_lang else None)
    if not eddi_lang:
        # Czech categories use cs resx even though EDDI_LANG_MAP commodities is None.
        if stem == "cs":
            eddi_lang = "cs"
        else:
            return None
    eddi_key = eddi_category_key(key, cat_value_to_eddi_key)
    if not eddi_key:
        return None
    return categories_by_lang.get(eddi_lang, {}).get(eddi_key)


def build_translations_for_stem(
    stem: str,
    ui_rows: list[tuple[str, str]],
    commodity_rows: list[tuple[str, str]],
    *,
    symbol_by_lower: dict[str, str],
    cat_value_to_eddi_key: dict[str, str],
    commodities_by_lang: dict[str, dict[str, str]],
    categories_by_lang: dict[str, dict[str, str]],
    delay: float,
) -> dict[str, str]:
    updates: dict[str, str] = {}
    need_mt: list[tuple[str, str]] = []

    for key, english in ui_rows:
        if key in OVERLAY_CATEGORY_KEYS:
            cat = translate_category_key(
                key,
                stem=stem,
                cat_value_to_eddi_key=cat_value_to_eddi_key,
                categories_by_lang=categories_by_lang,
            )
            if cat:
                updates[key] = cat
                continue
        need_mt.append((key, english))

    for key, english in commodity_rows:
        eddi = translate_commodity_key(
            key,
            english,
            stem=stem,
            symbol_by_lower=symbol_by_lower,
            commodities_by_lang=commodities_by_lang,
        )
        if eddi:
            updates[key] = eddi
        else:
            need_mt.append((key, english))

    if need_mt:
        google = GOOGLE_BY_STEM[stem]
        _safe_print(f"  MT fallback: {len(need_mt)} string(s) via {google}")
        values = translate_rows_google(need_mt, google, delay)
        for (key, _), val in zip(need_mt, values):
            updates[key] = val

    return updates


def patch_strings_file(path: Path, updates: dict[str, str]) -> tuple[int, int]:
    """Update or append keys; return (updated, appended)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    seen: set[str] = set()
    out: list[str] = []
    updated = 0
    for line in lines:
        m = TRANS_RE.match(line)
        if not m:
            out.append(line)
            continue
        key = unescape_strings(m.group(1))
        seen.add(key)
        if key in updates:
            out.append(f'"{escape_strings(key)}" = "{escape_strings(updates[key])}";')
            updated += 1
        else:
            out.append(line)

    appended = 0
    append_lines: list[str] = []
    for key, val in sorted(updates.items()):
        if key not in seen:
            append_lines.append(f'"{escape_strings(key)}" = "{escape_strings(val)}";')
            appended += 1
    if append_lines:
        if out and out[-1].strip():
            out.append("")
        out.append("/* Overlay HUD (en.overlay.template + en.commodities.template) */")
        out.extend(append_lines)

    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return updated, appended


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="Comma-separated locale stems (default: all Latin/Cyrillic)")
    ap.add_argument("--delay", type=float, default=0.12)
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    l10n_dir = root / "L10n"
    ui_rows, commodity_rows = overlay_template_rows(l10n_dir)
    if not ui_rows and not commodity_rows:
        print("No overlay template rows found.", file=sys.stderr)
        return 1

    only = {s.strip() for s in args.only.split(",") if s.strip()}
    targets = [s for s in sorted(LATIN_CYRILLIC_STEMS) if not only or s in only]
    if not targets:
        print("No target locales.", file=sys.stderr)
        return 1

    _safe_print(
        f"Overlay l10n: {len(ui_rows)} UI + {len(commodity_rows)} commodity keys -> "
        f"{len(targets)} locale(s)"
    )
    _safe_print("Loading EDDI commodity/category tables …")
    _en_com, cat_value_to_eddi_key, commodities_by_lang, categories_by_lang = load_eddi_tables()
    symbol_by_lower = fdev_symbol_by_lower()

    for stem in targets:
        out_path = l10n_dir / f"{stem}.strings"
        if not out_path.exists():
            _safe_print(f"skip missing {out_path.name}")
            continue
        _safe_print(f"translating -> {stem} …")
        try:
            updates = build_translations_for_stem(
                stem,
                ui_rows,
                commodity_rows,
                symbol_by_lower=symbol_by_lower,
                cat_value_to_eddi_key=cat_value_to_eddi_key,
                commodities_by_lang=commodities_by_lang,
                categories_by_lang=categories_by_lang,
                delay=args.delay,
            )
        except Exception as exc:
            print(f"FAILED {stem}: {exc}", file=sys.stderr)
            return 1
        eddi_hits = sum(
            1
            for k in updates
            if k.startswith("commodity:") or k in OVERLAY_CATEGORY_KEYS
        )
        n_up, n_add = patch_strings_file(out_path, updates)
        _safe_print(
            f"  {out_path.name}: {len(updates)} entries "
            f"({n_up} updated, {n_add} appended; ~{eddi_hits} from EDDI where available)"
        )
        time.sleep(0.05)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
