"""
Tk.Entry + Listbox combobox with EDMC theme styling.

Adapted from GalaxyGPS ``ThemedCombobox`` (``EDMC_GalaxyGPS/GalaxyGPS/ui_helpers.py``):
same API surface as ``ttk.Combobox`` for basic use (values, state, ``<<ComboboxSelected>>``).
Popup list width is measured from the longest option; the collapsed entry width is set separately.

EDMC / Linux practices (see ``docs/THEME_UI.md``):

- Use ``tk`` widgets + ``from theme import theme`` (EDMC PLUGINS.md); avoid ``theme.update`` on
  ``tk.Listbox`` popups and prefer explicit fg/bg with contrast checks on default (light) theme.
- Open the dropdown only on click, not on ``FocusIn`` (GalaxyGPS).
- Post worker results with ``frame.after(0, ...)`` on the plugin frame (Tk main thread).
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

try:
    from theme import theme as edmc_theme  # type: ignore
except ImportError:  # pragma: no cover - running outside EDMC
    edmc_theme = None


def _edmc_theme_is_dark() -> bool:
    try:
        from config import config  # type: ignore

        return config.get_int("theme") in (1, 2)
    except Exception:
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
    try:
        fg = _resolve_tk_color(entry, entry.cget("foreground"), fallback_foreground(dark=dark))
        if not dark:
            try:
                if "readonlyforeground" in entry.keys():
                    fg = _resolve_tk_color(
                        entry,
                        entry.cget("readonlyforeground") or fg,
                        fallback_foreground(dark=dark),
                    )
            except tk.TclError:
                pass
    except tk.TclError:
        fg = fallback_foreground(dark=dark)
    fg = ensure_readable_foreground(bg, fg, dark=dark)
    return bg, fg, highlight_color_for_background(bg)


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

        self.entry.update_idletasks()
        x = self.frame.winfo_rootx()
        y = self.frame.winfo_rooty() + self.frame.winfo_height()

        self.popup = tk.Toplevel(self.parent)
        self.popup.wm_overrideredirect(True)
        self.popup.wm_geometry(f"+{x}+{y}")

        try:
            bg_color, fg_color, highlight_color = _popup_list_colors_from_entry(self.entry)
        except Exception:
            dark = _edmc_theme_is_dark()
            bg_color = fallback_background(dark=dark)
            fg_color = fallback_foreground(dark=dark)
            highlight_color = highlight_color_for_background(bg_color)

        self.listbox = tk.Listbox(
            self.popup,
            bg=bg_color,
            fg=fg_color,
            selectbackground=highlight_color,
            selectforeground=fg_color,
            activestyle="underline",
            borderwidth=1,
            relief=tk.SOLID,
            highlightthickness=0,
        )
        self.listbox.pack(fill=tk.BOTH, expand=True)

        self.hover_index: Optional[int] = None

        def on_motion(event: tk.Event) -> None:
            if not self.listbox:
                return
            index = self.listbox.nearest(event.y)
            if index != self.hover_index:
                self.hover_index = index
                self.listbox.selection_clear(0, tk.END)
                self.listbox.selection_set(index)
                self.listbox.activate(index)

        def on_leave(_event: tk.Event) -> None:
            self.hover_index = None

        self.listbox.bind("<Motion>", on_motion)
        self.listbox.bind("<Leave>", on_leave)

        for value in self.values:
            self.listbox.insert(tk.END, value)
        if self.values:
            self.listbox.configure(height=len(self.values))

        # Do not call ``theme.update`` on the popup listbox: on Linux it often sets
        # foreground equal to background so items look like an empty list.

        self.listbox.bind("<Button-1>", self.on_select)
        self.listbox.bind("<Double-Button-1>", self.on_select)
        self.listbox.bind("<Return>", self.on_select)
        self.listbox.bind("<Escape>", lambda e: self.close_dropdown())

        self._selecting = False

        def on_focus_out(_event: object = None) -> None:
            def check_close() -> None:
                if self.is_open and not self._selecting:
                    self.close_dropdown()

            self.parent.after(150, check_close)

        self.popup.bind("<FocusOut>", on_focus_out)

        def on_click_anywhere(event: tk.Event) -> None:
            if not self.is_open or self._selecting:
                return
            try:
                widget = event.widget
                popup_str = str(self.popup) if self.popup else ""
                listbox_str = str(self.listbox) if self.listbox else ""
                frame_str = str(self.frame)
                entry_str = str(self.entry)
                btn_str = str(self.dropdown_btn)
                widget_str = str(widget)
                if (
                    widget_str.startswith(popup_str)
                    or widget_str.startswith(listbox_str)
                    or widget_str == frame_str
                    or widget_str == entry_str
                    or widget_str == btn_str
                    or widget == self.popup
                    or widget == self.listbox
                    or widget == self.frame
                    or widget == self.entry
                    or widget == self.dropdown_btn
                ):
                    return
                self.close_dropdown()
            except Exception:
                pass

        root = self.parent.winfo_toplevel()
        self._root_click_binding = root.bind("<Button-1>", on_click_anywhere, add="+")

        self.listbox.focus_set()

        self.listbox.update_idletasks()
        line_px = 16
        list_font = None
        if self.values:
            try:
                import tkinter.font as tkfont

                font_spec = self.listbox.cget("font")
                if isinstance(font_spec, str):
                    list_font = (
                        tkfont.nametofont(font_spec)
                        if font_spec
                        else tkfont.nametofont("TkDefaultFont")
                    )
                else:
                    list_font = tkfont.Font(font=font_spec)

                line_px = max(int(list_font.metrics("linespace")), 14)

                max_width = 0
                for value in self.values:
                    tw = list_font.measure(str(value))
                    if tw > max_width:
                        max_width = tw
                listbox_width = max_width + 40
            except Exception:
                max_text_length = max(len(str(value)) for value in self.values)
                listbox_width = max_text_length * 10
        else:
            listbox_width = 200

        measured_h = self.listbox.winfo_reqheight()
        item_h = max(1, len(self.values)) * line_px + 6
        listbox_height = max(measured_h, item_h, 28)

        # At least as wide as the closed control; no fixed 200px floor (short lists stay compact).
        listbox_width = max(listbox_width, self.frame.winfo_width())

        self.popup.wm_geometry(f"{listbox_width}x{listbox_height}")

        screen_width = self.parent.winfo_screenwidth()
        screen_height = self.parent.winfo_screenheight()

        self.popup.update_idletasks()
        popup_width = self.popup.winfo_width()
        popup_height = self.popup.winfo_height()

        if x + popup_width > screen_width:
            x = self.frame.winfo_rootx() + self.frame.winfo_width() - popup_width
            x = max(0, x)

        if y + popup_height > screen_height:
            y = self.frame.winfo_rooty() - popup_height
            y = max(0, y)

        self.popup.wm_geometry(f"+{x}+{y}")

        current_value = self.textvariable.get()
        if current_value in self.values and self.listbox:
            idx = self.values.index(current_value)
            self.listbox.selection_set(idx)

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
        except Exception:
            pass

    def close_dropdown(self) -> None:
        self._release_root_click_binding()
        if self.popup:
            try:
                self.popup.destroy()
            except Exception:
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
        except Exception:
            self.entry.configure(width=max(min_cols, min(max_cols, len(text or "") + 4)))

    def apply_theme_styling(self) -> None:
        """
        Apply theme-aware styling to the combobox entry and dropdown button.

        Matches GalaxyGPS ``ThemedCombobox.apply_theme_styling`` (same ``frame_bg`` logic,
        same ``entry.config`` / ``theme.update`` order). Call after ``theme.update`` on the
        parent row so ``self.frame.cget('bg')`` matches the plugin panel.

        Plan-site placeholders use ``state=disabled``; Tk uses ``disabledbackground`` for that
        paint path — after EDMC's ``theme.update(entry)``, copy resolved ``background`` /
        ``foreground`` into those keys only (do not re-apply our pre-theme ``bg_color`` over
        EDMC's result, or dark theme falls back to ``#1e1e1e`` and light theme stays panel grey).
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

            try:
                ebg = _resolve_tk_color(
                    self.entry,
                    self.entry.cget("background"),
                    bg_color,
                )
                efg = _resolve_tk_color(
                    self.entry,
                    self.entry.cget("foreground"),
                    fg_color,
                )
            except tk.TclError:
                ebg, efg = bg_color, fg_color

            efg = ensure_readable_foreground(ebg, efg, dark=is_dark_theme)

            patch: dict[str, Any] = {
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
                self.dropdown_btn.config(fg=efg, activeforeground=efg)
            except tk.TclError:
                pass

        except Exception:
            pass
        self._sync_state()
