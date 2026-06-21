#!/usr/bin/env python3
"""Merge v1.7 L10n keys from en.template order into all L10n/*.strings files."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
L10N = ROOT / "L10n"
TRANSLATIONS_JSON = Path(__file__).with_name("l10n_v1_7_translations.json")

NEW_KEYS = [
    "RavenColonialWeb",
    "Enable Overlay",
    "Always On",
    "Select Build Project",
    "Enable Carrier Tracking",
    "All",
    "Select carrier",
    "No Build Projects",
    "Build projects",
    "Build projects error",
    "Build projects refresh failed",
    "Cannot refresh build projects.",
    "Could not load build projects from the API.",
    "Copy Error Msg",
    "OK",
    "Plan sites",
    "Plan sites error",
    "Cannot refresh plan sites.",
    "Commander not ready.",
    "Could not load plan sites from the API.",
    "Could not determine a build name from the dock station or selected plan site.",
    "A completed project record already exists at this station — link cancelled.",
    "Selected site is no longer in plan status ({status}) — link cancelled.",
    "No commander name — wait for LoadGame or restart EDMC with a journal.",
    "Project exists",
    "A build project is now active at this station. Use Open Build Page.",
    "Overlay dependency:",
    "The build tracker overlay requires EDMC Modern Overlay to be installed and enabled in EDMC.",
    "Click here to install custom fonts.",
    "Install overlay fonts",
    "Overlay fonts",
    "Oxanium font installed into EDMC Modern Overlay. Restart EDMC so the overlay client reloads the font.",
    "EDMC Modern Overlay was not found. Install and enable it in EDMC (File → Settings → Plugins), then try again.",
    "Bundled Oxanium font files are missing from this plugin install. "
    "Reinstall RavenColonial_EDMC from the latest release.",
    "Font install did not complete. Check the EDMC log for details.",
    "Font install failed: {error}",
    "Check plugin settings for dependency.",
    "Overlay Theme:",
    "Colors the in-game overlay: build name and trip lines, system name, commodity names, and numeric columns.",
]


def _encode_strings_escapes(s: str) -> str:
    """Encode one logical string for a single-line EDMC .strings entry."""
    out: list[str] = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "\n":
            out.append("\\n")
            i += 1
            continue
        if ch == "\r":
            out.append("\\r")
            i += 1
            continue
        if ch == "\t":
            out.append("\\t")
            i += 1
            continue
        if ch == '"':
            out.append('\\"')
            i += 1
            continue
        if ch == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            if nxt in "nrt\\":
                out.append("\\" + nxt)
                i += 2
                continue
            out.append("\\\\")
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _normalize_strings_token(s: str) -> str:
    """Undo accidental double-escaping from an earlier merge pass."""
    out: list[str] = []
    i = 0
    while i < len(s):
        if s[i] == "\\" and i + 2 < len(s) and s[i + 1] == "\\" and s[i + 2] == "n":
            out.append("\\n")
            i += 3
            continue
        if s[i] == "\\" and i + 2 < len(s) and s[i + 1] == "\\" and s[i + 2] == "r":
            out.append("\\r")
            i += 3
            continue
        if s[i] == "\\" and i + 2 < len(s) and s[i + 1] == "\\" and s[i + 2] == "t":
            out.append("\\t")
            i += 3
            continue
        out.append(s[i])
        i += 1
    return "".join(out)


def parse_strings(path: Path) -> dict[str, str]:
    """Parse key/value pairs; file uses \\n escapes, not literal newlines in keys."""
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip().startswith('"'):
            continue
        parts = line.split('"')
        if len(parts) >= 4:
            key = _normalize_strings_token(parts[1])
            val = _normalize_strings_token(parts[3])
            out[key] = val
    return out


def parse_template_keys(path: Path) -> list[str]:
    keys: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith('"') and '" =' in line:
            keys.append(line.split('"', 2)[1])
    return keys


def read_header(path: Path) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    header: list[str] = []
    for line in lines:
        if line.strip().startswith("/*"):
            header.append(line)
            continue
        if not line.strip():
            if header:
                header.append(line)
            continue
        if line.strip().startswith('"'):
            break
    return "\n".join(header).rstrip() + "\n\n"


def main() -> None:
    locale_new: dict[str, dict[str, str]] = json.loads(
        TRANSLATIONS_JSON.read_text(encoding="utf-8")
    )
    template_keys = parse_template_keys(L10N / "en.template")
    en_template = parse_strings(L10N / "en.template")

    for path in sorted(L10N.glob("*.strings")):
        loc = path.stem
        existing = parse_strings(path)
        new_map = locale_new.get(loc, {})
        if loc == "sr-Latn-BA" and not new_map:
            new_map = locale_new.get("sr-Latn", {})

        merged = dict(existing)
        for key in NEW_KEYS:
            if key in new_map:
                merged[key] = new_map[key]
            elif key not in merged:
                merged[key] = en_template.get(key, key)

        header = read_header(path)
        out_lines = [header.rstrip(), ""]
        for key in template_keys:
            if key not in merged:
                continue
            val = merged[key]
            out_lines.append(f'"{_encode_strings_escapes(key)}" = "{_encode_strings_escapes(val)}";')
        out_lines.append("")
        path.write_text("\n".join(out_lines), encoding="utf-8")
        print(f"Updated {path.name} ({len(template_keys)} entries)")


if __name__ == "__main__":
    main()
