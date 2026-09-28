"""Remove X11 decorations while retaining a managed, taskbar-visible Tk window."""

from __future__ import annotations

import ctypes
import logging
import tkinter as tk
from typing import Any

logger = logging.getLogger(__name__)


def _x11_library() -> Any:
    """Bind the Xlib calls used for the same decoration hint as EDMC's theme."""
    library = ctypes.CDLL("libX11.so.6")
    xid = ctypes.c_ulong
    display = ctypes.c_void_p
    signatures = {
        "XOpenDisplay": ([ctypes.c_char_p], display),
        "XCloseDisplay": ([display], ctypes.c_int),
        "XInternAtom": ([display, ctypes.c_char_p, ctypes.c_int], xid),
        "XQueryTree": (
            [display, xid, ctypes.POINTER(xid), ctypes.POINTER(xid),
             ctypes.POINTER(ctypes.POINTER(xid)), ctypes.POINTER(ctypes.c_uint)],
            ctypes.c_int,
        ),
        "XChangeProperty": (
            [display, xid, xid, xid, ctypes.c_int, ctypes.c_int,
             ctypes.POINTER(ctypes.c_ubyte), ctypes.c_int],
            ctypes.c_int,
        ),
        "XFree": ([ctypes.c_void_p], ctypes.c_int),
        "XFlush": ([display], ctypes.c_int),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(library, name)
        function.argtypes = arguments
        function.restype = result
    return library


def hide_x11_decorations(window: tk.Toplevel) -> bool:
    """Request no native border on X11/XWayland without bypassing the window manager."""
    try:
        if window.tk.call("tk", "windowingsystem") != "x11":
            return False
        library = _x11_library()
        display = library.XOpenDisplay(str(window.winfo_screen()).encode("utf-8"))
        if not display:
            return False
    except (AttributeError, OSError, tk.TclError):
        logger.debug("X11 decoration hints unavailable", exc_info=True)
        return False

    children = ctypes.POINTER(ctypes.c_ulong)()
    try:
        window.update_idletasks()
        root = ctypes.c_ulong()
        wrapper = ctypes.c_ulong()
        count = ctypes.c_uint()
        # Tk's content window is a child of the toplevel wrapper owned by the WM.
        if not library.XQueryTree(
            display, window.winfo_id(), ctypes.byref(root), ctypes.byref(wrapper),
            ctypes.byref(children), ctypes.byref(count),
        ) or not wrapper.value:
            return False
        atom = library.XInternAtom(display, b"_MOTIF_WM_HINTS", False)
        if not atom:
            return False
        # MWM_HINTS_DECORATIONS (2), decorations=0; keep the WM's normal functions.
        hints = (ctypes.c_ulong * 5)(2, 0, 0, 0, 0)
        library.XChangeProperty(
            display, wrapper.value, atom, atom, 32, 0,
            ctypes.cast(hints, ctypes.POINTER(ctypes.c_ubyte)), 5,
        )
        library.XFlush(display)
        return True
    except (AttributeError, OSError, tk.TclError):
        logger.debug("Could not remove X11 window decorations", exc_info=True)
        return False
    finally:
        if children:
            library.XFree(children)
        library.XCloseDisplay(display)
