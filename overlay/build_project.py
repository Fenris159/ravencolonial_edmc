"""Build commodity overlay via EDMCModernOverlay."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Mapping, Optional, Set

try:
    from ..api.client import resolve_build_id
except ImportError:  # pragma: no cover
    from api.client import resolve_build_id

from .bridge import (
    OVERLAY_MESSAGE_PREFIX,
    get_overlay_client,
    register_build_tracker_group,
    seed_preferred_overlay_group_defaults_once,
    send_overlay_text,
)
from .fc_cargo import compute_fc_deltas, parse_project_linked_fcs, resolve_fc_cargo_for_selection
from .formatting import (
    merge_need_maps,
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
OVERLAY_SESSION_TTL_SECONDS = 24 * 60 * 60
OVERLAY_TRACK_ALL_KEY = "__OVERLAY_TRACK_ALL__"


def aggregate_project_cache(projects: List[Mapping[str, Any]]) -> Dict[str, Any]:
    """Build a synthetic project view whose commodities are all active project needs."""
    valid = [p for p in projects if isinstance(p, Mapping) and not p.get("complete")]
    needs = merge_need_maps(
        *(p.get("commodities") for p in valid if isinstance(p.get("commodities"), Mapping))
    )
    systems = sorted(
        {
            str(p.get("systemName") or "").strip()
            for p in valid
            if str(p.get("systemName") or "").strip()
        },
        key=str.casefold,
    )
    linked_fcs: List[Dict[str, Any]] = []
    seen_fcs: set[int] = set()
    for project in valid:
        for fc in parse_project_linked_fcs(project):
            try:
                mid = int(fc["marketId"])
            except (KeyError, TypeError, ValueError):
                continue
            if mid in seen_fcs:
                continue
            seen_fcs.add(mid)
            linked_fcs.append(dict(fc))
    linked_fcs.sort(key=lambda x: str(x.get("label", "")).lower())
    return {
        "buildId": OVERLAY_TRACK_ALL_KEY,
        "buildName": "Track All",
        "buildType": f"{len(valid)} builds",
        "systemName": ", ".join(systems[:3]) + (" ..." if len(systems) > 3 else ""),
        "commodities": needs,
        "linkedFC": linked_fcs,
        "complete": bool(valid) and not needs,
    }


def _read_overlay_theme_id(plugin: Any) -> str:
    try:
        from config import config

        return (config.get_str("ravencolonial_overlay_theme") or "").strip()
    except Exception:
        return getattr(plugin, "overlay_theme_id", None) or ""


def _decorative_shapes_enabled(plugin: Any) -> bool:
    """Keep optional shape layers opt-in; some Modern Overlay builds crash in native Qt painting."""
    try:
        from config import config

        return bool(config.get_bool("ravencolonial_overlay_decorative_shapes", default=False))
    except Exception:
        return bool(getattr(plugin, "overlay_decorative_shapes_enabled", False))


def _row_stripes_enabled(plugin: Any) -> bool:
    """Keep subtle row striping on by default; it is just filled rects, not line art."""
    try:
        from config import config

        return bool(config.get_bool("ravencolonial_overlay_row_stripes", default=True))
    except Exception:
        return bool(getattr(plugin, "overlay_row_stripes_enabled", True))


class BuildProjectOverlay:
    def __init__(self, plugin: Any) -> None:
        self._plugin = plugin
        self._last_signature: Optional[str] = None
        self._group_attempted = False
        self._active_message_ids: Set[str] = set()
        self._full_clear_done = False

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
        ids_to_clear = set(self._active_message_ids) | set(ALL_OVERLAY_MESSAGE_IDS)
        if not ids_to_clear:
            self._last_signature = None
            logger.debug("Build overlay clear skipped: no active message ids")
            return
        self._last_signature = None
        client = get_overlay_client()
        logger.debug("Build overlay clear active ids: count=%d", len(ids_to_clear))
        for msg_id in sorted(ids_to_clear):
            client.send_raw({"id": msg_id, "text": "", "ttl": 0})
        self._active_message_ids.clear()
        self._full_clear_done = True

    def refresh(self, *, force: bool = False) -> None:
        plugin = self._plugin
        cached = getattr(plugin, "overlay_project_cache", None)
        selected = getattr(plugin, "selected_overlay_build_id", None)
        cached_build_id = resolve_build_id(cached) if isinstance(cached, dict) else None
        logger.debug(
            "Build overlay refresh start: enabled=%s selected=%s cached=%s cached_build_id=%s always_on=%s docked=%s force=%s",
            getattr(plugin, "overlay_ui_enabled", None),
            selected,
            isinstance(cached, dict),
            cached_build_id,
            getattr(plugin, "overlay_always_on", None),
            getattr(plugin, "is_docked", None),
            force,
        )
        if not self.should_display():
            logger.debug(
                "Build overlay clear: not displayable enabled=%s selected=%s always_on=%s docked=%s",
                getattr(plugin, "overlay_ui_enabled", None),
                getattr(plugin, "selected_overlay_build_id", None),
                getattr(plugin, "overlay_always_on", None),
                getattr(plugin, "is_docked", None),
            )
            self.clear()
            return
        if not self._group_attempted:
            register_build_tracker_group()
            self._group_attempted = True
        bundle = self._compose_layers()
        if not bundle.text_layers:
            plugin = self._plugin
            logger.debug(
                "Build overlay clear: no renderable layers selected=%s cached_project=%s",
                getattr(plugin, "selected_overlay_build_id", None),
                isinstance(getattr(plugin, "overlay_project_cache", None), dict),
            )
            self.clear()
            return
        signature = self._bundle_signature(bundle)
        if not force and signature == self._last_signature:
            logger.debug("Build overlay refresh skipped: unchanged signature")
            return
        current_message_ids = {
            *(rect.msg_id for rect in bundle.rect_layers),
            *(vector.msg_id for vector in bundle.vector_layers),
            *(layer.msg_id for layer in bundle.text_layers),
        }
        client = get_overlay_client()
        stale_message_ids = set(self._active_message_ids) - current_message_ids
        if not self._full_clear_done:
            stale_message_ids |= set(ALL_OVERLAY_MESSAGE_IDS) - current_message_ids
            self._full_clear_done = True
        for msg_id in sorted(stale_message_ids):
            client.send_raw({"id": msg_id, "text": "", "ttl": 0})
        for rect in bundle.rect_layers:
            self._send_rect(client, rect)
        for vector in bundle.vector_layers:
            self._send_vector(client, vector)
        for layer in bundle.text_layers:
            send_overlay_text(
                client,
                layer.msg_id,
                layer.text,
                layer.color,
                layer.x,
                layer.y,
                ttl=OVERLAY_SESSION_TTL_SECONDS,
                size=layer.size,
                weight=layer.weight,
            )
        self._active_message_ids = current_message_ids
        self._last_signature = signature
        seed_preferred_overlay_group_defaults_once()
        logger.debug(
            "Build overlay sent: text_layers=%d rect_layers=%d vector_layers=%d selected=%s",
            len(bundle.text_layers),
            len(bundle.rect_layers),
            len(bundle.vector_layers),
            getattr(self._plugin, "selected_overlay_build_id", None),
        )

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
                OVERLAY_SESSION_TTL_SECONDS,
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
                "ttl": OVERLAY_SESSION_TTL_SECONDS,
            }
        )

    @staticmethod
    def _send_vector(client: Any, vector: OverlayVectorLayer) -> None:
        client.send_raw(
            {
                "id": vector.msg_id,
                "type": "shape",
                "shape": "vect",
                "color": vector.color,
                "fill": "none",
                "vector": [
                    {"x": int(vector.x), "y": int(vector.y1)},
                    {"x": int(vector.x), "y": int(vector.y2)},
                ],
                "ttl": OVERLAY_SESSION_TTL_SECONDS,
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
            logger.debug(
                "Build overlay compose: no matching project selected=%s cached=%s cached_build_id=%s",
                getattr(plugin, "selected_overlay_build_id", None),
                isinstance(getattr(plugin, "overlay_project_cache", None), dict),
                resolve_build_id(getattr(plugin, "overlay_project_cache", None))
                if isinstance(getattr(plugin, "overlay_project_cache", None), dict)
                else None,
            )
            return OverlayRenderBundle([], [])

        theme = get_overlay_theme(_read_overlay_theme_id(plugin))

        depot_remaining: Dict[str, int] = {}
        depot_authoritative = False
        aggregate_mode = getattr(plugin, "selected_overlay_build_id", None) == OVERLAY_TRACK_ALL_KEY
        if not aggregate_mode:
            try:
                depot_fields = plugin.build_depot_project_fields(refresh=False)
                if depot_fields:
                    depot_remaining = dict(depot_fields.get("remaining_need") or {})
                    depot_authoritative = True
            except Exception:
                pass
        if not aggregate_mode and not depot_authoritative and project and self._at_selected_project_depot(plugin, project):
            cached_depot = getattr(plugin, "last_depot_remaining_need", None)
            if cached_depot is not None:
                depot_remaining = dict(cached_depot)
                depot_authoritative = True

        needs = resolve_project_needs(
            project,
            depot_remaining=depot_remaining if depot_authoritative else None,
            depot_authoritative=depot_authoritative,
        )
        logger.debug(
            "Build overlay compose project: build_id=%s needs_count=%d needs_total=%d depot_authoritative=%s cargo_count=%d carrier_tracking=%s",
            resolve_build_id(project),
            len(needs),
            sum(int(v) for v in needs.values()),
            depot_authoritative,
            len(normalize_cargo_hold(getattr(plugin, "cargo", None))),
            getattr(plugin, "overlay_carrier_tracking_enabled", False),
        )
        if not needs and project is None:
            return OverlayRenderBundle([], [])

        cargo = normalize_cargo_hold(getattr(plugin, "cargo", None))
        complete = bool(project and project.get("complete")) or (
            not aggregate_mode and self._depot_construction_complete()
        )

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

        bundle = build_overlay_layers(
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
            row_stripes=_row_stripes_enabled(plugin),
            column_dividers=_decorative_shapes_enabled(plugin),
        )
        logger.debug(
            "Build overlay compose layers: text_layers=%d rect_layers=%d vector_layers=%d header=%s subheader=%s",
            len(bundle.text_layers),
            len(bundle.rect_layers),
            len(bundle.vector_layers),
            bool(header),
            bool(subheader),
        )
        return bundle

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
            plugin.overlay_project_linked_fcs = parse_project_linked_fcs(project)
        elif project is None:
            plugin.overlay_project_cache = None
            plugin.overlay_project_linked_fcs = []
            plugin.overlay_fc_cargo_by_market = {}

    def remember_all_projects(self, projects: List[Mapping[str, Any]]) -> None:
        plugin = self._plugin
        plugin.overlay_project_cache_by_build_id = {
            str(resolve_build_id(project)): dict(project)
            for project in projects
            if isinstance(project, Mapping) and resolve_build_id(project)
        }
        aggregate = aggregate_project_cache(projects)
        plugin.overlay_project_cache = aggregate
        plugin.overlay_project_linked_fcs = parse_project_linked_fcs(aggregate)

    def _depot_construction_complete(self) -> bool:
        """Return live journal completion state when a depot snapshot is available."""
        entry = getattr(self._plugin, "construction_depot_data", None)
        if not isinstance(entry, Mapping):
            return False
        return bool(entry.get("ConstructionComplete"))

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
