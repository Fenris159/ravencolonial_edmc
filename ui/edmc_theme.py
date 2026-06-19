"""
Apply EDMC's global ``theme`` to a widget subtree (depth-first, post-order).

EDMC's ``theme.update(widget)`` only calls ``_update_widget`` on the widget and its
*direct* children; nested ``ttk.Frame`` chains are otherwise left without an initial
paint. GalaxyGPS calls ``theme.update`` per widget; we walk the tree so children are
updated before parents, matching that behavior without hand-maintaining every frame.

``theme._update_widget`` is aimed at classic ``tk`` widgets. Calling ``theme.update`` on
``ttk.Button`` / ``ttk.Entry`` / etc. fights the Ttk style engine (flat wrong colors,
bright disabled states on Windows). Skip those; use ``tk.Button`` + ``theme.update`` for
controls that should match plugins like GalaxyGPS (see ``ui/manager.py``).
"""

from __future__ import annotations

import logging
import math
import sys
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import ttk
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

HEADER_FONT_SCALE = 1.125  # 1.5 × 0.75 — RavenColonialWeb title
# Native Windows indicator is ~10–12px; image mode sizes the widget to this graphic (~2×).
CHECKBOX_INDICATOR_PX = 20
OXANIUM_VARIABLE_FILENAME = "Oxanium[wght].ttf"

_oxanium_header_font: Optional[tkfont.Font] = None
_oxanium_header_font_failed = False
_oxanium_font_registered = False
OXANIUM_FAMILY = "Oxanium"
_checkbox_image_cache: dict[tuple[Any, ...], tuple[tk.PhotoImage, tk.PhotoImage]] = {}

# Widget types where theme.update breaks native ttk appearance (EDMC dark theme).
_TTK_SKIP_THEME_UPDATE: tuple[type, ...] = (
    ttk.Button,
    ttk.Checkbutton,
    ttk.Radiobutton,
    ttk.Entry,
    ttk.Combobox,
    ttk.Spinbox,
    ttk.Treeview,
    ttk.Notebook,
    ttk.Progressbar,
    ttk.Scale,
    ttk.Scrollbar,
    ttk.Label,
)

# ``theme.update`` on popup ``Listbox`` widgets breaks contrast on Linux (default theme).
_TK_SKIP_THEME_UPDATE: tuple[type, ...] = (tk.Listbox,)


def _skip_theme_update(widget: tk.Widget) -> bool:
    if isinstance(widget, _TTK_SKIP_THEME_UPDATE + _TK_SKIP_THEME_UPDATE):
        return True
    # ``ThemedCombobox`` entry/button are styled via ``apply_theme_styling`` only.
    return bool(getattr(widget, "_rc_skip_subtree_theme", False))


def apply_theme_to_widget_subtree(root: tk.Widget) -> None:
    """Register and paint ``root`` and descendants with EDMC's active theme."""
    try:
        from theme import theme  # type: ignore[import-untyped]
    except ImportError:
        return
    if not getattr(theme, "current", None):
        return

    def visit(w: tk.Widget) -> None:
        try:
            children = w.winfo_children()
        except tk.TclError:
            children = ()
        for c in children:
            visit(c)
        if _skip_theme_update(w):
            return
        try:
            theme.update(w)
        except (ValueError, TypeError, tk.TclError):
            pass

    visit(root)


def _edmc_theme_is_dark() -> bool:
    try:
        from config import config  # type: ignore[import-untyped]

        return config.get_int("theme") in (1, 2)
    except Exception:
        return False


def _tk_color_to_hex(
    color: object,
    *,
    fallback: str,
    widget: Optional[tk.Widget] = None,
) -> str:
    """Resolve Tk color names/system colors to ``#rrggbb`` for uniform PhotoImage use."""
    raw = str(color or "").strip() or fallback
    candidates = []
    if widget is not None:
        candidates.append(widget)
    root = getattr(tk, "_default_root", None)
    if root is not None:
        candidates.append(root)

    for candidate in candidates:
        try:
            r, g, b = candidate.winfo_rgb(raw)
            return f"#{r // 257:02x}{g // 257:02x}{b // 257:02x}"
        except tk.TclError:
            continue

    if raw.startswith("#") and len(raw) == 7:
        return raw
    return fallback


def _hex_rgb(color: str) -> tuple[int, int, int]:
    h = color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _relative_luminance(color: str) -> float:
    r, g, b = _hex_rgb(color)
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0


def _contrasting_color(background: str) -> str:
    return "#000000" if _relative_luminance(background) > 0.55 else "#ffffff"


