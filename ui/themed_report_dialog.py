"""
Themed small Toplevel for plan-site (and similar) errors — GalaxyGPS-style ``tk`` + EDMC theme.

Avoids stuffing long API strings into narrow comboboxes (which widens the EDMC window).
"""

from __future__ import annotations

import logging
import sys
import tkinter as tk
from tkinter import ttk

from .edmc_theme import apply_theme_to_widget_subtree

logger = logging.getLogger(__name__)


def _safe_modal_grab(top: tk.Toplevel) -> None:
    """
    Apply a modal grab after the window is mapped.

    Calling ``grab_set`` before the toplevel is visible can leave a stray grab on Linux
    (X11/Wayland), which makes the rest of EDMC ignore mouse clicks until EDMC restarts.
    """
    try:
        top.update_idletasks()
        top.wait_visibility()
    except tk.TclError as exc:
        logger.debug("Dialog not visible before grab: %s", exc)
    try:
        top.grab_set()
    except tk.TclError as exc:
        logger.warning("Could not grab dialog (modal behaviour may be reduced): %s", exc)
        return
    if sys.platform.startswith("linux"):
        try:
            top.lift()
            top.focus_force()
        except tk.TclError:
            pass


def _configure_toplevel_background(top: tk.Toplevel) -> None:
    try:
        from theme import theme  # type: ignore[import-untyped]

        if getattr(theme, "current", None):
            top.configure(bg=theme.current["background"])
    except (ImportError, tk.TclError, KeyError, TypeError):
        try:
            shell = ttk.Style().lookup("TFrame", "background")
            if shell:
                top.configure(bg=shell)
        except tk.TclError:
            pass


def _center_toplevel_on_parent(top: tk.Toplevel, parent: tk.Misc) -> None:
    top.update_idletasks()
    try:
        pw = parent.winfo_toplevel()
        px = pw.winfo_rootx()
        py = pw.winfo_rooty()
        pw_w = pw.winfo_width()
        ph_h = pw.winfo_height()
        tw = top.winfo_reqwidth()
        th = top.winfo_reqheight()
        x = max(0, px + (pw_w - tw) // 2)
        y = max(0, py + (ph_h - th) // 3)
        top.geometry(f"+{x}+{y}")
    except tk.TclError:
        pass


def _release_and_destroy(top: tk.Toplevel) -> None:
    try:
        top.grab_release()
    except tk.TclError:
        pass
    top.destroy()


def _finalize_modal_dialog(top: tk.Toplevel, ok_handler, focus_widget: tk.Widget) -> None:
    top.protocol("WM_DELETE_WINDOW", ok_handler)
    focus_widget.focus_set()
    _safe_modal_grab(top)


def show_themed_report_dialog(
    parent: tk.Misc,
    *,
    title: str,
    summary: str,
    detail: str,
    copy_button_text: str,
    ok_button_text: str,
) -> None:
    """Modal dialog: ``summary`` + scrollable ``detail``; copy uses full ``detail`` text."""
    top = tk.Toplevel(parent)
    top.title(title)
    top.resizable(True, True)
    top.minsize(360, 180)
    try:
        top.transient(parent.winfo_toplevel())
    except tk.TclError:
        pass

    _configure_toplevel_background(top)

    outer = tk.Frame(top, padx=14, pady=14)
    outer.pack(fill=tk.BOTH, expand=True)
    outer.columnconfigure(0, weight=1)
    outer.rowconfigure(1, weight=1)

    sum_lbl = tk.Label(
        outer,
        text=summary,
        anchor="w",
        justify=tk.LEFT,
        wraplength=440,
    )
    sum_lbl.grid(row=0, column=0, sticky="ew", pady=(0, 8))

    body = (detail or "").strip()
    clipboard_payload = "\n\n".join(
        x for x in (title.strip(), summary.strip(), body) if x
    ).strip()

    text_frame = tk.Frame(outer)
    text_frame.grid(row=1, column=0, sticky="nsew", pady=(0, 12))
    text_frame.columnconfigure(0, weight=1)
    text_frame.rowconfigure(0, weight=1)

    txt = tk.Text(text_frame, height=10, width=56, wrap=tk.WORD, relief=tk.FLAT, borderwidth=1)
    scroll = tk.Scrollbar(text_frame, command=txt.yview)
    txt.configure(yscrollcommand=scroll.set)
    txt.grid(row=0, column=0, sticky="nsew")
    scroll.grid(row=0, column=1, sticky="ns")
    txt.insert("1.0", body)
    txt.configure(state=tk.DISABLED)

    btn_row = tk.Frame(outer)
    btn_row.grid(row=2, column=0, sticky="ew")

    def _copy() -> None:
        top.clipboard_clear()
        top.clipboard_append(clipboard_payload)
        top.update_idletasks()

    def _ok() -> None:
        _release_and_destroy(top)

    copy_btn = tk.Button(btn_row, text=copy_button_text, command=_copy)
    copy_btn.pack(side=tk.LEFT)
    ok_btn = tk.Button(btn_row, text=ok_button_text, command=_ok, width=10)
    ok_btn.pack(side=tk.RIGHT)

    try:
        copy_btn.configure(cursor="hand2")
        ok_btn.configure(cursor="hand2")
    except tk.TclError:
        pass

    apply_theme_to_widget_subtree(top)
    _center_toplevel_on_parent(top, parent)
    _finalize_modal_dialog(top, _ok, ok_btn)


def show_themed_alert_dialog(
    parent: tk.Misc,
    *,
    title: str,
    message: str,
    ok_button_text: str,
) -> None:
    """Compact themed modal with a single message and OK button."""
    top = tk.Toplevel(parent)
    top.title(title)
    top.resizable(False, False)
    top.minsize(280, 100)
    try:
        top.transient(parent.winfo_toplevel())
    except tk.TclError:
        pass

    _configure_toplevel_background(top)

    outer = tk.Frame(top, padx=14, pady=14)
    outer.pack(fill=tk.BOTH, expand=True)
    outer.columnconfigure(0, weight=1)

    msg_lbl = tk.Label(
        outer,
        text=message,
        anchor="w",
        justify=tk.LEFT,
        wraplength=420,
    )
    msg_lbl.grid(row=0, column=0, sticky="ew", pady=(0, 12))

    btn_row = tk.Frame(outer)
    btn_row.grid(row=1, column=0, sticky="e")

    def _ok() -> None:
        _release_and_destroy(top)

    ok_btn = tk.Button(btn_row, text=ok_button_text, command=_ok, width=10)
    ok_btn.pack(side=tk.RIGHT)
    try:
        ok_btn.configure(cursor="hand2")
    except tk.TclError:
        pass

    apply_theme_to_widget_subtree(top)
    _center_toplevel_on_parent(top, parent)
    _finalize_modal_dialog(top, _ok, ok_btn)
