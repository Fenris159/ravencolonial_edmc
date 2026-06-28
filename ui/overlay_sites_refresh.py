"""Background worker + lookup resolution for overlay build-site refresh."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, Optional

from ..exc_utils import HTTP_CLIENT_ERRORS
from ..http_session import new_http_session
from ..i18n import tr
from .overlay_site_rows import build_status_rows, parse_sites_payload

if TYPE_CHECKING:
    from .plugin_protocol import PluginProtocol

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OverlaySitesLookup:
    lookup_value: object
    lookup_key: object
    lookup_system_address: Optional[int]


def resolve_overlay_sites_lookup(
    plugin: "PluginProtocol",
    *,
    search_enabled: bool,
    search_name: str,
    get_system_address_from_journal: Any,
    normalize_search_key: Any,
) -> Optional[OverlaySitesLookup]:
    if search_enabled and not search_name:
        return None
    if search_name:
        lookup_value: object = " ".join(search_name.split())
        lookup_key: object = normalize_search_key(str(lookup_value))
        return OverlaySitesLookup(
            lookup_value=lookup_value,
            lookup_key=lookup_key,
            lookup_system_address=None,
        )
    sa = plugin.current_system_address or get_system_address_from_journal()
    if sa is not None and plugin.current_system_address is None:
        plugin.set_current_system_address(sa)
    if sa is None:
        return None
    return OverlaySitesLookup(
        lookup_value=int(sa),
        lookup_key=int(sa),
        lookup_system_address=int(sa),
    )


def missing_lookup_detail(search_enabled: bool, search_name: str) -> str:
    if search_enabled and not search_name:
        return tr("Enter a system name.")
    return tr("No system context")


def fetch_overlay_sites_worker(
    *,
    base: str,
    fallback_base: str,
    seg: str,
    headers: Dict[str, str],
    lookup_key: object,
    lookup_system_address: Optional[int],
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "ok": False,
        "reason": None,
        "system_key": lookup_key,
        "system_address": lookup_system_address,
        "build_rows": [],
    }
    bases = [base]
    if fallback_base and fallback_base.lower() != base.lower():
        bases.append(fallback_base)
    try:
        last_error = None
        for api_base in bases:
            try:
                url = f"{api_base.rstrip('/')}/api/v2/system/{seg}/sites"
                session = new_http_session(timeout=15)
                sr = session.get(url, headers=headers, timeout=15)
                sr.raise_for_status()
                sites = parse_sites_payload(sr.json())
                result["raw_rows_count"] = len(sites)
                result["build_rows"] = build_status_rows(sites)
                result["api_base"] = api_base
                result["ok"] = True
                break
            except HTTP_CLIENT_ERRORS as e:
                last_error = e
                if api_base == bases[-1]:
                    raise
                logger.debug(
                    "Overlay sites refresh retrying default API base after %s failed: %s",
                    api_base,
                    e,
                )
        if not result["ok"] and last_error is not None:
            raise last_error
    except HTTP_CLIENT_ERRORS as e:
        result["reason"] = "http_error"
        result["detail"] = str(e)
    return result
