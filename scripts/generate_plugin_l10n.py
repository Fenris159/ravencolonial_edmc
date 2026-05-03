#!/usr/bin/env python3
"""
Build plugin L10n/*.strings from L10n/en.template using Google Translate (deep-translator).

Run from repo root:
  python scripts/generate_plugin_l10n.py

Requires: pip install deep-translator

EDMC language file stems match https://github.com/EDCD/EDMarketConnector/tree/main/L10n
(excluding en.template). "uwu" is copied verbatim from English (EDMC joke locale).
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

# Same pattern as EDMC l10n.Translations.TRANS_RE
TRANS_RE = re.compile(r'\s*"((?:[^"]|\\")+)"\s*=\s*"((?:[^"]|\\")+)"\s*;\s*$')
COMMENT_RE = re.compile(r"\s*/\*.*\*/\s*$")

# EDMC plugin L10n stems (23 files beside en.template)
LANG_STEMS: list[tuple[str, str | None]] = [
    ("cs", "cs"),
    ("de", "de"),
    ("es", "es"),
    ("fi", "fi"),
    ("fr", "fr"),
    ("hu", "hu"),
    ("it", "it"),
    ("ja", "ja"),
    ("ko", "ko"),
    ("lv", "lv"),
    ("nl", "nl"),
    ("pl", "pl"),
    ("pt-BR", "pt"),
    ("pt-PT", "pt"),
    ("ru", "ru"),
    ("sl", "sl"),
    # Latin-script files: use Croatian (Latin) — Google "sr" returns Cyrillic.
    ("sr-Latn-BA", "hr"),
    ("sr-Latn", "hr"),
    ("sv-SE", "sv"),
    ("tr", "tr"),
    ("uk", "uk"),
    ("uwu", None),  # copy English
    ("zh-Hans", "zh-CN"),
]


def unescape_strings(s: str) -> str:
    return s.replace(r"\"", '"')


def escape_strings(s: str) -> str:
    return s.replace('"', r"\"")


def parse_template(path: Path) -> list[tuple[str, str]]:
    """Return list of (msgid, msgstr) from en.template (msgstr is English default)."""
    rows: list[tuple[str, str]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip("\n")
        stripped = line.strip()
        if not stripped or stripped.startswith("/*") or stripped.startswith("*") or stripped.startswith("*/"):
            continue
        if not stripped.startswith('"'):
            continue
        m = TRANS_RE.match(line)
        if not m:
            print(f"skip (unparsed): {line[:80]!r}", file=sys.stderr)
            continue
        key = unescape_strings(m.group(1))
        val = unescape_strings(m.group(2))
        rows.append((key, val))
    return rows


_PLACEHOLDER_RE = re.compile(r"(\{[a-zA-Z_][a-zA-Z0-9_]*\})")


def protect_braces(text: str) -> tuple[str, list[str]]:
    """Replace {name} tokens so MT does not corrupt them."""
    found: list[str] = []

    def repl(m: re.Match[str]) -> str:
        found.append(m.group(1))
        return f"⟦{len(found) - 1}⟧"

    return _PLACEHOLDER_RE.sub(repl, text), found


def restore_braces(text: str, found: list[str]) -> str:
    out = text
    for i, tok in enumerate(found):
        out = out.replace(f"⟦{i}⟧", tok)
    return out


def translate_rows_google(
    rows: list[tuple[str, str]], target: str, delay: float
) -> list[str]:
    from deep_translator import GoogleTranslator

    translator = GoogleTranslator(source="en", target=target)
    keys = [k for k, _ in rows]
    protected: list[tuple[str, list[str]]] = [protect_braces(k) for k in keys]
    to_send = [p for p, _ in protected]

    # Batch in chunks to reduce HTTP calls
    batch_size = 25
    translated_chunks: list[str] = []
    for i in range(0, len(to_send), batch_size):
        chunk = to_send[i : i + batch_size]
        try:
            batch = translator.translate_batch(chunk)
        except Exception:
            batch = []
            for one in chunk:
                try:
                    batch.append(translator.translate(one))
                except Exception:
                    batch.append(one)  # fall back to English
                time.sleep(delay)
        else:
            time.sleep(delay)
        if isinstance(batch, str):
            batch = [batch]
        translated_chunks.extend(batch)

    if len(translated_chunks) != len(keys):
        raise RuntimeError(f"Length mismatch: got {len(translated_chunks)}, expected {len(keys)}")

    out: list[str] = []
    for t_raw, (_, ph_list) in zip(translated_chunks, protected):
        t = restore_braces(t_raw.strip() if isinstance(t_raw, str) else str(t_raw), ph_list)
        out.append(t)
    return out


def write_strings(path: Path, rows: list[tuple[str, str]], header: str) -> None:
    lines = [header.rstrip(), ""]
    for key, val in rows:
        lines.append(f'"{escape_strings(key)}" = "{escape_strings(val)}";')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Parse only; do not write or call APIs")
    ap.add_argument("--delay", type=float, default=0.12, help="Seconds between batch requests")
    ap.add_argument(
        "--resume",
        action="store_true",
        help="Skip language files that already exist (continue an interrupted run).",
    )
    ap.add_argument(
        "--only",
        type=str,
        default="",
        help="Comma-separated stems to generate (e.g. sr-Latn,de). Empty = all.",
    )
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    template = root / "L10n" / "en.template"
    if not template.exists():
        print(f"Missing {template}", file=sys.stderr)
        return 1

    rows = parse_template(template)
    if not rows:
        print("No entries parsed from en.template", file=sys.stderr)
        return 1

    if args.dry_run:
        print(f"Parsed {len(rows)} entries from {template}")
        return 0

    l10n_dir = root / "L10n"
    l10n_dir.mkdir(parents=True, exist_ok=True)

    only_set = {s.strip() for s in args.only.split(",") if s.strip()} if args.only else set()

    for stem, google_target in LANG_STEMS:
        if only_set and stem not in only_set:
            continue
        out_path = l10n_dir / f"{stem}.strings"
        if args.resume and out_path.exists() and out_path.stat().st_size > 50:
            print(f"skip existing {out_path.name}")
            continue
        if google_target is None:
            # uwu: keep English strings (EDMC parody locale; translators can edit manually)
            header = f"/* Ravencolonial EDMC Plugin — {stem} (same as English; customize for parody locale). */"
            write_strings(out_path, rows, header)
            print(f"wrote {out_path.name} (English copy)")
            continue

        print(f"translating -> {stem} ({google_target}) ...", flush=True)
        try:
            values = translate_rows_google(rows, google_target, args.delay)
        except Exception as e:
            print(f"FAILED {stem}: {e}", file=sys.stderr)
            return 1
        out_rows = [(k, v) for (k, _), v in zip(rows, values)]
        note = (
            " (Croatian Latin proxy for sr-Latn*; replace with proper Serbian Latin if available)."
            if stem.startswith("sr-Latn")
            else ""
        )
        header = (
            f"/* Ravencolonial EDMC Plugin — {stem} "
            f"(machine-translated from English; review by a native speaker).{note} */"
        )
        write_strings(out_path, out_rows, header)
        print(f"wrote {out_path.name}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
