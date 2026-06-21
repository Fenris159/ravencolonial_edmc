"""
Tk.Entry + Listbox combobox with EDMC theme styling.

Adapted from GalaxyGPS ``ThemedCombobox`` (``EDMC_GalaxyGPS/GalaxyGPS/ui_helpers.py``):
same API surface as ``ttk.Combobox`` for basic use (values, state, ``<<ComboboxSelected>>``).
Popup list width is measured from the longest option; the collapsed entry width is set separately.

EDMC / Linux practices (see ``docs/THEME_UI.md``):

- Use ``tk`` widgets + ``from theme import theme`` (EDMC PLUGINS.md); avoid ``theme.update`` on
  ``tk.Listbox`` popups and prefer explicit fg/bg with contrast checks on default (light) theme.
- Open the dropdown only on click, not on ``FocusIn`` (GalaxyGPS).
- Post worker results with ``plugin.schedule_after(0, ...)`` on the plugin instance (Tk main thread; see ``load.py`` and ``docs/THEME_UI.md``).
- Popup: ``wm_overrideredirect(True)``; defer modal ``grab_set`` until visible (dialogs).
"""

from __future__ import annotations

import tkinter as tk
from typing import Any, List, Optional, Tuple

from .combo_colors import (
    ensure_readable_foreground,
    fallback_background,
    fallback_foreground,
    highlight_color_for_background,
    preferred_entry_colors,
)
from ..exc_utils import CONFIG_READ_ERRORS, TK_UI_ERRORS

try:
    from theme import theme as edmc_theme  # type: ignore
except ImportError:  # pragma: no cover - running outside EDMC
    edmc_theme = None


def _edmc_theme_is_dark() -> bool:
    try:
        from config import config  # type: ignore

        return config.get_int("theme") in (1, 2)
    except CONFIG_READ_ERRORS:
        return False


def _resolve_tk_color(widget: tk.Widget, color: object, fallback: str) -> str:
    """Return ``#rrggbb`` for Tk color names/system colors where possible."""
    raw = str(color or "").strip() or fallback
    try:
        r, g, b = widget.winfo_rgb(raw)
        return f"#{r // 257:02x}{g // 257:02x}{b // 257:02x}"
    except tk.TclError:
        if raw.startswith("#") and len(raw) == 7:
            return raw
        return fallback


def _resolve_panel_bg(
    frame_bg: str,
    *,
    current_theme: int,
    color_parent: tk.Widget,
) -> str:
    """Background for combobox entry/button from parent frame (GalaxyGPS-style)."""
    is_dark_theme = current_theme in (1, 2)
    fallback = fallback_background(dark=is_dark_theme)

    def get_actual_color(color_name: str) -> str:
        return _resolve_tk_color(color_parent, color_name, fallback)

    if frame_bg and str(frame_bg).strip():
        lowered = str(frame_bg).lower()
        if current_theme == 2 and lowered == "systemwindow":
            return get_actual_color("systemwindow")
        if str(frame_bg).startswith("#"):
            return get_actual_color(frame_bg)
        if lowered not in ("white", "#ffffff", "systembuttonface", "systemwindow"):
            return get_actual_color(frame_bg)
    return fallback


def _popup_list_colors_from_entry(entry: tk.Entry) -> Tuple[str, str, str]:
    """``(background, foreground, highlight)`` for the dropdown listbox."""
    dark = _edmc_theme_is_dark()
    try:
        bg = _resolve_tk_color(
            entry,
            entry.cget("readonlybackground") or entry.cget("background"),
            fallback_background(dark=dark),
        )
    except tk.TclError:
        bg = fallback_background(dark=dark)
    fg = fallback_foreground(dark=dark)
    fg = ensure_readable_foreground(bg, fg, dark=dark)
    return bg, fg, highlight_color_for_background(bg)


