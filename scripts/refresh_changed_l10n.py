#!/usr/bin/env python3
"""
Re-translate en.template rows whose English display text (msgstr) differs from the lookup key.

Use after editing msgstr values in en.template (e.g. site -> location wording) without changing
tr() keys. Patches existing L10n/*.strings in place.

  python scripts/refresh_changed_l10n.py
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

# Reuse generator helpers
sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_plugin_l10n import (  # noqa: E402
    LANG_STEMS,
    TRANS_RE,
    escape_strings,
    load_all_template_rows,
    translate_rows_google,
    unescape_strings,
)


def _safe_print(text: str) -> None:
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        print(text.encode("ascii", "backslashreplace").decode("ascii"), flush=True)


def patch_strings_file(path: Path, updates: dict[str, str]) -> int:
    """Replace values for known keys; return count patched."""
    lines = path.read_text(encoding="utf-8").splitlines()
    patched = 0
    out: list[str] = []
    for line in lines:
        m = TRANS_RE.match(line)
        if not m:
            out.append(line)
            continue
        key = unescape_strings(m.group(1))
        if key in updates:
            out.append(f'"{escape_strings(key)}" = "{escape_strings(updates[key])}";')
            patched += 1
        else:
            out.append(line)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return patched


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    l10n_dir = root / "L10n"
    rows = load_all_template_rows(l10n_dir)
    changed = [(k, v) for k, v in rows if k != v]
    if not changed:
        print("No msgstr changes detected (all keys match English display text).")
        return 0

    _safe_print(f"Refreshing {len(changed)} changed English string(s) across locales:")
    for key, val in changed:
        preview = val.replace("\n", "\\n")
        if len(preview) > 72:
            preview = preview[:69] + "..."
        _safe_print(f"  - {preview!r}")

    l10n_dir = root / "L10n"
    delay = 0.12
    for stem, google_target in LANG_STEMS:
        _safe_print(f"translating -> {stem} ({google_target}) ...")
        try:
            values = translate_rows_google(changed, google_target, delay)
        except Exception as exc:
            print(f"FAILED {stem}: {exc}", file=sys.stderr)
            return 1
        updates = {k: v for (k, _), v in zip(changed, values)}
        out_path = l10n_dir / f"{stem}.strings"
        n = patch_strings_file(out_path, updates)
        _safe_print(f"  patched {n} entries in {out_path.name}")
        time.sleep(0.05)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
