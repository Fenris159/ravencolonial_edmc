"""Worker + finish helpers for Link Build Site (plan row → active project)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from tkinter import messagebox

from ..api.client import (
    active_project_from_system_location_json,
    completed_project_hint_from_system_location_json,
    plan_site_body_num,
    plan_site_put_body_fields,
    prepare_put_project_body,
)
from ..exc_utils import HTTP_CLIENT_ERRORS
from ..i18n import tr, trf
from ..plugin_config import PluginConfig
from ..http_session import new_http_session
from ..station_names import normalize_dock_station_name
from .overlay_site_rows import parse_sites_payload

if TYPE_CHECKING:
    from .plugin_protocol import PluginProtocol

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LinkBuildSiteContext:
    site_id: Any
    site_obj: Dict[str, Any]
    build_name: str
    build_type: str
    arch_name: str
    market_id: int
    system_address: int
    depot_fields: Dict[str, Any]
    system_bodies: Any
    cached_body_fields: Optional[Dict[str, Any]]


def validate_link_build_site_inputs(
    p: "PluginProtocol",
    *,
    site_obj: Optional[Dict[str, Any]],
    mid: Optional[int],
    sa_cache: Optional[int],
    sa_cur: Optional[int],
) -> Optional[str]:
    """Return a user-facing error string, or None when inputs are valid."""
    if not site_obj or mid is None:
        return tr("Missing site selection or dock MarketID.")
    if sa_cache is None or sa_cur is None or int(sa_cache) != int(sa_cur):
        return tr("Plan sites cache does not match current system — refresh.")
    site_id = site_obj.get("id")
    build_type = str(site_obj.get("buildType") or "").strip()
    if not site_id or not build_type:
        return tr("Selected site is missing id or buildType.")
    plan_name = str(site_obj.get("name") or "").strip()
    dock_name = normalize_dock_station_name(getattr(p, "current_station", None))
    build_name = dock_name or plan_name
    if not build_name:
        return tr("Could not determine a build name from the dock station or selected plan site.")
    arch_name = (p.cmdr_name or "").strip()
    if not arch_name:
        return tr("No commander name — wait for LoadGame or restart EDMC with a journal.")
    return None


def prepare_link_build_site_context(
    p: "PluginProtocol",
    *,
    site_obj: Dict[str, Any],
    sa_cache: int,
    depot_fields: Dict[str, Any],
) -> LinkBuildSiteContext:
    system_bodies = p.get_system_bodies(int(sa_cache))
    cached_body_fields = plan_site_put_body_fields(site_obj, system_bodies)
    if cached_body_fields:
        logger.info(
            "Link Build Site body fields from plan row: bodyNum=%s bodyName=%r",
            cached_body_fields.get("bodyNum"),
            cached_body_fields.get("bodyName"),
        )
    elif plan_site_body_num(site_obj) is None:
        logger.debug("Link Build Site: selected plan row has no bodyNum")
    return build_link_build_site_context(
        p,
        site_obj=site_obj,
        mid=int(p.current_market_id),
        sa_cache=int(sa_cache),
        depot_fields=depot_fields,
        system_bodies=system_bodies,
        cached_body_fields=cached_body_fields,
    )


def build_link_build_site_context(
    p: "PluginProtocol",
    *,
    site_obj: Dict[str, Any],
    mid: int,
    sa_cache: int,
    depot_fields: Dict[str, Any],
    system_bodies: Any,
    cached_body_fields: Optional[Dict[str, Any]],
) -> LinkBuildSiteContext:
    plan_name = str(site_obj.get("name") or "").strip()
    dock_name = normalize_dock_station_name(getattr(p, "current_station", None))
    build_name = dock_name or plan_name
    if dock_name:
        logger.debug(
            "Link Build Site buildName from dock station %r -> %r (plan row was %r)",
            p.current_station,
            build_name,
            plan_name or None,
        )
    else:
        logger.debug(
            "Link Build Site buildName from plan row %r (no dock station name)",
            build_name,
        )
    return LinkBuildSiteContext(
        site_id=site_obj.get("id"),
        site_obj=site_obj,
        build_name=build_name,
        build_type=str(site_obj.get("buildType") or "").strip(),
        arch_name=(p.cmdr_name or "").strip(),
        market_id=int(mid),
        system_address=int(sa_cache),
        depot_fields=depot_fields,
        system_bodies=system_bodies,
        cached_body_fields=cached_body_fields,
    )


def _live_plan_site_check(
    sites: List[Dict[str, Any]],
    site_id: Any,
) -> tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Return (live_row, terminal_out). terminal_out is set when status is no longer plan."""
    for row in sites:
        if not isinstance(row, dict) or str(row.get("id")) != str(site_id):
            continue
        live_status = str(row.get("status") or "").strip().lower()
        if live_status and live_status != "plan":
            return row, {"phase": "site_not_plan", "detail": live_status}
        return row, None
    return None, None


def _location_probe_result(
    response: Any,
    *,
    q_url: str,
    status_code: int,
) -> Optional[Dict[str, Any]]:
    if not response.ok and status_code != 404:
        return {
            "phase": "http_error",
            "detail": f"GET {q_url}: HTTP {status_code} {(getattr(response, 'text', None) or '')[:400]}",
        }
    try:
        data = response.json()
    except ValueError:
        data = (response.text or "").strip() or None
    if active_project_from_system_location_json(data) is not None:
        return {"phase": "exists"}
    if status_code == 404 and completed_project_hint_from_system_location_json(data) is not None:
        return {"phase": "exists_complete"}
    return None