class DropdownPopupManager:
    """Create, size, and wire the themed combobox dropdown popup."""

    def __init__(self, combobox: 'ThemedCombobox') -> None:
        self._cb = combobox

    def open(self) -> None:
        cb = self._cb
        cb.entry.update_idletasks()
        x = cb.frame.winfo_rootx()
        y = cb.frame.winfo_rooty() + cb.frame.winfo_height()
        self._create_popup(x, y)
        self._create_listbox()
        self._populate_listbox()
        self._bind_listbox_handlers()
        self._bind_popup_handlers()
        x, y = self._position_popup(x, y)
        self._select_current_value()

    def _create_popup(self, x: int, y: int) -> None:
        cb = self._cb
        cb.popup = tk.Toplevel(cb.parent)
        cb.popup.wm_overrideredirect(True)
        cb.popup.wm_geometry(f"+{x}+{y}")

    def _listbox_colors(self) -> Tuple[str, str, str]:
        try:
            return _popup_list_colors_from_entry(self._cb.entry)
        except (tk.TclError, AttributeError, TypeError, ValueError):
            dark = _edmc_theme_is_dark()
            bg_color = fallback_background(dark=dark)
            fg_color = fallback_foreground(dark=dark)
            highlight_color = highlight_color_for_background(bg_color)
            return bg_color, fg_color, highlight_color

    def _create_listbox(self) -> None:
        cb = self._cb
        bg_color, fg_color, highlight_color = self._listbox_colors()
        cb.listbox = tk.Listbox(
            cb.popup,
            bg=bg_color,
            fg=fg_color,
            selectbackground=highlight_color,
            selectforeground=fg_color,
            activestyle="underline",
            borderwidth=1,
            relief=tk.SOLID,
            highlightthickness=0,
        )
        cb.listbox.pack(fill=tk.BOTH, expand=True)
        cb.hover_index = None

    def _populate_listbox(self) -> None:
        cb = self._cb
        if cb.listbox is None:
            return
        for value in cb.values:
            cb.listbox.insert(tk.END, value)
        if cb.values:
            cb.listbox.configure(height=len(cb.values))

    def _bind_listbox_handlers(self) -> None:
        cb = self._cb
        if cb.listbox is None:
            return

        def on_motion(event: tk.Event) -> None:
            if not cb.listbox:
                return
            index = cb.listbox.nearest(event.y)
            if index != cb.hover_index:
                cb.hover_index = index
                cb.listbox.selection_clear(0, tk.END)
                cb.listbox.selection_set(index)
                cb.listbox.activate(index)

        def on_leave(_event: tk.Event) -> None:
            cb.hover_index = None

        cb.listbox.bind("<Motion>", on_motion)
        cb.listbox.bind("<Leave>", on_leave)
        cb.listbox.bind("<Button-1>", cb.on_select)
        cb.listbox.bind("<Double-Button-1>", cb.on_select)
        cb.listbox.bind("<Return>", cb.on_select)
        cb.listbox.bind("<Escape>", lambda e: cb.close_dropdown())

    def _bind_popup_handlers(self) -> None:
        cb = self._cb
        cb._selecting = False

        def on_focus_out(_event: object = None) -> None:
            def check_close() -> None:
                if cb.is_open and not cb._selecting:
                    cb.close_dropdown()

            cb.parent.after(150, check_close)

        if cb.popup is not None:
            cb.popup.bind("<FocusOut>", on_focus_out)

        def on_click_anywhere(event: tk.Event) -> None:
            if not cb.is_open or cb._selecting:
                return
            try:
                widget = event.widget
                popup_str = str(cb.popup) if cb.popup else ""
                listbox_str = str(cb.listbox) if cb.listbox else ""
                frame_str = str(cb.frame)
                entry_str = str(cb.entry)
                btn_str = str(cb.dropdown_btn)
                widget_str = str(widget)
                if (
                    widget_str.startswith(popup_str) or
                    widget_str.startswith(listbox_str) or
                    widget_str == frame_str or
                    widget_str == entry_str or
                    widget_str == btn_str or
                    widget == cb.popup or
                    widget == cb.listbox or
                    widget == cb.frame or
                    widget == cb.entry or
                    widget == cb.dropdown_btn
                ):
                    return
                cb.close_dropdown()
            except TK_UI_ERRORS:  # nosec B110 - best-effort outside-click close during destroy races
                pass

        root = cb.parent.winfo_toplevel()
        cb._root_click_binding = root.bind("<Button-1>", on_click_anywhere, add="+")
        if cb.listbox is not None:
            cb.listbox.focus_set()

    def _measure_popup_size(self) -> Tuple[int, int]:
        cb = self._cb
        line_px = 16
        listbox_width = 200
        if cb.values and cb.listbox is not None:
            try:
                import tkinter.font as tkfont

                font_spec = cb.listbox.cget("font")
                if isinstance(font_spec, str):
                    list_font = (
                        tkfont.nametofont(font_spec)
                        if font_spec
                        else tkfont.nametofont("TkDefaultFont")
                    )
                else:
                    list_font = tkfont.Font(font=font_spec)

                line_px = max(int(list_font.metrics("linespace")), 14)
                max_width = max(list_font.measure(str(value)) for value in cb.values)
                listbox_width = max_width + 40
            except (ImportError, tk.TclError, AttributeError, TypeError, ValueError):
                max_text_length = max(len(str(value)) for value in cb.values)
                listbox_width = max_text_length * 10

        if cb.listbox is not None:
            cb.listbox.update_idletasks()
            measured_h = cb.listbox.winfo_reqheight()
            item_h = max(1, len(cb.values)) * line_px + 6
            listbox_height = max(measured_h, item_h, 28)
        else:
            listbox_height = 28

        listbox_width = max(listbox_width, cb.frame.winfo_width())
        return listbox_width, listbox_height

    def _position_popup(self, x: int, y: int) -> Tuple[int, int]:
        cb = self._cb
        listbox_width, listbox_height = self._measure_popup_size()
        if cb.popup is not None:
            cb.popup.wm_geometry(f"{listbox_width}x{listbox_height}")

        screen_width = cb.parent.winfo_screenwidth()
        screen_height = cb.parent.winfo_screenheight()
        if cb.popup is not None:
            cb.popup.update_idletasks()
            popup_width = cb.popup.winfo_width()
            popup_height = cb.popup.winfo_height()
        else:
            popup_width, popup_height = listbox_width, listbox_height

        if x + popup_width > screen_width:
            x = cb.frame.winfo_rootx() + cb.frame.winfo_width() - popup_width
            x = max(0, x)
        if y + popup_height > screen_height:
            y = cb.frame.winfo_rooty() - popup_height
            y = max(0, y)
        if cb.popup is not None:
            cb.popup.wm_geometry(f"+{x}+{y}")
        return x, y

    def _select_current_value(self) -> None:
        cb = self._cb
        current_value = cb.textvariable.get()
        if current_value in cb.values and cb.listbox:
            idx = cb.values.index(current_value)
            cb.listbox.selection_set(idx)


