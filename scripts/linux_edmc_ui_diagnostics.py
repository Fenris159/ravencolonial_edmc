#!/usr/bin/env python3
"""
Ravencolonial EDMC — Linux UI troubleshooting helpers.

Run inside the same Python environment as EDMC (so ``tkinter`` and EDMC modules work):

    python3 scripts/linux_edmc_ui_diagnostics.py

Or paste sections into EDMC's Python console after the plugin has loaded.

Checks:
  - Tcl/Tk version and platform
  - EDMC UI theme id (0 = default/light — plan-site combobox must show readable options)
  - Whether a modal grab is currently active (common cause of "dead" clicks)
  - Plugin config flags added in v1.7.0 overlay UI
  - Recent EDMC log lines mentioning Ravencolonial / TclError / grab
"""

from __future__ import annotations

import os
import platform
import re
import sys
import tempfile
from pathlib import Path


def _plugin_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _edmc_log_candidates() -> list[Path]:
    home = Path.home()
    return [
        home / ".local" / "share" / "EDMarketConnector" / "EDMarketConnector.log",
        home / ".local" / "share" / "EDMarketConnector" / "logs" / "EDMarketConnector.log",
        Path(os.environ.get("TMPDIR") or tempfile.gettempdir()) / "EDMarketConnector" / "EDMarketConnector.log",
    ]


def print_environment() -> None:
    print("=== Environment ===")
    print(f"Python: {sys.version.split()[0]} ({sys.executable})")
    print(f"Platform: {platform.platform()}")
    try:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        print(f"Tcl/Tk: {tk.Tcl().call('info', 'patchlevel')}")
        root.destroy()
    except Exception as exc:
        print(f"Tcl/Tk: unavailable ({exc})")
    print()


def print_edmc_theme() -> None:
    print("=== EDMC UI theme ===")
    try:
        from config import config  # type: ignore[import-untyped]

        theme_id = config.get_int("theme")
    except Exception as exc:
        print(f"  Could not read theme: {exc}")
        print()
        return
    names = {0: "default/light", 1: "dark", 2: "transparent"}
    print(f"  config theme = {theme_id} ({names.get(theme_id, 'unknown')})")
    print(
        "  Plan-site / overlay combobox popups must show readable text on theme 0.\n"
        "  If the dropdown looks empty on Linux with theme 0, upgrade to current development."
    )
    print()


def print_overlay_config() -> None:
    print("=== Overlay config (v1.7.0+ keys) ===")
    try:
        from config import config  # type: ignore[import-untyped]
    except ImportError:
        print("config module not available (not running inside EDMC).")
        print()
        return
    keys = [
        "ravencolonial_overlay_enabled",
        "ravencolonial_overlay_always_on",
        "ravencolonial_overlay_carrier_tracking",
        "ravencolonial_overlay_fc_selection",
        "ravencolonial_overlay_theme",
    ]
    for key in keys:
        try:
            val = config.get(key)
        except Exception:
            val = "(read error)"
        print(f"  {key} = {val!r}")
    print()


def print_active_grab() -> None:
    print("=== Active Tk grab (if any) ===")
    try:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        grabbed = root.grab_current()
        if grabbed is None:
            print("  No global grab on this test root (EDMC may still hold one on its main window).")
        else:
            print(f"  grab_current: {grabbed!r}")
        root.destroy()
    except Exception as exc:
        print(f"  Could not query grab: {exc}")
    print(
        "If the user reports all EDMC clicks are dead, ask them to restart EDMC once.\n"
        "A stuck grab from a themed dialog (overlay dependency alert, plan-site error)\n"
        "often clears only after restart."
    )
    print()


def tail_ravencolonial_log(max_lines: int = 40) -> None:
    print("=== Recent Ravencolonial / UI log lines ===")
    found = False
    patterns = re.compile(
        r"ravencolonial|RavenColonial|TypeError|grab|TclError|plugin tab|build_row|overlay",
        re.I,
    )
    for path in _edmc_log_candidates():
        if not path.is_file():
            continue
        found = True
        print(f"--- {path} ---")
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            print(f"  (read failed: {exc})")
            continue
        hits = [ln for ln in lines if patterns.search(ln)]
        for ln in hits[-max_lines:]:
            print(ln)
        if not hits:
            print("  (no matching lines)")
        print()
    if not found:
        print("  No EDMC log file found at common Linux paths.")
        print("  Check README for your install layout.")
    print()


def edmc_plugin_probe() -> None:
    """When run under EDMC with the plugin loaded, exercise button callbacks."""
    print("=== In-process plugin probe (EDMC only) ===")
    try:
        from load import this  # type: ignore[import-untyped]
    except ImportError:
        print("  load.this not importable — skip.")
        print()
        return
    if this is None:
        print("  Plugin not loaded (this is None).")
        print()
        return
    ui = getattr(this, "ui_manager", None)
    if ui is None:
        print("  ui_manager missing.")
        print()
        return
    btn = getattr(ui, "create_button", None)
    print(f"  create_button: {btn!r}")
    if btn is not None:
        try:
            print(f"    state={btn.cget('state')!r} command={btn.cget('command')!r}")
        except Exception as exc:
            print(f"    cget failed: {exc}")
    overlay = getattr(ui, "_overlay_row", None)
    if overlay is not None:
        print(f"  overlay build_row callable: {callable(getattr(overlay, 'build_row', None))}")
        print(f"  overlay build_picker_row frame: {getattr(overlay, 'build_picker_row', None)!r}")
    print()


def main() -> None:
    print(f"Plugin root: {_plugin_root()}\n")
    print_environment()
    print_edmc_theme()
    print_overlay_config()
    print_active_grab()
    tail_ravencolonial_log()
    edmc_plugin_probe()
    print("Done.")


if __name__ == "__main__":
    main()
