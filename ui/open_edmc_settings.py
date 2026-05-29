"""Open EDMC's settings dialog on this plugin's preferences tab."""

from __future__ import annotations

import logging
import tkinter as tk
from typing import Callable, Iterator, Optional

logger = logging.getLogger(__name__)


def _walk_widgets(root: tk.Misc) -> Iterator[tk.Misc]:
    try:
        children = list(root.winfo_children())
    except tk.TclError:
        return
    for child in children:
        yield child
        yield from _walk_widgets(child)


def _find_settings_notebook(dialog: tk.Misc) -> Optional[tk.Widget]:
    for w in _walk_widgets(dialog):
        if w.__class__.__name__ == "ScrollableNotebook":
            return w
    return None


def _find_open_settings_dialog(edmc_root: tk.Misc) -> Optional[tk.Toplevel]:
    """Return an open EDMC ``PreferencesDialog`` (localized title or not)."""
    for w in edmc_root.winfo_children():
        if not isinstance(w, tk.Toplevel):
            continue
        try:
            if not w.winfo_exists():
                continue
        except tk.TclError:
            continue
        if _find_settings_notebook(w) is not None:
            return w
    return None


def _resolve_postprefs(edmc_root: tk.Misc) -> Optional[Callable[..., None]]:
    """
    EDMC binds ``postprefs`` on ``AppWindow``, not the ``tk.Tk`` root.

    ``PreferencesDialog`` accepts ``callback=None``; opening settings still works,
    and ``plug.notify_prefs_changed`` runs on OK. Return ``None`` when EDMC did not
    attach the callback to the root (normal on EDMC 6.x).
    """
    return getattr(edmc_root, "postprefs", None)


def select_plugin_prefs_tab(notebook: tk.Widget, plugin_tab_name: str) -> bool:
    """Select the notebook tab whose label matches the plugin folder display name."""
    want = plugin_tab_name.casefold()
    try:
        for tab_id in notebook.tabs():
            if str(notebook.tab(tab_id, "text")).casefold() == want:
                notebook.select(tab_id)
                try:
                    notebook.see(tab_id)
                except (tk.TclError, AttributeError):
                    pass
                return True
    except tk.TclError as e:
        logger.debug("Could not select plugin prefs tab %r: %s", plugin_tab_name, e)
    return False


def open_plugin_settings_tab(
    plugin_tab_name: str,
    *,
    parent_widget: tk.Widget,
    postprefs: Optional[Callable[..., None]] = None,
) -> None:
    """
    Show EDMC File → Settings and select this plugin's tab (``plugin_start3`` / folder name).

    Uses EDMC's ``prefs.PreferencesDialog`` when running inside EDMC; no-op with a log line otherwise.
    """
    try:
        import prefs  # type: ignore[import-untyped]  # EDMC runtime module
    except ImportError:
        logger.warning("EDMC prefs module not available — cannot open settings")
        return

    edmc_root = parent_widget.winfo_toplevel()
    if postprefs is None:
        postprefs = _resolve_postprefs(edmc_root)

    dialog = _find_open_settings_dialog(edmc_root)
    if dialog is None:
        try:
            prefs.PreferencesDialog(edmc_root, postprefs)
        except Exception as e:
            logger.exception("Failed to open EDMC settings: %s", e)
            return
        dialog = _find_open_settings_dialog(edmc_root)
        if dialog is None:
            return
    else:
        try:
            dialog.deiconify()
            dialog.lift()
            dialog.focus_force()
        except tk.TclError:
            pass

    notebook = _find_settings_notebook(dialog)
    if notebook is None:
        logger.debug("Settings dialog has no ScrollableNotebook")
        return

    def _select() -> None:
        if not select_plugin_prefs_tab(notebook, plugin_tab_name):
            logger.info(
                "Plugin settings tab %r not found in EDMC settings", plugin_tab_name
            )

    try:
        dialog.after(0, _select)
    except tk.TclError:
        _select()