class ThemedCombobox:
    """
    Custom combobox that matches EDMC themes (avoids ``ttk.Combobox`` white/chrome on Windows).
    """

    def __init__(
        self,
        parent: tk.Widget,
        textvariable: Optional[tk.StringVar] = None,
        values: Optional[List[str]] = None,
        width: Optional[int] = None,
        state: str = "readonly",
        **kwargs: Any,
    ):
        self.parent = parent
        self.textvariable = textvariable if textvariable else tk.StringVar()
        self.values: List[str] = list(values) if values else []
        self.width = width
        self.state = state
        self.kwargs = kwargs

        self.frame = tk.Frame(parent)

        def _entry_state(s: str) -> str:
            if s == "disabled":
                return "disabled"
            if s == "readonly":
                return "readonly"
            return "normal"

        entry_kwargs = {
            "textvariable": self.textvariable,
            "state": _entry_state(state),
            **kwargs,
        }
        if width is not None:
            entry_kwargs["width"] = width

        self.entry = tk.Entry(self.frame, **entry_kwargs)
        self.entry.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        # Styled only via ``apply_theme_styling`` (subtree ``theme.update`` breaks light-theme contrast).
        self.entry._rc_skip_subtree_theme = True  # type: ignore[attr-defined]

        self.dropdown_btn = tk.Button(
            self.frame,
            text="▼",
            width=2,
            command=self.toggle_dropdown,
            relief=tk.FLAT,
            borderwidth=1,
        )
        self.dropdown_btn.pack(side=tk.RIGHT, fill=tk.Y)
        self.dropdown_btn._rc_skip_subtree_theme = True  # type: ignore[attr-defined]

        self.popup: Optional[tk.Toplevel] = None
        self.listbox: Optional[tk.Listbox] = None
        self.is_open = False
        self._root_click_binding: Optional[str] = None
        self._selecting = False

        self.entry.bind("<Button-1>", self.on_entry_click)
        self._sync_state()

    def toggle_dropdown(self) -> None:
        if self.state == "disabled":
            return
        if self.is_open:
            self.close_dropdown()
        else:
            self.open_dropdown()

    def on_entry_click(self, event: object) -> None:
        if self.state == "disabled":
            return
        if self.state == "readonly":
            self.open_dropdown()

    def open_dropdown(self) -> None:
        if self.state == "disabled":
            return
        if self.is_open or not self.values:
            return
        self.is_open = True
        DropdownPopupManager(self).open()

    def on_select(self, event: Optional[tk.Event] = None) -> None:
        self._selecting = True

        if self.listbox:
            if event is not None and hasattr(event, "y"):
                idx = self.listbox.nearest(event.y)
                if 0 <= idx < len(self.values):
                    value = self.values[idx]
                    self.textvariable.set(value)
                    self.entry.event_generate("<<ComboboxSelected>>")
                    self.close_dropdown()
                    self._selecting = False
                    return

            selection = self.listbox.curselection()
            if selection:
                idx = selection[0]
                value = self.values[idx]
                self.textvariable.set(value)
                self.entry.event_generate("<<ComboboxSelected>>")

        self._selecting = False
        self.close_dropdown()

    def _release_root_click_binding(self) -> None:
        bind_id = self._root_click_binding
        if not bind_id:
            return
        self._root_click_binding = None
        try:
            root = self.parent.winfo_toplevel()
            root.unbind("<Button-1>", bind_id)
        except TK_UI_ERRORS:  # nosec B110 - popup may already be destroyed
            pass

    def close_dropdown(self) -> None:
        self._release_root_click_binding()
        if self.popup:
            try:
                self.popup.destroy()
            except TK_UI_ERRORS:  # nosec B110 - Toplevel may already be gone
                pass
            self.popup = None
            self.listbox = None
        self.is_open = False

    def _sync_state(self) -> None:
        if self.state == "disabled":
            self.entry.config(state="disabled")
            self.dropdown_btn.config(state="disabled")
        elif self.state == "readonly":
            self.entry.config(state="readonly")
            self.dropdown_btn.config(state="normal")
        else:
            self.entry.config(state="normal")
            self.dropdown_btn.config(state="normal")

    def config(self, **kwargs: Any) -> None:
        if "values" in kwargs:
            v = kwargs.pop("values")
            self.values = list(v) if v is not None else []
        if "state" in kwargs:
            self.state = str(kwargs.pop("state"))
            self._sync_state()
        if kwargs:
            self.entry.config(**kwargs)

    configure = config

    def cget(self, option: str) -> Any:
        if option == "values":
            return tuple(self.values)
        if option == "state":
            return self.state
        return self.entry.cget(option)

    def __getitem__(self, key: str) -> Any:
        return self.cget(key)

    def __setitem__(self, key: str, value: Any) -> None:
        self.config(**{key: value})

    def pack(self, **kwargs: Any) -> None:
        self.frame.pack(**kwargs)

    def grid(self, **kwargs: Any) -> None:
        self.frame.grid(**kwargs)

    def bind(self, event: str, handler: Any) -> None:
        self.entry.bind(event, handler)

    def get(self) -> str:
        """Current displayed value (``ttk.Combobox``-compatible)."""
        return self.textvariable.get()

    def current(self, index: Optional[int] = None) -> Any:
        if index is not None:
            if 0 <= index < len(self.values):
                self.textvariable.set(self.values[index])
                self.entry.event_generate("<<ComboboxSelected>>")
        else:
            current_value = self.textvariable.get()
            if current_value in self.values:
                return self.values.index(current_value)
            return -1

    def set_entry_width_for_text(
        self,
        text: str,
        *,
        min_cols: int = 10,
        max_cols: int = 72,
        pad_px: int = 36,
    ) -> None:
        """Size the visible entry (character columns) to fit ``text`` without stretching the row."""
        try:
            import tkinter.font as tkfont

            font_spec = self.entry.cget("font")
            if isinstance(font_spec, str) and font_spec:
                font = tkfont.nametofont(font_spec)
            elif font_spec:
                font = tkfont.Font(font=font_spec)
            else:
                font = tkfont.nametofont("TkDefaultFont")
            px = font.measure(text or "") + pad_px
            cw = max(font.measure("0"), 1)
            cols = int((px + cw - 1) // cw)
            cols = max(min_cols, min(max_cols, cols))
            self.entry.configure(width=cols)
        except (ImportError, tk.TclError, AttributeError, TypeError, ValueError):
            self.entry.configure(width=max(min_cols, min(max_cols, len(text or "") + 4)))

    def apply_theme_styling(self) -> None:
        """
        Apply theme-aware styling to the combobox entry and dropdown button.

        Matches GalaxyGPS ``ThemedCombobox.apply_theme_styling`` (same ``frame_bg`` logic,
        same ``entry.config`` / ``theme.update`` order). Call after ``theme.update`` on the
        parent row so ``self.frame.cget('bg')`` matches the plugin panel.

        Disabled placeholders use ``disabledbackground`` for their paint path. EDMC's
        default theme can rewrite entry backgrounds to panel grey, so light/default
        mode re-applies the preferred white entry surface after ``theme.update`` while
        dark modes keep EDMC's resolved themed background.
        """
        try:
            from config import config  # type: ignore

            current_theme = config.get_int("theme")
            is_dark_theme = current_theme in (1, 2)
            frame_bg = str(self.frame.cget("bg"))
            bg_color = _resolve_panel_bg(
                frame_bg, current_theme=current_theme, color_parent=self.frame
            )
            bg_color, fg_color = preferred_entry_colors(bg_color, dark=is_dark_theme)
            insert_color = fg_color

            self.entry.config(
                bg=bg_color,
                fg=fg_color,
                insertbackground=insert_color,
                readonlybackground=bg_color,
            )
            self.dropdown_btn.config(
                bg=bg_color,
                fg=fg_color,
                activebackground=bg_color,
                activeforeground=fg_color,
            )

            if edmc_theme:
                try:
                    edmc_theme.update(self.frame)
                    edmc_theme.update(self.entry)
                    edmc_theme.update(self.dropdown_btn)
                except (ValueError, TypeError, tk.TclError):
                    pass

            if is_dark_theme:
                try:
                    ebg = _resolve_tk_color(
                        self.entry,
                        self.entry.cget("background"),
                        bg_color,
                    )
                except tk.TclError:
                    ebg = bg_color
            else:
                ebg = bg_color

            efg = fallback_foreground(dark=is_dark_theme)
            efg = ensure_readable_foreground(ebg, efg, dark=is_dark_theme)

            patch: dict[str, Any] = {
                "bg": ebg,
                "background": ebg,
                "fg": efg,
                "foreground": efg,
                "readonlybackground": ebg,
                "disabledbackground": ebg,
                "disabledforeground": efg,
                "highlightbackground": ebg,
                "highlightcolor": efg,
            }
            try:
                if "readonlyforeground" in self.entry.keys():
                    patch["readonlyforeground"] = efg
            except tk.TclError:
                pass
            try:
                self.entry.config(**patch)
                self.dropdown_btn.config(
                    bg=ebg,
                    fg=efg,
                    activebackground=ebg,
                    activeforeground=efg,
                    highlightbackground=ebg,
                    highlightcolor=efg,
                )
            except tk.TclError:
                pass

        except (CONFIG_READ_ERRORS, tk.TclError, TypeError, ValueError):  # nosec B110
            pass
        self._sync_state()