def _colors_too_close(a: str, b: str) -> bool:
    ar, ag, ab = _hex_rgb(a)
    br, bg, bb = _hex_rgb(b)
    return abs(ar - br) < 32 and abs(ag - bg) < 32 and abs(ab - bb) < 32


def bundled_oxanium_font_path() -> Optional[Path]:
    """Path to the bundled Oxanium variable font shipped with this plugin."""
    path = (
        Path(__file__).resolve().parents[1]
        / "assets"
        / "fonts"
        / "oxanium"
        / OXANIUM_VARIABLE_FILENAME
    )
    return path if path.is_file() else None


def ensure_bundled_oxanium_font_registered() -> bool:
    """Make the bundled Oxanium family available to Tk when the platform allows it."""
    font_path = bundled_oxanium_font_path()
    if font_path is None:
        return False
    return _register_bundled_oxanium(font_path)


def _register_bundled_oxanium(font_path: Path) -> bool:
    """
    Make bundled Oxanium visible to Tk.

    EDMC's Tcl/Tk build does not support ``Font(file=…)`` (raises ``bad option "-file"``).
    On Windows, register the TTF privately (same approach as EDMC's EUROCAPS font).
    """
    global _oxanium_font_registered
    if _oxanium_font_registered:
        return True

    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            add_font = ctypes.windll.gdi32.AddFontResourceExW
            add_font.argtypes = [wintypes.LPCWSTR, ctypes.c_uint, wintypes.LPVOID]
            add_font.restype = ctypes.c_int
            FR_PRIVATE = 0x10
            if add_font(str(font_path.resolve()), FR_PRIVATE, None) > 0:
                _oxanium_font_registered = True
                logger.debug("Registered Oxanium for Tk from %s", font_path)
                return True
        except (OSError, AttributeError) as exc:
            logger.warning("Could not register Oxanium with GDI: %s", exc)
        return False

    # Linux/macOS: use Oxanium only if already installed system-wide.
    try:
        if OXANIUM_FAMILY in tkfont.families():
            _oxanium_font_registered = True
            return True
    except tk.TclError:
        pass
    return False


def _unregister_bundled_oxanium(font_path: Path) -> bool:
    """Release the private Windows font registration so the plugin folder can be replaced."""
    global _oxanium_font_registered
    if not _oxanium_font_registered:
        return True
    if sys.platform != "win32":
        _oxanium_font_registered = False
        return True
    try:
        import ctypes
        from ctypes import wintypes

        remove_font = ctypes.windll.gdi32.RemoveFontResourceExW
        remove_font.argtypes = [wintypes.LPCWSTR, ctypes.c_uint, wintypes.LPVOID]
        remove_font.restype = ctypes.c_int
        FR_PRIVATE = 0x10
        if remove_font(str(font_path.resolve()), FR_PRIVATE, None) > 0:
            _oxanium_font_registered = False
            return True
    except (OSError, AttributeError) as exc:
        logger.warning("Could not unregister Oxanium with GDI: %s", exc)
        return False
    return False


def _oxanium_header_tk_font(point_size: int) -> Optional[tkfont.Font]:
    """Return a bold Oxanium ``Font`` when registration succeeded."""
    font = tkfont.Font(family=OXANIUM_FAMILY, size=point_size, weight="bold")
    try:
        if font.actual("family") == OXANIUM_FAMILY:
            return font
    except tk.TclError:
        pass
    return None


def _default_header_point_size(scale: float) -> int:
    base = tkfont.nametofont("TkDefaultFont")
    try:
        size = int(base.cget("size"))
    except tk.TclError:
        size = 10
    if size <= 0:
        size = 10
    return max(8, int(round(size * scale)))


def plugin_header_font(scale: float = HEADER_FONT_SCALE) -> tkfont.Font:
    """Bold Oxanium when bundled; otherwise scaled EDMC default (plugin strip title)."""
    global _oxanium_header_font, _oxanium_header_font_failed

    if _oxanium_header_font is not None:
        return _oxanium_header_font

    point_size = _default_header_point_size(scale)
    if not _oxanium_header_font_failed:
        oxanium_path = bundled_oxanium_font_path()
        if oxanium_path is not None and _register_bundled_oxanium(oxanium_path):
            try:
                oxanium_font = _oxanium_header_tk_font(point_size)
                if oxanium_font is not None:
                    _oxanium_header_font = oxanium_font
                    logger.debug("Plugin header using %s at %spt", OXANIUM_FAMILY, point_size)
                    return _oxanium_header_font
            except tk.TclError as exc:
                logger.warning("Oxanium header font creation failed: %s", exc)
        _oxanium_header_font_failed = True
        logger.warning(
            "Oxanium header font unavailable (bundled=%s); using default Tk font",
            oxanium_path is not None,
        )

    base = tkfont.nametofont("TkDefaultFont")
    _oxanium_header_font = tkfont.Font(
        family=base.actual("family"),
        size=point_size,
        weight="bold",
    )
    return _oxanium_header_font


