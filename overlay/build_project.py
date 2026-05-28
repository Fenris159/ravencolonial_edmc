"""Build commodity overlay via EDMCModernOverlay."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Mapping, Optional

try:
    from ..api.client import resolve_build_id
except ImportError:  # pragma: no cover
    from api.client import resolve_build_id

from .bridge import OVERLAY_MESSAGE_PREFIX, get_overlay_client, register_build_tracker_group
from .fc_cargo import compute_fc_deltas, resolve_fc_cargo_for_selection
from .formatting import (
    normalize_cargo_hold,
    project_header_line,
    resolve_assignments_for_needs,
    resolve_project_needs,
)
from .layers import ALL_OVERLAY_MESSAGE_IDS, OverlayRectLayer, OverlayTextLayer, OverlayVectorLayer
from .themes import get_overlay_theme
from .render_layers import OverlayRenderBundle, build_overlay_layers
from .trip_estimates import fc_summary_label as fc_summary_label_for, total_fc_deficit

logger = logging.getLogger(__name__)


def _read_overlay_theme_id(plugin: Any) -> str:
    try:
        from config import config

        return (config.get_str("ravencolonial_overlay_theme") or "").strip()
    except Exception:
        return getattr(plugin, "overlay_theme_id", None) or ""


class BuildProjectOverlay:
    def __init__(self, plugin: Any) -> None:
        self._plugin = plugin
        self._last_signature: Optional[str] = None
        self._group_attempted = False

    def enabled(self) -> bool:
        plugin = self._plugin
        if not getattr(plugin, "overlay_ui_enabled", False):
            return False
        return bool(getattr(plugin, "selected_overlay_build_id", None))

    def should_display(self) -> bool:
        """Show overlay when docked, or when Always On is enabled."""
        if not self.enabled():
            return False
        plugin = self._plugin
        if getattr(plugin, "overlay_always_on", False):
            return True
        return bool(getattr(plugin, "is_docked", False))

    def clear(self) -> None:
        self._last_signature = None
        client = get_overlay_client()
        for msg_id in ALL_OVERLAY_MESSAGE_IDS:
            client.send_raw({"id": msg_id, "text": "", "ttl": 0})

    def refresh(self, *, force: bool = False) -> None:
        if not self.should_display():
            self.clear()
            return
        if not self._group_attempted:
            register_build_tracker_group()
            self._group_attempted = True
        bundle = self._compose_layers()
        if not bundle.text_layers:
            self.clear()
            return
        signature = self._bundle_signature(bundle)
        if not force and signature == self._last_signature:
            return
        client = get_overlay_client()
        for msg_id in ALL_OVERLAY_MESSAGE_IDS:
            client.send_raw({"id": msg_id, "text": "", "ttl": 0})
        for rect in bundle.rect_layers:
            self._send_rect(client, rect)
        for vector in bundle.vector_layers:
            self._send_vector(client, vector)
        for layer in bundle.text_layers:
            client.send_message(
                layer.msg_id,
                layer.text,
                layer.color,
                layer.x,
                layer.y,
                ttl=0,
                size="normal",
            )
        self._last_signature = signature

    @staticmethod
    def _send_rect(client: Any, rect: OverlayRectLayer) -> None:
        send_shape = getattr(client, "send_shape", None)
        if callable(send_shape):
            send_shape(
                rect.msg_id,
                "rect",
                rect.border_color,
                rect.fill,
                rect.x,
                rect.y,
                rect.w,
                rect.h,
                0,
            )
            return
        client.send_raw(
            {
                "id": rect.msg_id,
                "type": "shape",
                "shape": "rect",
                "color": rect.border_color,
                "fill": rect.fill,
                "x": rect.x,
                "y": rect.y,
                "w": rect.w,
                "h": rect.h,
                "ttl": 0,
            }
        )

    @staticmethod
    def _bundle_signature(bundle: OverlayRenderBundle) -> str:
        parts: List[str] = []
        for rect in bundle.rect_layers:
            parts.append(f"R|{rect.msg_id}|{rect.fill}|{rect.x}|{rect.y}|{rect.w}|{rect.h}")
        for vector in bundle.vector_layers:
            parts.append(
                f"V|{vector.msg_id}|{vector.color}|{vector.x}|{vector.y1}|{vector.y2}"
            )
        for ly in bundle.text_layers:
            parts.append(f"T|{ly.msg_id}|{ly.color}|{ly.x}|{ly.y}|{ly.text}")
        return "\x1e".join(parts)

    def _compose_layers(self) -> OverlayRenderBundle:
        plugin = self._plugin
        project = self._resolve_tracked_project()
        if project is None:
            return OverlayRenderBundle([], [])

        theme = get_overlay_theme(_read_overlay_theme_id(plugin))

        depot_remaining: Dict[str, int] = {}
        try:
            depot_fields = plugin.build_depot_project_fields(refresh=False)
            if depot_fields:
                depot_remaining = dict(depot_fields.get("remaining_need") or {})
        except Exception:
            pass
        if not depot_remaining and project and self._at_selected_project_depot(plugin, project):
            depot_remaining = dict(getattr(plugin, "last_depot_remaining_need", None) or {})

        needs = resolve_project_needs(project, depot_remaining=depot_remaining)
        if not needs and project is None:
            return OverlayRenderBundle([], [])

        cargo = normalize_cargo_hold(getattr(plugin, "cargo", None))
        complete = bool(project and project.get("complete")) or self._depot_construction_complete()

        if project:
            header = project_header_line(project)
            system = str(project.get("systemName") or "").strip()
            subheader = system if system else None
        elif plugin.is_docked and getattr(plugin, "current_station", None):
            header = str(plugin.current_station)
            subheader = "Colonization site"
        else:
            header = "Colonization build"
            subheader = None

        cmdr = getattr(plugin, "cmdr_name", None)
        if not cmdr:
            client = getattr(plugin, "api_client", None)
            cmdr = getattr(client, "cmdr_name", None) if client else None
        assignments = resolve_assignments_for_needs(needs, project, cmdr)

        fc_deltas = None
        fc_column_title = "FC's"
        fc_cargo: Dict[str, int] = {}
        show_fc_trip_summary = False
        fc_summary_label = "FC's"
        if getattr(plugin, "overlay_carrier_tracking_enabled", False):
            linked = getattr(plugin, "overlay_project_linked_fcs", None) or []
            cargo_by_market = getattr(plugin, "overlay_fc_cargo_by_market", None) or {}
            selection = str(getattr(plugin, "overlay_fc_selection", "all") or "all")
            fc_cargo, fc_column_title = resolve_fc_cargo_for_selection(
                linked_fcs=linked,
                cargo_by_market=cargo_by_market,
                selection=selection,
            )
            fc_deltas = compute_fc_deltas(needs, fc_cargo)
            show_fc_trip_summary = True
            fc_summary_label = fc_summary_label_for(selection, linked)

        return build_overlay_layers(
            header=header,
            subheader=subheader,
            needs=needs,
            cargo=cargo,
            complete=complete,
            assignments=assignments,
            fc_deltas=fc_deltas,
            fc_column_title=fc_column_title,
            ship_cargo_capacity=getattr(plugin, "ship_cargo_capacity", None),
            show_fc_trip_summary=show_fc_trip_summary,
            fc_deficit_total=total_fc_deficit(needs, fc_cargo) if show_fc_trip_summary else None,
            fc_summary_label=fc_summary_label,
            theme=theme,
        )

    def _resolve_tracked_project(self) -> Optional[Dict[str, Any]]:
        plugin = self._plugin
        if not self.enabled():
            return None
        cached = getattr(plugin, "overlay_project_cache", None)
        sel = getattr(plugin, "selected_overlay_build_id", None)
        if isinstance(cached, dict) and sel and resolve_build_id(cached) == str(sel).strip():
            return cached
        return None

    def remember_project(self, project: Optional[Mapping[str, Any]]) -> None:
        plugin = self._plugin
        if isinstance(project, dict) and resolve_build_id(project):
            plugin.overlay_project_cache = dict(project)
            from .fc_cargo import parse_project_linked_fcs

            plugin.overlay_project_linked_fcs = parse_project_linked_fcs(project)
        elif project is None:
            plugin.overlay_project_cache = None
            plugin.overlay_project_linked_fcs = []
            plugin.overlay_fc_cargo_by_market = {}

    @staticmethod
    def _at_selected_project_depot(plugin: Any, project: Dict[str, Any]) -> bool:
        """Use live journal depot only when docked at the selected build's market."""
        if not plugin.is_docked or plugin.current_market_id is None:
            return False
        proj_mid = project.get("marketId") if project.get("marketId") is not None else project.get("MarketID")
        if proj_mid is None:
            return False
        try:
            return int(plugin.current_market_id) == int(proj_mid)
        except (TypeError, ValueError):
            return False