def _put_link_project(
    session: Any,
    *,
    base: str,
    ctx: LinkBuildSiteContext,
    body_fields: Optional[Dict[str, Any]],
    headers: Dict[str, str],
) -> Dict[str, Any]:
    put_base: Dict[str, Any] = {
        "marketId": ctx.market_id,
        "systemAddress": ctx.system_address,
        "buildName": ctx.build_name,
        "buildType": ctx.build_type,
        "systemSiteId": ctx.site_id,
        "architectName": ctx.arch_name,
    }
    if body_fields:
        put_base.update(body_fields)
    payload = prepare_put_project_body(put_base, ctx.depot_fields)
    pu = f"{base}/api/project"
    rp = session.put(pu, headers=headers, json=payload, timeout=15)
    if not rp.ok:
        return {"phase": "put_failed", "detail": (rp.text or "")[:500]}
    try:
        body = rp.json()
    except ValueError:
        body = {}
    return {
        "phase": "ok",
        "site_id": ctx.site_id,
        "build_id": body.get("buildId") if isinstance(body, dict) else None,
        "project": body if isinstance(body, dict) else None,
    }


def run_link_build_site_worker(ctx: LinkBuildSiteContext) -> Dict[str, Any]:
    """HTTP PUT link payload (runs off the main thread)."""
    out: Dict[str, Any] = {"phase": "error", "detail": ""}
    base = PluginConfig.get_api_base().rstrip("/")
    ua = PluginConfig.get_user_agent()
    headers = {"User-Agent": ua, "Accept": "application/json", "Content-Type": "application/json"}
    session = new_http_session(timeout=15)
    try:
        sites_url = f"{base}/api/v2/system/{ctx.system_address}/sites"
        rs = session.get(
            sites_url,
            headers={"User-Agent": ua, "Accept": "application/json"},
            timeout=15,
        )
        live_site_row: Optional[Dict[str, Any]] = None
        if rs.ok:
            try:
                sites_data = rs.json()
            except ValueError:
                sites_data = []
            live_site_row, terminal = _live_plan_site_check(
                parse_sites_payload(sites_data),
                ctx.site_id,
            )
            if terminal is not None:
                return terminal

        site_row_for_body = live_site_row if isinstance(live_site_row, dict) else ctx.site_obj
        body_fields = (
            plan_site_put_body_fields(site_row_for_body, ctx.system_bodies) or
            ctx.cached_body_fields
        )

        q_url = f"{base}/api/system/{ctx.system_address}/{ctx.market_id}"
        rg = session.get(
            q_url,
            headers={"User-Agent": ua, "Accept": "application/json"},
            timeout=15,
        )
        blocked = _location_probe_result(rg, q_url=q_url, status_code=rg.status_code)
        if blocked is not None:
            return blocked
        return _put_link_project(
            session,
            base=base,
            ctx=ctx,
            body_fields=body_fields,
            headers=headers,
        )
    except HTTP_CLIENT_ERRORS as e:
        out["phase"] = "error"
        out["detail"] = str(e)
        return out


def depot_fields_error_message(p: "PluginProtocol") -> Optional[str]:
    """Return user-facing error when depot fields are missing, else None."""
    if not p.construction_depot_data:
        return tr(
            "No ColonisationConstructionDepot data yet. Wait a few seconds after docking, then try again; "
            "if this persists, undock and dock again at the construction site so the journal can update."
        )
    return tr(
        "Could not read any required commodities from the depot snapshot. "
        "Wait for the next depot update, or undock and dock again at the construction site, then retry."
    )


def show_link_build_site_phase_dialog(res: Dict[str, Any]) -> bool:
    """Show modal for terminal failure phases. Returns True if the flow should stop."""
    phase = res.get("phase")
    if phase == "exists":
        messagebox.showinfo(
            tr("Link Build Site"),
            tr("A project already exists at this station — link cancelled."),
        )
        return True
    if phase == "exists_complete":
        messagebox.showinfo(
            tr("Link Build Site"),
            tr("A completed project record already exists at this station — link cancelled."),
        )
        return True
    if phase == "site_not_plan":
        messagebox.showinfo(
            tr("Link Build Site"),
            trf(
                "Selected site is no longer in plan status ({status}) — link cancelled.",
                status=res.get("detail") or "?",
            ),
        )
        return True
    if phase == "put_failed":
        detail = (res.get("detail") or "").strip()
        msg = tr("Server rejected create — see EDMC log.")
        if detail:
            msg = f"{msg}\n{detail[:400]}"
        messagebox.showerror(tr("Link Build Site"), msg)
        return True
    if phase == "error":
        messagebox.showerror(tr("Link Build Site"), res.get("detail") or tr("Unknown error"))
        return True
    return False


def apply_link_build_site_success(
    p: "PluginProtocol",
    res: Dict[str, Any],
    depot_fields: Dict[str, Any],
) -> None:
    sid_mark = res.get("site_id")
    if sid_mark:
        p.plan_sites_rows = [
            r
            for r in p.plan_sites_rows
            if not (isinstance(r, dict) and str(r.get("id")) == str(sid_mark))
        ]
    p.selected_plan_site_id = None
    p.selected_plan_site_obj = None
    bid = res.get("build_id")
    if bid:
        p.current_build_id = bid
        p.maybe_clear_phantom_commodities(bid, res.get("project"))
        p.queue_initial_project_supply_update(bid, depot_fields)
    p.invalidate_project_location_cache()
    messagebox.showinfo(
        tr("Link Build Site"),
        trf("Linked plan site. buildId={bid}", bid=bid or "?"),
    )