def reapply_plugin_header_font(label: tk.Label, scale: float = HEADER_FONT_SCALE) -> None:
    """Re-apply header font after EDMC ``theme.update`` (which may reset widget fonts)."""
    try:
        label.configure(font=plugin_header_font(scale))
    except tk.TclError as exc:
        logger.debug("Could not reapply plugin header font: %s", exc)


def release_bundled_oxanium_font() -> None:
    """Release the private Oxanium registration and cached font before plugin replacement."""
    global _oxanium_header_font, _oxanium_header_font_failed
    font_path = bundled_oxanium_font_path()
    if font_path is None:
        return
    if _unregister_bundled_oxanium(font_path):
        _oxanium_header_font = None
        _oxanium_header_font_failed = False


def _checkbox_theme_colors(
    *,
    panel_background: object = None,
    widget: Optional[tk.Widget] = None,
) -> tuple[str, str, str]:
    """Panel fill, box border, and check mark colors from EDMC theme when available."""
    dark = _edmc_theme_is_dark()
    bg = "#1e1e1e" if dark else "#ffffff"
    border = "#f0f0f0" if dark else "#404040"
    mark = "#ff8000"
    try:
        from theme import theme  # type: ignore[import-untyped]

        if getattr(theme, "current", None):
            bg = str(theme.current.get("background", bg))
            border = str(theme.current.get("highlight", theme.current.get("foreground", border)))
            mark = str(theme.current.get("foreground", mark))
    except ImportError:
        pass

    if panel_background:
        bg = str(panel_background)
    bg = _tk_color_to_hex(bg, fallback="#1e1e1e" if dark else "#ffffff", widget=widget)
    border = _tk_color_to_hex(border, fallback="#f0f0f0" if dark else "#404040", widget=widget)
    mark = _tk_color_to_hex(mark, fallback="#ff8000" if dark else "#000000", widget=widget)

    contrast = _contrasting_color(bg)
    if _colors_too_close(bg, border):
        border = contrast
    if _colors_too_close(bg, mark):
        mark = contrast
    return bg, border, mark


