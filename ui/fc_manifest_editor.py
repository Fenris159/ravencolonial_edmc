"""Theme-aware Fleet Carrier manifest editor."""

from __future__ import annotations

import logging
import re
import sys
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from ..api.client import normalize_commodity_key
from ..exc_utils import CONFIG_READ_ERRORS, HTTP_CLIENT_ERRORS, OVERLAY_UI_ERRORS
from ..i18n import tr, trf
from ..overlay.commodity_categories import category_for_commodity_key, category_sort_key
from ..overlay.fc_cargo import fc_callsign_label
from ..overlay.l10n_helpers import tr_category, tr_commodity
from .combo_colors import (
    edmc_theme_fg_bg,
    fallback_background,
    fallback_foreground,
    highlight_color_for_background,
    preferred_entry_colors,
)
from .edmc_theme import apply_theme_to_widget_subtree
from .themed_combobox import ThemedCombobox

logger = logging.getLogger(__name__)

EDITOR_TITLE = "Edit Carrier Manifest"
EDITOR_POSITION_CONFIG_KEY = "ravencolonial_fc_manifest_editor_position"
ADD_COMMODITY_CATEGORIES = frozenset(
    {
        "Metals",
        "Industrial Materials",
        "Chemicals",
        "Machinery",
        "Technology",
        "Foods",
        "Medicines",
        "Weapons",
    }
)
COMMODITY_TEMPLATE = Path(__file__).resolve().parents[1] / "L10n" / "en.commodities.template"
_COMMODITY_RE = re.compile(r'"commodity:([^"]+)"\s*=\s*"([^"]*)";')


@dataclass(frozen=True)
class CommodityOption:
    key: str
    label: str
    category: str


@dataclass(frozen=True)
class EditorColors:
    bg: str
    fg: str
    entry_bg: str
    entry_fg: str
    accent: str
    muted: str
    danger: str
    category_bg: str
    category_fg: str
    row_alt: str


