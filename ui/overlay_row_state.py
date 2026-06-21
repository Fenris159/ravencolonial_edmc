"""Pure overlay-row widget state computation + application."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import tkinter as tk

if TYPE_CHECKING:
    from .overlay_row import OverlayBuildRowController


@dataclass(frozen=True)
class OverlayRowWidgetState:
    overlay_on: bool
    modern_enabled: bool
    popout_enabled: bool
    carrier_tracking: bool
    refresh_ok: bool
    always_on_interactable: bool
    build_combo_readonly: bool
    fc_combo_readonly: bool


def compute_overlay_row_widget_state(
    plugin: Any,
    *,
    overlay_on: bool,
    refresh_inflight: bool,
    has_build_rows: bool,
) -> OverlayRowWidgetState:
    p = plugin
    modern = bool(getattr(p, "overlay_modern_enabled", False))
    popout = bool(getattr(p, "overlay_popout_enabled", False))
    carrier = bool(getattr(p, "overlay_carrier_tracking_enabled", False))
    has_build = bool(getattr(p, "selected_overlay_build_id", None))
    build_combo_ok = bool(overlay_on and has_build_rows)
    fc_readonly = bool(
        overlay_on and
        carrier and
        has_build and
        build_combo_ok
    )
    return OverlayRowWidgetState(
        overlay_on=overlay_on,
        modern_enabled=modern,
        popout_enabled=popout,
        carrier_tracking=carrier,
        refresh_ok=bool(overlay_on and not refresh_inflight),
        always_on_interactable=bool(overlay_on and modern),
        build_combo_readonly=build_combo_ok,
        fc_combo_readonly=fc_readonly,
    )


def _safe_combo_state(combo: Any, state: str) -> None:
    if combo is None:
        return
    try:
        combo.configure(state=state)
    except tk.TclError:
        pass


def apply_overlay_row_widget_state(
    ctrl: "OverlayBuildRowController",
    *,
    overlay_on: bool,
    refresh_inflight: bool,
    has_build_rows: bool,
) -> None:
    p = ctrl.plugin
    ctrl._sync_optional_controls_visibility(overlay_on)

    if ctrl.always_on_var is not None:
        p.overlay_always_on = bool(overlay_on and ctrl.always_on_var.get())
    if getattr(p, "overlay_popout_enabled", False):
        p.overlay_always_on = False
    if ctrl.carrier_var is not None:
        p.overlay_carrier_tracking_enabled = bool(
            overlay_on and ctrl.carrier_var.get()
        )

    state = compute_overlay_row_widget_state(
        p,
        overlay_on=overlay_on,
        refresh_inflight=refresh_inflight,
        has_build_rows=has_build_rows,
    )

    if ctrl.refresh_btn is not None:
        try:
            ctrl.refresh_btn.configure(
                state=tk.NORMAL if state.refresh_ok else tk.DISABLED
            )
        except tk.TclError:
            pass

    if ctrl.always_on_cb is not None:
        ctrl.always_on_cb.set_interactable(state.always_on_interactable)
    if ctrl.search_cb is not None:
        ctrl.search_cb.set_interactable(state.overlay_on)
    if ctrl.carrier_cb is not None:
        ctrl.carrier_cb.set_interactable(state.overlay_on)

    ctrl._sync_build_lookup_widgets(state.overlay_on)

    if not state.overlay_on:
        _safe_combo_state(ctrl.combo, "disabled")
    elif state.build_combo_readonly:
        _safe_combo_state(ctrl.combo, "readonly")
    else:
        _safe_combo_state(ctrl.combo, "disabled")

    if state.fc_combo_readonly:
        _safe_combo_state(ctrl.fc_combo, "readonly")
    else:
        _safe_combo_state(ctrl.fc_combo, "disabled")
