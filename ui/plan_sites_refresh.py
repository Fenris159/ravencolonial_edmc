"""Background worker for plan-site combobox refresh (architect gate + /sites)."""

from __future__ import annotations

import logging
import urllib.parse
from typing import Any, Dict

from ..api.client import parse_system_architect_response
from ..orbital_allowlist import is_orbital_build_type
from ..exc_utils import HTTP_CLIENT_ERRORS
from .overlay_site_rows import build_status_rows, parse_sites_payload

logger = logging.getLogger(__name__)


def fetch_plan_sites_worker(
    *,
    base: str,
    system_address: int,
    cmdr_name: str,
    headers: Dict[str, str],
) -> Dict[str, Any]:
    """HTTP work for ``start_plan_sites_refresh`` (runs off the main thread)."""
    result: Dict[str, Any] = {
        "ok": False,
        "reason": None,
        "system_address": int(system_address),
        "rows": [],
    }
    try:
        import timeout_session
    except ImportError:  # pragma: no cover - provided by EDMC at runtime
        result["reason"] = "no_timeout_session"
        return result

    session = timeout_session.new_session(timeout=15)
    snap = (cmdr_name or "").strip()
    if not snap:
        result["reason"] = "no_cmdr"
        return result

    seg = urllib.parse.quote(str(system_address), safe="")
    try:
        arch_url = f"{base.rstrip('/')}/api/v2/system/{seg}/architect"
        ar = session.get(arch_url, headers=headers, timeout=12)
        ar.raise_for_status()
        try:
            arch_raw = ar.json()
        except ValueError:
            arch_raw = (ar.text or "").strip()
        arch_name = parse_system_architect_response(arch_raw)
        is_architect = bool(
            arch_name and str(arch_name).strip().lower() == snap.lower()
        )
        logger.debug(
            "Plan sites architect gate: api=%r cmdr=%r match=%s plan_rows_pending",
            arch_name,
            snap,
            is_architect,
        )

        sites_url = f"{base.rstrip('/')}/api/v2/system/{seg}/sites"
        sr = session.get(sites_url, headers=headers, timeout=15)
        sr.raise_for_status()
        sites = parse_sites_payload(sr.json())
        plan_rows = [
            s
            for s in sites
            if isinstance(s, dict) and str(s.get("status", "")).lower() == "plan"
        ]
        build_rows = build_status_rows(sites)
        result["build_rows"] = build_rows
        if is_architect:
            result["rows"] = plan_rows
            result["allow_create_new"] = True
        else:
            result["rows"] = [
                s for s in plan_rows if is_orbital_build_type(s.get("buildType"))
            ]
            result["allow_create_new"] = False
        logger.debug(
            "Plan sites refresh: %d plan, %d build, showing %d plan (architect=%s)",
            len(plan_rows),
            len(build_rows),
            len(result["rows"]),
            is_architect,
        )
        result["ok"] = True
        return result
    except HTTP_CLIENT_ERRORS as e:
        result["reason"] = "http_error"
        result["detail"] = str(e)
        return result