class ThemedVerticalScrollbar(tk.Canvas):
    """Small canvas scrollbar so the manifest editor does not inherit light native chrome."""

    def __init__(self, parent: tk.Widget, command: Callable[..., Any], *, width: int = 16) -> None:
        super().__init__(
            parent,
            width=width,
            highlightthickness=0,
            borderwidth=0,
            takefocus=0,
        )
        self._command = command
        self._first = 0.0
        self._last = 1.0
        self._drag_offset = 0
        self._trough = "#000000"
        self._thumb = "#ff8000"
        self._thumb_active = "#ff8000"
        self.bind("<Configure>", lambda _event: self._draw())
        self.bind("<Button-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<Enter>", lambda _event: self.configure(cursor="hand2"))
        self.bind("<Leave>", lambda _event: self.configure(cursor=""))

    def set(self, first: Any, last: Any) -> None:
        try:
            self._first = max(0.0, min(1.0, float(first)))
            self._last = max(self._first, min(1.0, float(last)))
        except (TypeError, ValueError):
            self._first = 0.0
            self._last = 1.0
        self._draw()

    def apply_theme(self, colors: EditorColors) -> None:
        self._trough = colors.entry_bg
        self._thumb = colors.fg
        self._thumb_active = colors.category_bg
        try:
            self.configure(bg=colors.entry_bg)
        except tk.TclError:
            pass
        self._draw()

    def _thumb_geometry(self) -> Tuple[int, int]:
        height = max(1, int(self.winfo_height()))
        visible = max(0.0, min(1.0, self._last - self._first))
        if visible >= 0.999:
            return 0, height
        thumb_h = max(28, int(height * visible))
        max_top = max(0, height - thumb_h)
        top = int(round(max_top * self._first / max(0.0001, 1.0 - visible)))
        return top, min(height, top + thumb_h)

    def _draw(self, *, active: bool = False) -> None:
        try:
            width = max(1, int(self.winfo_width()))
            height = max(1, int(self.winfo_height()))
            self.delete("all")
            self.create_rectangle(0, 0, width, height, fill=self._trough, outline=self._trough)
            if self._last - self._first >= 0.999:
                return
            top, bottom = self._thumb_geometry()
            pad = max(2, width // 5)
            fill = self._thumb_active if active else self._thumb
            self.create_rectangle(pad, top + 2, width - pad, bottom - 2, fill=fill, outline=fill)
        except tk.TclError:
            pass

    def _on_press(self, event: tk.Event) -> None:
        top, bottom = self._thumb_geometry()
        if top <= event.y <= bottom:
            self._drag_offset = int(event.y - top)
        else:
            self._drag_offset = max(1, (bottom - top) // 2)
            self._move_to_event(event)
        self._draw(active=True)

    def _on_drag(self, event: tk.Event) -> None:
        self._move_to_event(event)
        self._draw(active=True)

    def _move_to_event(self, event: tk.Event) -> None:
        height = max(1, int(self.winfo_height()))
        top, bottom = self._thumb_geometry()
        thumb_h = max(1, bottom - top)
        visible = max(0.0, min(1.0, self._last - self._first))
        scrollable = max(1, height - thumb_h)
        fraction = (int(event.y) - self._drag_offset) / scrollable
        fraction = max(0.0, min(1.0 - visible, fraction * max(0.0, 1.0 - visible)))
        try:
            self._command("moveto", fraction)
        except tk.TclError:
            pass


@lru_cache(maxsize=1)
def commodity_catalog() -> Tuple[CommodityOption, ...]:
    """Return all known market commodities from the bundled commodity template."""
    options: Dict[str, CommodityOption] = {}
    try:
        text = COMMODITY_TEMPLATE.read_text(encoding="utf-8")
    except OSError:
        text = ""
    for key_raw, label_raw in _COMMODITY_RE.findall(text):
        key = normalize_commodity_key(key_raw)
        if not key:
            continue
        label = label_raw.strip() or tr_commodity(key)
        options[key] = CommodityOption(
            key=key,
            label=label,
            category=category_for_commodity_key(key),
        )
    return tuple(
        sorted(
            options.values(),
            key=lambda item: (
                category_sort_key(item.category),
                item.category.casefold(),
                item.label.casefold(),
            ),
        )
    )


def normalize_manifest(cargo: Optional[Mapping[str, Any]]) -> Dict[str, int]:
    """Normalize cargo totals; zero and negative rows are omitted."""
    out: Dict[str, int] = {}
    for raw_key, raw_value in (cargo or {}).items():
        key = normalize_commodity_key(str(raw_key))
        if not key:
            continue
        try:
            amount = int(raw_value)
        except (TypeError, ValueError):
            continue
        if amount > 0:
            out[key] = out.get(key, 0) + amount
    return out


def manifest_total(cargo: Mapping[str, int]) -> int:
    return sum(int(v) for v in cargo.values())


def format_manifest_total(total: int, free_space: Optional[Any] = None) -> str:
    total_text = f"{int(total):,}"
    try:
        free_space_i = int(free_space)
    except (TypeError, ValueError):
        free_space_i = None
    if free_space_i is not None and free_space_i >= 0:
        return trf("Total: {total}/{free_space}", total=total_text, free_space=f"{free_space_i:,}")
    return trf("Total: {total}", total=total_text)


def available_commodity_options(cargo: Mapping[str, int]) -> Tuple[CommodityOption, ...]:
    present = {normalize_commodity_key(str(k)) for k in cargo}
    return tuple(
        option
        for option in commodity_catalog()
        if option.key not in present and option.category in ADD_COMMODITY_CATEGORIES
    )


def manifest_update_payload(current: Mapping[str, int], base: Mapping[str, int]) -> Dict[str, int]:
    """Include zeroes for baseline rows removed from the editor."""
    current_norm = normalize_manifest(current)
    payload: Dict[str, int] = dict(current_norm)
    for key in normalize_manifest(base):
        if key not in current_norm:
            payload[key] = 0
    return payload


def linked_fc_options(linked_fcs: Mapping[Any, Mapping[str, Any]]) -> List[Tuple[str, int, Dict[str, Any]]]:
    rows: List[Tuple[str, int, Dict[str, Any]]] = []
    for raw_mid, raw_fc in (linked_fcs or {}).items():
        if not isinstance(raw_fc, Mapping):
            continue
        try:
            mid = int(raw_fc.get("marketId", raw_mid))
        except (TypeError, ValueError):
            continue
        fc = dict(raw_fc)
        fc["marketId"] = mid
        label = fc_callsign_label(fc)
        rows.append((label, mid, fc))
    rows.sort(key=lambda row: (row[0].casefold(), row[1]))
    seen: Dict[str, int] = {}
    out: List[Tuple[str, int, Dict[str, Any]]] = []
    for label, mid, fc in rows:
        seen[label] = seen.get(label, 0) + 1
        display = label if seen[label] == 1 else f"{label} ({mid})"
        out.append((display, mid, fc))
    return out


class FleetCarrierManifestEditor:
    """Edit cached Fleet Carrier cargo and POST a full replacement on save."""

    _MIN_W = 620
    _MIN_H = 720
    _TITLE_H = 38

    def __init__(self, plugin: Any) -> None:
        self._plugin = plugin
        self._window: Optional[tk.Toplevel] = None
        self._chrome_outer: Optional[tk.Frame] = None
        self._title_bar: Optional[tk.Frame] = None
        self._title_label: Optional[tk.Label] = None
        self._close_btn: Optional[tk.Button] = None
        self._content_frame: Optional[tk.Frame] = None
        self._taskbar_configured = False
        self._carrier_var: Optional[tk.StringVar] = None
        self._carrier_combo: Optional[ThemedCombobox] = None
        self._fc_display_to_market: Dict[str, int] = {}
        self._fc_records: Dict[int, Dict[str, Any]] = {}
        self._selected_market_id: Optional[int] = None
        self._base_manifest: Dict[str, int] = {}
        self._working_manifest: Dict[str, int] = {}
        self._amount_vars: Dict[str, tk.StringVar] = {}
        self._amount_entries: Dict[str, tk.Entry] = {}
        self._detail_vars: Dict[str, tk.StringVar] = {}
        self._manifest_frame: Optional[tk.Frame] = None
        self._manifest_canvas: Optional[tk.Canvas] = None
        self._manifest_scrollbar: Optional[ThemedVerticalScrollbar] = None
        self._add_panel: Optional[tk.Frame] = None
        self._add_listbox: Optional[tk.Listbox] = None
        self._add_scrollbar: Optional[ThemedVerticalScrollbar] = None
        self._add_display_to_key: Dict[str, str] = {}
        self._add_btn: Optional[tk.Button] = None
        self._cancel_btn: Optional[tk.Button] = None
        self._remove_buttons: List[tk.Button] = []
        self._save_btn: Optional[tk.Button] = None
        self._status_var: Optional[tk.StringVar] = None
        self._total_var: Optional[tk.StringVar] = None
        self._saving = False
        self._colors: Optional[EditorColors] = None

    def open(self) -> None:
        if self._window is not None:
            try:
                self._window.lift()
                self._window.focus_force()
                self.refresh()
                return
            except tk.TclError:
                self._window = None
        self._build_window()
        self.refresh()

    def close(self) -> None:
        window = self._window
        if window is not None:
            self._save_window_position(window)
        self._window = None
        self._chrome_outer = None
        self._title_bar = None
        self._title_label = None
        self._close_btn = None
        self._content_frame = None
        self._manifest_scrollbar = None
        self._add_scrollbar = None
        self._add_btn = None
        self._cancel_btn = None
        self._remove_buttons = []
        self._taskbar_configured = False
        if window is not None:
            try:
                window.destroy()
            except tk.TclError:
                pass

    def refresh_theme(self) -> None:
        window = self._window
        if window is None:
            return
        self._colors = self._resolve_colors(window)
        self._apply_theme()
        self._render_manifest()
        self._refresh_add_list()

    def refresh(self) -> None:
        self._refresh_carrier_options()
        self._refresh_save_state()

    def _build_window(self) -> None:
        parent = getattr(self._plugin, "frame", None)
        window = tk.Toplevel(parent)
        self._window = window
        window.title(tr(EDITOR_TITLE))
        window.withdraw()
        window.overrideredirect(self._uses_borderless_chrome())
        window.minsize(self._MIN_W, self._MIN_H)
        window.protocol("WM_DELETE_WINDOW", self.close)
        self._configure_window_manager_hints(window)
        self._colors = self._resolve_colors(window)
        colors = self._colors
        border = self._chrome_border_color(colors)
        window.configure(background=border)

        self._chrome_outer = tk.Frame(window, background=border, highlightthickness=0, borderwidth=0)
        self._chrome_outer.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        self._title_bar = tk.Frame(
            self._chrome_outer,
            bg=colors.bg,
            height=self._TITLE_H,
            relief=tk.FLAT,
            bd=0,
        )
        self._title_bar.pack(fill=tk.X, side=tk.TOP)
        self._title_bar.pack_propagate(False)

        self._title_label = tk.Label(
            self._title_bar,
            text=tr(EDITOR_TITLE),
            bg=colors.bg,
            fg=colors.fg,
            font=("TkDefaultFont", 12, "bold"),
            anchor="w",
        )
        self._title_label.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(12, 4))

        self._close_btn = tk.Button(
            self._title_bar,
            text="X",
            command=self.close,
            width=3,
            bg=colors.bg,
            fg=colors.fg,
            relief=tk.FLAT,
            bd=0,
            activebackground="#ff4444",
            activeforeground="#ffffff",
            font=("TkDefaultFont", 12, "bold"),
            takefocus=0,
        )
        self._close_btn.pack(side=tk.RIGHT, padx=(0, 5), pady=2)

        outer = tk.Frame(
            self._chrome_outer,
            bg=colors.bg,
            highlightthickness=0,
            borderwidth=0,
            padx=14,
            pady=12,
        )
        outer.pack(fill=tk.BOTH, expand=True)
        self._content_frame = outer

        selector = tk.Frame(outer, bg=colors.bg)
        selector.pack(fill=tk.X, pady=(0, 8))
        tk.Label(
            selector,
            text=tr("Select Callsign:"),
            bg=colors.bg,
            fg=colors.fg,
            font=("TkDefaultFont", 10, "bold"),
        ).pack(side=tk.LEFT, padx=(0, 8))
        self._carrier_var = tk.StringVar(value="")
        self._carrier_combo = ThemedCombobox(selector, textvariable=self._carrier_var, state="readonly")
        self._carrier_combo.frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._carrier_combo.bind("<<ComboboxSelected>>", self._on_carrier_selected)

        details = tk.Frame(outer, bg=colors.bg)
        details.pack(fill=tk.X, pady=(0, 8))
        self._detail_vars = {
            "carrier": tk.StringVar(value=""),
            "market": tk.StringVar(value=""),
            "owner": tk.StringVar(value=""),
            "access": tk.StringVar(value=""),
            "notorious": tk.StringVar(value=""),
        }
        self._detail_row(details, 0, tr("Carrier name:"), self._detail_vars["carrier"])
        self._detail_row(details, 1, tr("MarketId:"), self._detail_vars["market"])
        self._detail_row(details, 2, tr("Owner:"), self._detail_vars["owner"])
        self._detail_row(details, 3, tr("Access:"), self._detail_vars["access"], width=16)
        self._detail_row(
            details,
            3,
            tr("Notorious:"),
            self._detail_vars["notorious"],
            label_col=2,
            value_col=3,
            width=16,
        )
        details.columnconfigure(1, weight=1)
        details.columnconfigure(3, weight=1)

        self._add_panel = tk.Frame(outer, bg=colors.bg)
        self._build_add_panel(self._add_panel)

        header_row = tk.Frame(outer, bg=colors.bg)
        header_row.pack(fill=tk.X, pady=(4, 2))
        tk.Label(
            header_row,
            text=tr("Commodity:"),
            bg=colors.bg,
            fg=colors.fg,
            font=("TkDefaultFont", 10, "bold"),
            anchor="w",
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(
            header_row,
            text=tr("Amount:"),
            bg=colors.bg,
            fg=colors.fg,
            font=("TkDefaultFont", 10, "bold"),
            width=12,
            anchor="e",
        ).pack(side=tk.LEFT, padx=(6, 34))

        manifest_shell = tk.Frame(outer, bg=colors.bg)
        manifest_shell.pack(fill=tk.BOTH, expand=True)
        self._manifest_canvas = tk.Canvas(
            manifest_shell,
            bg=colors.bg,
            highlightthickness=0,
            borderwidth=0,
        )
        scrollbar = ThemedVerticalScrollbar(manifest_shell, self._manifest_canvas.yview)
        self._manifest_scrollbar = scrollbar
        self._manifest_canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._manifest_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._manifest_frame = tk.Frame(self._manifest_canvas, bg=colors.bg)
        self._manifest_canvas.create_window((0, 0), window=self._manifest_frame, anchor="nw")
        self._manifest_frame.bind("<Configure>", self._on_manifest_configure)
        self._manifest_canvas.bind("<Configure>", self._on_manifest_canvas_configure)
        self._bind_manifest_mousewheel(self._manifest_canvas)
        self._bind_manifest_mousewheel(self._manifest_frame)

        footer = tk.Frame(outer, bg=colors.bg)
        footer.pack(fill=tk.X, pady=(8, 0))
        self._status_var = tk.StringVar(value="")
        tk.Label(
            footer,
            textvariable=self._status_var,
            bg=colors.bg,
            fg=colors.muted,
            anchor="w",
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._total_var = tk.StringVar(value="")
        tk.Label(
            footer,
            textvariable=self._total_var,
            bg=colors.bg,
            fg=colors.fg,
            font=("TkDefaultFont", 10, "bold"),
            anchor="e",
        ).pack(side=tk.RIGHT)

        buttons = tk.Frame(outer, bg=colors.bg)
        buttons.pack(fill=tk.X, pady=(12, 0))
        self._add_btn = tk.Button(
            buttons,
            text=tr("+ Add commodity?"),
            command=self._toggle_add_panel,
            cursor="hand2",
        )
        self._add_btn.pack(side=tk.LEFT)
        self._cancel_btn = tk.Button(buttons, text=tr("Cancel"), command=self.close, width=12)
        self._cancel_btn.pack(side=tk.RIGHT, padx=(6, 0))
        self._save_btn = tk.Button(buttons, text=tr("Save"), command=self._on_save, width=12, state=tk.DISABLED)
        self._save_btn.pack(side=tk.RIGHT)

        apply_theme_to_widget_subtree(window)
        self._apply_theme()
        self._bind_window_drag()
        self._restore_window_position(window)
        window.deiconify()
        self._ensure_taskbar_visibility(window)

    def _detail_row(
        self,
        parent: tk.Frame,
        row: int,
        label: str,
        variable: tk.StringVar,
        *,
        label_col: int = 0,
        value_col: int = 1,
        width: int = 32,
    ) -> None:
        colors = self._colors or self._resolve_colors(parent)
        tk.Label(
            parent,
            text=label,
            bg=colors.bg,
            fg=colors.fg,
            font=("TkDefaultFont", 10, "bold"),
            anchor="w",
        ).grid(row=row, column=label_col, sticky="w", padx=(0, 8), pady=2)
        entry = tk.Entry(
            parent,
            textvariable=variable,
            width=width,
            state="readonly",
            readonlybackground=colors.entry_bg,
            fg=colors.entry_fg,
            relief=tk.FLAT,
        )
        entry.grid(row=row, column=value_col, sticky="ew", padx=(0, 8), pady=2)

    def _build_add_panel(self, panel: tk.Frame) -> None:
        colors = self._colors or self._resolve_colors(panel)
        inner = tk.Frame(panel, bg=colors.bg)
        inner.pack(fill=tk.BOTH, expand=True)
        self._add_listbox = tk.Listbox(
            inner,
            height=9,
            activestyle="dotbox",
            bg=colors.entry_bg,
            fg=colors.entry_fg,
            selectbackground=colors.accent,
            selectforeground=colors.fg,
            exportselection=False,
        )
        yscroll = ThemedVerticalScrollbar(inner, self._add_listbox.yview)
        self._add_scrollbar = yscroll
        self._add_listbox.configure(yscrollcommand=yscroll.set)
        self._add_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)
        yscroll.apply_theme(colors)
        self._add_listbox.bind("<Double-Button-1>", self._on_add_selected)
        self._add_listbox.bind("<Return>", self._on_add_selected)

    def _refresh_carrier_options(self) -> None:
        handler = getattr(self._plugin, "fc_handler", None)
        linked = getattr(handler, "linked_fcs", {}) if handler is not None else {}
        rows = linked_fc_options(linked)
        self._fc_display_to_market = {label: mid for label, mid, _fc in rows}
        self._fc_records = {mid: fc for _label, mid, fc in rows}
        labels = list(self._fc_display_to_market.keys())
        combo = self._carrier_combo
        if combo is not None:
            combo["values"] = labels
            combo.configure(state="readonly" if labels else "disabled")
        selected_label = self._carrier_var.get() if self._carrier_var is not None else ""
        if selected_label not in self._fc_display_to_market and labels:
            if self._carrier_var is not None:
                self._carrier_var.set(labels[0])
            self._select_market(self._fc_display_to_market[labels[0]])
        elif not labels:
            self._select_market(None)

    def _on_carrier_selected(self, _event: object = None) -> None:
        label = self._carrier_var.get() if self._carrier_var is not None else ""
        self._select_market(self._fc_display_to_market.get(label))

    def _select_market(self, market_id: Optional[int]) -> None:
        self._selected_market_id = market_id
        fc = self._fc_records.get(market_id or -1, {})
        self._base_manifest = normalize_manifest(fc.get("cargo") if isinstance(fc, Mapping) else {})
        self._working_manifest = dict(self._base_manifest)
        self._set_detail_vars(fc)
        self._render_manifest()
        self._refresh_add_list()
        self._refresh_save_state()

    def _set_detail_vars(self, fc: Mapping[str, Any]) -> None:
        values = {
            "carrier": str(fc.get("displayName") or fc.get("carrierName") or fc.get("name") or ""),
            "market": str(fc.get("marketId") or ""),
            "owner": str(fc.get("owner") or getattr(self._plugin, "cmdr_name", None) or ""),
            "access": str(fc.get("access") or fc.get("accessLevel") or tr("All")),
            "notorious": str(fc.get("notorious") or fc.get("notoriousAccess") or tr("Allowed")),
        }
        for key, value in values.items():
            if key in self._detail_vars:
                self._detail_vars[key].set(value)

    def _render_manifest(self) -> None:
        frame = self._manifest_frame
        if frame is None:
            return
        for child in frame.winfo_children():
            child.destroy()
        self._amount_vars.clear()
        self._amount_entries.clear()
        self._remove_buttons.clear()
        colors = self._colors or self._resolve_colors(frame)
        if self._selected_market_id is None:
            tk.Label(
                frame,
                text=tr("No linked Fleet Carriers are loaded yet."),
                bg=colors.bg,
                fg=colors.muted,
                anchor="w",
            ).pack(fill=tk.X, pady=12)
            return

        rows = sorted(
            self._working_manifest.items(),
            key=lambda kv: (
                category_sort_key(category_for_commodity_key(kv[0])),
                category_for_commodity_key(kv[0]).casefold(),
                tr_commodity(kv[0]).casefold(),
            ),
        )
        last_category = None
        for idx, (key, amount) in enumerate(rows):
            category = category_for_commodity_key(key)
            if category != last_category:
                self._category_row(frame, tr_category(category), colors)
                last_category = category
            self._commodity_row(frame, key, amount, colors, alt=bool(idx % 2))
        if not rows:
            tk.Label(
                frame,
                text=tr("Manifest is empty."),
                bg=colors.bg,
                fg=colors.muted,
                anchor="w",
            ).pack(fill=tk.X, pady=12)
        self._update_total()

    def _category_row(self, parent: tk.Frame, label: str, colors: EditorColors) -> None:
        category_label = tk.Label(
            parent,
            text=label,
            bg=colors.category_bg,
            fg=colors.category_fg,
            anchor="w",
            padx=8,
            font=("TkDefaultFont", 10, "bold"),
        )
        category_label.pack(fill=tk.X, pady=(4, 0))
        self._bind_manifest_mousewheel(category_label)

    def _commodity_row(self, parent: tk.Frame, key: str, amount: int, colors: EditorColors, *, alt: bool) -> None:
        bg = colors.row_alt if alt else colors.bg
        row = tk.Frame(parent, bg=bg)
        row.pack(fill=tk.X, pady=1)
        label = tk.Label(
            row,
            text=tr_commodity(key),
            bg=bg,
            fg=colors.fg,
            anchor="w",
            padx=8,
        )
        label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        var = tk.StringVar(value=str(amount))
        self._amount_vars[key] = var
        entry = tk.Entry(
            row,
            textvariable=var,
            width=12,
            justify=tk.RIGHT,
            bg=colors.entry_bg,
            fg=colors.entry_fg,
            insertbackground=colors.entry_fg,
            relief=tk.SOLID,
            bd=1,
        )
        entry.pack(side=tk.LEFT, padx=(6, 6), pady=2)
        entry.bind("<KeyRelease>", lambda _event, commodity=key: self._on_amount_changed(commodity))
        entry.bind("<FocusOut>", lambda _event, commodity=key: self._on_amount_changed(commodity))
        self._amount_entries[key] = entry
        remove_btn = tk.Button(
            row,
            text="X",
            width=3,
            command=lambda commodity=key: self._remove_commodity(commodity),
            cursor="hand2",
        )
        remove_btn.pack(side=tk.LEFT, padx=(0, 4), pady=1)
        self._remove_buttons.append(remove_btn)
        self._configure_button_theme(remove_btn, colors)
        for widget in (row, label, entry, remove_btn):
            self._bind_manifest_mousewheel(widget)

    def _on_amount_changed(self, commodity: str) -> None:
        var = self._amount_vars.get(commodity)
        entry = self._amount_entries.get(commodity)
        if var is None:
            return
        colors = self._colors or self._resolve_colors(self._window or self._plugin.frame)
        raw = var.get().strip()
        try:
            value = int(raw)
            valid = value >= 0
        except ValueError:
            value = 0
            valid = False
        if entry is not None:
            try:
                entry.configure(fg=colors.entry_fg if valid else colors.danger)
            except tk.TclError:
                pass
        if valid:
            if value > 0:
                self._working_manifest[commodity] = value
            else:
                self._working_manifest.pop(commodity, None)
            self._update_total()
            self._refresh_add_list()
        self._refresh_save_state()

    def _remove_commodity(self, commodity: str) -> None:
        self._working_manifest.pop(commodity, None)
        self._render_manifest()
        self._refresh_add_list()
        self._refresh_save_state()

    def _toggle_add_panel(self) -> None:
        panel = self._add_panel
        if panel is None:
            return
        if panel.winfo_manager():
            panel.pack_forget()
        else:
            panel.pack(fill=tk.BOTH, pady=(0, 8))
            self._refresh_add_list()

    def _refresh_add_list(self) -> None:
        listbox = self._add_listbox
        if listbox is None:
            return
        colors = self._colors or self._resolve_colors(listbox)
        listbox.delete(0, tk.END)
        self._add_display_to_key.clear()
        last_category = ""
        for option in available_commodity_options(self._working_manifest):
            category = tr_category(option.category)
            if category != last_category:
                header = f"[{category}]"
                listbox.insert(tk.END, header)
                index = listbox.size() - 1
                try:
                    listbox.itemconfigure(
                        index,
                        bg=colors.category_bg,
                        fg=colors.category_fg,
                        selectbackground=colors.category_bg,
                        selectforeground=colors.category_fg,
                    )
                except tk.TclError:
                    pass
                last_category = category
            display = f"{option.label}"
            self._add_display_to_key[display] = option.key
            listbox.insert(tk.END, display)

    def _on_add_selected(self, _event: object = None) -> None:
        listbox = self._add_listbox
        if listbox is None:
            return
        selection = listbox.curselection()
        if not selection:
            return
        label = str(listbox.get(selection[0]))
        key = self._add_display_to_key.get(label)
        if not key:
            return
        self._working_manifest[key] = 1
        self._render_manifest()
        self._refresh_add_list()
        self._refresh_save_state()

    def _current_manifest_from_entries(self) -> Tuple[Dict[str, int], bool]:
        manifest = dict(self._working_manifest)
        valid = True
        for key, var in self._amount_vars.items():
            try:
                amount = int(var.get().strip())
            except ValueError:
                valid = False
                continue
            if amount > 0:
                manifest[key] = amount
            else:
                manifest.pop(key, None)
        return normalize_manifest(manifest), valid

    def _refresh_save_state(self) -> None:
        manifest, valid = self._current_manifest_from_entries()
        changed = manifest != self._base_manifest
        state = (
            tk.NORMAL
            if valid and changed and not self._saving and self._selected_market_id is not None
            else tk.DISABLED
        )
        if self._save_btn is not None:
            try:
                self._save_btn.configure(state=state)
            except tk.TclError:
                pass
        if self._status_var is not None:
            if self._saving:
                text = tr("Saving manifest...")
            elif not valid:
                text = tr("Amounts must be whole numbers.")
            elif changed:
                text = tr("Unsaved manifest changes.")
            else:
                text = tr("No manifest changes.")
            self._status_var.set(text)

    def _on_save(self) -> None:
        if self._saving or self._selected_market_id is None:
            return
        manifest, valid = self._current_manifest_from_entries()
        if not valid or manifest == self._base_manifest:
            self._refresh_save_state()
            return
        payload = manifest_update_payload(manifest, self._base_manifest)
        removed = sorted(key for key, amount in payload.items() if amount <= 0)
        market_id = int(self._selected_market_id)
        self._saving = True
        self._refresh_save_state()
        logger.info(
            "FC manifest editor saving marketId=%s: %s positive rows, %s removals",
            market_id,
            sum(1 for amount in payload.values() if amount > 0),
            len(removed),
        )
        if removed:
            logger.debug("FC manifest editor removal payload keys for %s: %s", market_id, removed)

        def worker() -> None:
            result: Optional[Mapping[str, Any]] = None
            error: Optional[BaseException] = None
            try:
                result = self._plugin.api_client.update_fc_cargo(market_id, payload)
                if result is None:
                    raise RuntimeError("server returned no cargo payload")
            except (HTTP_CLIENT_ERRORS, RuntimeError, AttributeError) as exc:
                error = exc
            self._schedule_on_main(lambda: self._finish_save(market_id, manifest, result, error))

        threading.Thread(target=worker, daemon=True, name="fc-manifest-save").start()

    def _finish_save(
        self,
        market_id: int,
        submitted: Mapping[str, int],
        result: Optional[Mapping[str, Any]],
        error: Optional[BaseException],
    ) -> None:
        self._saving = False
        if error is not None:
            logger.warning("FC manifest editor save failed for %s: %s", market_id, error)
            if self._status_var is not None:
                self._status_var.set(trf("Save failed: {error}", error=str(error)))
            self._refresh_save_state()
            return
        saved = normalize_manifest(result if isinstance(result, Mapping) else submitted)
        if not saved:
            saved = normalize_manifest(submitted)
        handler = getattr(self._plugin, "fc_handler", None)
        if handler is not None:
            handler.replace_fc_cargo_manifest(
                market_id,
                saved,
                source="manual_manifest_editor",
                timestamp=time.time(),
            )
            try:
                handler._maybe_mirror_selected_fc_cargo_and_refresh(market_id)
            except (AttributeError, OVERLAY_UI_ERRORS):
                logger.debug("Could not refresh overlay FC cache after manifest edit", exc_info=True)
        self._base_manifest = dict(saved)
        self._working_manifest = dict(saved)
        self._render_manifest()
        self._refresh_add_list()
        if self._status_var is not None:
            self._status_var.set(tr("Manifest saved."))
        self._refresh_save_state()

    def _schedule_on_main(self, callback: Any) -> None:
        frame = getattr(self._plugin, "frame", None)
        if frame is not None:
            try:
                if self._plugin.schedule_after(0, callback) is not None:
                    return
            except (AttributeError, tk.TclError):
                pass
        callback()

    def _update_total(self) -> None:
        if self._total_var is not None:
            self._total_var.set(
                format_manifest_total(
                    manifest_total(self._working_manifest),
                    self._selected_owner_free_space(),
                )
            )

    def _selected_owner_free_space(self) -> Optional[int]:
        if self._selected_market_id is None:
            return None
        handler = getattr(self._plugin, "fc_handler", None)
        if handler is None:
            return None
        try:
            capacity = handler.get_owner_capacity(int(self._selected_market_id))
        except (AttributeError, TypeError, ValueError):
            return None
        if not isinstance(capacity, Mapping):
            return None
        try:
            free_space = int(capacity.get("freeSpace"))
        except (TypeError, ValueError):
            return None
        return free_space if free_space >= 0 else None

    def _bind_manifest_mousewheel(self, widget: tk.Widget) -> None:
        try:
            widget.bind("<MouseWheel>", self._on_manifest_mousewheel, add="+")
            widget.bind("<Button-4>", self._on_manifest_mousewheel, add="+")
            widget.bind("<Button-5>", self._on_manifest_mousewheel, add="+")
        except tk.TclError:
            pass

    def _on_manifest_mousewheel(self, event: tk.Event) -> str:
        canvas = self._manifest_canvas
        if canvas is None:
            return "break"
        units = 0
        event_num = getattr(event, "num", None)
        if event_num == 4:
            units = -1
        elif event_num == 5:
            units = 1
        else:
            delta = int(getattr(event, "delta", 0) or 0)
            if delta:
                units = -1 if delta > 0 else 1
                if abs(delta) >= 120:
                    units = int(-delta / 120)
        if units:
            try:
                canvas.yview_scroll(units, "units")
            except tk.TclError:
                pass
        return "break"

    def _on_manifest_configure(self, _event: tk.Event) -> None:
        canvas = self._manifest_canvas
        if canvas is None:
            return
        try:
            canvas.configure(scrollregion=canvas.bbox("all"))
        except tk.TclError:
            pass

    def _on_manifest_canvas_configure(self, event: tk.Event) -> None:
        canvas = self._manifest_canvas
        frame = self._manifest_frame
        if canvas is None or frame is None:
            return
        try:
            item = canvas.find_all()[0]
            canvas.itemconfigure(item, width=event.width)
        except (IndexError, tk.TclError):
            pass

    def _bind_window_drag(self) -> None:
        window = self._window
        if window is None:
            return

        def start_drag(event: tk.Event) -> None:
            window._rc_drag_x = event.x_root  # type: ignore[attr-defined]
            window._rc_drag_y = event.y_root  # type: ignore[attr-defined]

        def on_drag(event: tk.Event) -> None:
            if not hasattr(window, "_rc_drag_x"):
                return
            dx = int(event.x_root - window._rc_drag_x)  # type: ignore[attr-defined]
            dy = int(event.y_root - window._rc_drag_y)  # type: ignore[attr-defined]
            window.geometry(f"+{window.winfo_x() + dx}+{window.winfo_y() + dy}")
            window._rc_drag_x = event.x_root  # type: ignore[attr-defined]
            window._rc_drag_y = event.y_root  # type: ignore[attr-defined]

        def stop_drag(_event: tk.Event) -> None:
            self._save_window_position(window)
            for attr in ("_rc_drag_x", "_rc_drag_y"):
                if hasattr(window, attr):
                    delattr(window, attr)

        for widget in (self._title_bar, self._title_label):
            if widget is None:
                continue
            widget.bind("<Button-1>", start_drag)
            widget.bind("<B1-Motion>", on_drag)
            widget.bind("<ButtonRelease-1>", stop_drag)

    @staticmethod
    def _uses_borderless_chrome() -> bool:
        return sys.platform.startswith("win")

    @staticmethod
    def _configure_window_manager_hints(window: tk.Toplevel) -> None:
        if sys.platform.startswith("win"):
            return
        try:
            window.attributes("-type", "normal")
        except tk.TclError:
            pass

    def _ensure_taskbar_visibility(self, window: tk.Toplevel) -> None:
        if self._taskbar_configured:
            return
        if not sys.platform.startswith("win"):
            self._taskbar_configured = True
            return
        try:
            window.after(0, lambda: self._promote_windows_taskbar(window))
            self._taskbar_configured = True
        except tk.TclError:
            pass

    @staticmethod
    def _promote_windows_taskbar(window: tk.Toplevel) -> None:
        try:
            import ctypes

            window.update_idletasks()
            hwnd = int(window.winfo_id())
            user32 = ctypes.windll.user32
            parent_hwnd = int(user32.GetParent(hwnd) or 0)
            if parent_hwnd:
                hwnd = parent_hwnd
            gwl_exstyle = -20
            ws_ex_appwindow = 0x00040000
            ws_ex_toolwindow = 0x00000080
            swp_nosize = 0x0001
            swp_nomove = 0x0002
            swp_nozorder = 0x0004
            swp_framechanged = 0x0020
            try:
                get_window_long = user32.GetWindowLongPtrW
                set_window_long = user32.SetWindowLongPtrW
            except AttributeError:
                get_window_long = user32.GetWindowLongW
                set_window_long = user32.SetWindowLongW
            style = int(get_window_long(hwnd, gwl_exstyle))
            style = (style | ws_ex_appwindow) & ~ws_ex_toolwindow
            set_window_long(hwnd, gwl_exstyle, style)
            user32.SetWindowPos(
                hwnd,
                0,
                0,
                0,
                0,
                0,
                swp_nomove | swp_nosize | swp_nozorder | swp_framechanged,
            )
            window.withdraw()
            window.after(0, window.deiconify)
        except OSError:
            logger.warning("Manifest editor taskbar promotion failed", exc_info=True)

    @staticmethod
    def _chrome_border_color(colors: EditorColors) -> str:
        return colors.fg

    def _restore_window_position(self, window: tk.Toplevel) -> None:
        saved = self._saved_window_position()
        if saved is None:
            return
        try:
            window.geometry(f"+{saved[0]}+{saved[1]}")
        except tk.TclError:
            pass

    @staticmethod
    def _saved_window_position() -> Optional[Tuple[int, int]]:
        try:
            from config import config  # type: ignore[import-untyped]

            raw = str(config.get_str(EDITOR_POSITION_CONFIG_KEY) or "").strip()
        except CONFIG_READ_ERRORS:
            return None
        if not raw:
            return None
        try:
            x_raw, y_raw = raw.split(",", 1)
            return int(x_raw), int(y_raw)
        except (TypeError, ValueError):
            logger.debug("Ignoring invalid manifest editor position config: %r", raw)
            return None

    @staticmethod
    def _save_window_position(window: tk.Toplevel) -> None:
        try:
            x = int(window.winfo_x())
            y = int(window.winfo_y())
        except tk.TclError:
            return
        try:
            from config import config  # type: ignore[import-untyped]

            config.set(EDITOR_POSITION_CONFIG_KEY, f"{x},{y}")
        except CONFIG_READ_ERRORS:
            logger.debug("Manifest editor position save failed", exc_info=True)

    def _apply_chrome_theme(self, colors: EditorColors) -> None:
        window = self._window
        border = self._chrome_border_color(colors)
        for widget in (window, self._chrome_outer):
            if widget is None:
                continue
            try:
                widget.configure(background=border)
            except tk.TclError:
                pass
        for widget in (self._title_bar, self._content_frame):
            if widget is None:
                continue
            try:
                widget.configure(bg=colors.bg)
            except tk.TclError:
                pass
        if self._title_label is not None:
            try:
                self._title_label.configure(bg=colors.bg, fg=colors.fg)
            except tk.TclError:
                pass
        if self._close_btn is not None:
            try:
                self._close_btn.configure(
                    bg=colors.entry_bg,
                    fg=colors.entry_fg,
                    activebackground="#ff4444",
                    activeforeground="#ffffff",
                    disabledforeground=colors.muted,
                    highlightbackground=colors.fg,
                    highlightcolor=colors.fg,
                    relief=tk.SOLID,
                    bd=1,
                )
            except tk.TclError:
                pass

    def _configure_button_theme(self, button: tk.Button, colors: EditorColors) -> None:
        try:
            button.configure(
                bg=colors.entry_bg,
                fg=colors.entry_fg,
                activebackground=colors.accent,
                activeforeground=colors.entry_fg,
                disabledforeground=colors.muted,
                highlightbackground=colors.fg,
                highlightcolor=colors.fg,
                relief=tk.SOLID,
                bd=1,
                borderwidth=1,
                takefocus=0,
            )
        except tk.TclError:
            pass

    def _apply_button_theme(self, colors: EditorColors) -> None:
        for button in (
            self._add_btn,
            self._cancel_btn,
            self._save_btn,
            *self._remove_buttons,
        ):
            if button is not None:
                self._configure_button_theme(button, colors)

    def _apply_scrollbar_theme(self, colors: EditorColors) -> None:
        for scrollbar in (self._manifest_scrollbar, self._add_scrollbar):
            if scrollbar is not None:
                scrollbar.apply_theme(colors)

    def _resolve_colors(self, widget: tk.Widget) -> EditorColors:
        def resolve_color(raw: str, fallback: str) -> str:
            try:
                r, g, b = widget.winfo_rgb(raw)
                return f"#{r // 257:02x}{g // 257:02x}{b // 257:02x}"
            except tk.TclError:
                return fallback

        try:
            from config import config  # type: ignore[import-untyped]

            dark = config.get_int("theme") in (1, 2)
        except CONFIG_READ_ERRORS:
            dark = False
        bg = fallback_background(dark=dark)
        fg = fallback_foreground(dark=dark)
        palette = edmc_theme_fg_bg()
        if palette:
            bg, fg = palette
        bg = resolve_color(bg, fallback_background(dark=dark))
        fg = resolve_color(fg, fallback_foreground(dark=dark))
        entry_bg, entry_fg = preferred_entry_colors(bg, dark=dark)
        entry_bg = resolve_color(entry_bg, fallback_background(dark=dark))
        entry_fg = resolve_color(entry_fg, fallback_foreground(dark=dark))
        accent = highlight_color_for_background(entry_bg)
        muted = "#a0a0a0" if dark else "#606060"
        danger = "#ff6b6b" if dark else "#b00020"
        category_bg = "#dbe84a" if dark else "#d8d8d8"
        category_fg = "#111111"
        row_alt = highlight_color_for_background(bg)
        return EditorColors(
            bg=bg,
            fg=fg,
            entry_bg=entry_bg,
            entry_fg=entry_fg,
            accent=accent,
            muted=muted,
            danger=danger,
            category_bg=category_bg,
            category_fg=category_fg,
            row_alt=row_alt,
        )

    def _apply_theme(self) -> None:
        window = self._window
        colors = self._colors
        if window is None or colors is None:
            return
        apply_theme_to_widget_subtree(window)
        self._apply_chrome_theme(colors)
        self._apply_button_theme(colors)
        self._apply_scrollbar_theme(colors)
        if self._carrier_combo is not None:
            self._carrier_combo.apply_theme_styling()
        if self._manifest_canvas is not None:
            try:
                self._manifest_canvas.configure(bg=colors.bg)
            except tk.TclError:
                pass
        if self._add_listbox is not None:
            try:
                self._add_listbox.configure(
                    bg=colors.entry_bg,
                    fg=colors.entry_fg,
                    selectbackground=colors.accent,
                    selectforeground=colors.fg,
                )
            except tk.TclError:
                pass