def _checkbox_check_mark(inner: int, lx: int, ly: int) -> bool:
    """True when ``(lx, ly)`` lies on a check stroke inside an ``inner``×``inner`` box."""
    if inner < 4:
        return False
    thickness = max(1.2, inner * 0.14)

    def dist(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
        dx, dy = bx - ax, by - ay
        if dx == 0 and dy == 0:
            return math.hypot(px - ax, py - ay)
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
        return math.hypot(px - (ax + t * dx), py - (ay + t * dy))

    return dist(
        lx + 0.5,
        ly + 0.5,
        inner * 0.18,
        inner * 0.52,
        inner * 0.38,
        inner * 0.78,
    ) <= thickness or dist(
        lx + 0.5,
        ly + 0.5,
        inner * 0.38,
        inner * 0.78,
        inner * 0.82,
        inner * 0.22,
    ) <= thickness


def _checkbox_photo(
    size: int,
    *,
    checked: bool,
    bg: str,
    border: str,
    mark: str,
) -> tk.PhotoImage:
    """Draw a themed square indicator; widget size follows the bitmap (no font padding)."""
    img = tk.PhotoImage(width=size, height=size)
    border_px = max(1, size // 10)
    inner = size - 2 * border_px
    for y in range(size):
        row: list[str] = []
        for x in range(size):
            if x < border_px or y < border_px or x >= size - border_px or y >= size - border_px:
                row.append(border)
            elif checked and _checkbox_check_mark(inner, x - border_px, y - border_px):
                row.append(mark)
            else:
                row.append(bg)
        img.put("{" + " ".join(row) + "}", to=(0, y))
    return img


def _checkbox_images(
    size: int = CHECKBOX_INDICATOR_PX,
    *,
    panel_background: object = None,
    widget: Optional[tk.Widget] = None,
) -> tuple[tk.PhotoImage, tk.PhotoImage]:
    """Cached unchecked/checked indicator pair for ``indicatoron=0`` checkbuttons."""
    bg, border, mark = _checkbox_theme_colors(panel_background=panel_background, widget=widget)
    key = (size, bg, border, mark)
    cached = _checkbox_image_cache.get(key)
    if cached is not None:
        return cached
    pair = (
        _checkbox_photo(size, checked=False, bg=bg, border=border, mark=mark),
        _checkbox_photo(size, checked=True, bg=bg, border=border, mark=mark),
    )
    _checkbox_image_cache[key] = pair
    return pair


class ThemedCheckbox:
    """
    ``tk.Checkbutton`` with drawn indicator images plus ``ttk.Label`` caption.

    ``indicatoron=0`` + ``PhotoImage`` pairs size the control to the graphic (~2× native)
    without font padding or ttk ``indicatorsize`` white cells. Colors follow EDMC theme.
    """

    def __init__(
        self,
        parent: tk.Widget,
        *,
        text: str,
        variable: tk.BooleanVar,
        command: Optional[Callable[[], None]] = None,
        padx: tuple[int, int] = (5, 4),
    ) -> None:
        self.frame = tk.Frame(parent, highlightthickness=0, borderwidth=0)
        self.frame.pack(side=tk.LEFT, padx=padx)
        self.variable = variable
        self._interactable = True
        self._user_command = command
        self._img_off: Optional[tk.PhotoImage] = None
        self._img_on: Optional[tk.PhotoImage] = None
        self.checkbutton = tk.Checkbutton(
            self.frame,
            variable=variable,
            text="",
            command=self._on_checkbutton_click,
            indicatoron=0,
            highlightthickness=0,
            borderwidth=0,
            relief=tk.FLAT,
            takefocus=0,
        )
        self.checkbutton.pack(side=tk.LEFT, padx=(0, 2), pady=0)
        self._label = ttk.Label(self.frame, text=text)
        self._label.pack(side=tk.LEFT, padx=(4, 0))
        self._label.bind("<Button-1>", self._on_label_click)
        try:
            self.checkbutton.configure(cursor="hand2")
        except tk.TclError:
            pass
        self.refresh_theme()

    def _on_checkbutton_click(self) -> None:
        if not self._interactable:
            # Tcl toggles the variable before ``command``; revert when gated off.
            self.variable.set(not bool(self.variable.get()))
            return
        if self._user_command is not None:
            self._user_command()

    def _on_label_click(self, _event: object = None) -> None:
        if not self._interactable:
            return
        self.variable.set(not bool(self.variable.get()))
        if self._user_command is not None:
            self._user_command()

    def set_interactable(self, interactable: bool) -> None:
        """
        Gate clicks without ``disabled`` on the indicator.

        Disabled ``tk.Checkbutton`` indicators look different on Windows; this keeps all
        overlay checkboxes on the same indicator theme while graying only the caption.
        """
        self._interactable = interactable
        self._sync_label_state("normal" if interactable else "disabled")
        try:
            self.checkbutton.configure(cursor="hand2" if interactable else "arrow")
        except tk.TclError:
            pass

    def configure(self, **kwargs: Any) -> None:
        if "text" in kwargs:
            text = kwargs.pop("text")
            try:
                self._label.configure(text=text)
            except tk.TclError:
                pass
        if "state" in kwargs:
            state = kwargs.pop("state")
            self.set_interactable(str(state) != str(tk.DISABLED))
        if kwargs:
            self.checkbutton.configure(**kwargs)

    def set_text(self, text: str) -> None:
        """Update the caption text without touching the indicator button."""
        self.configure(text=text)

    def _sync_label_state(self, state: str) -> None:
        """Caption uses native ``TLabel`` styling (same as **Select Plan Site**)."""
        label_state = "disabled" if str(state) == str(tk.DISABLED) else "normal"
        try:
            self._label.configure(state=label_state)
        except tk.TclError:
            pass

    def refresh_theme(self) -> None:
        """Sync indicator images and caption with EDMC theme."""
        self._sync_label_state("normal" if self._interactable else "disabled")
        try:
            bg = str(self.frame.cget("bg"))
            self._img_off, self._img_on = _checkbox_images(
                panel_background=bg,
                widget=self.frame,
            )
            patch: dict[str, Any] = {
                "background": bg,
                "activebackground": bg,
                "image": self._img_off,
                "selectimage": self._img_on,
                "indicatoron": 0,
            }
            try:
                from theme import theme  # type: ignore[import-untyped]

                if getattr(theme, "current", None):
                    patch["foreground"] = theme.current.get("foreground", "")
                    patch["activeforeground"] = theme.current.get("activeforeground", "")
                    patch["disabledforeground"] = theme.current.get("disabledforeground", "")
            except ImportError:
                pass
            self.checkbutton.configure(**{k: v for k, v in patch.items() if v})
            try:
                self.frame.configure(background=bg)
            except tk.TclError:
                pass
        except tk.TclError:
            pass
