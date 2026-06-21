"""Shared site-row filtering helpers for overlay and plan-site refresh."""

from __future__ import annotations

from typing import Any, Dict, List

from ..overlay.fc_cargo import parse_project_linked_fcs


def _site_status_key(site: Dict[str, Any]) -> str:
    return "".join(ch for ch in str(site.get("status", "")).strip().lower() if ch.isalnum())


def build_status_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    active_statuses = {"build", "building", "active", "inprogress"}
    return [
        s
        for s in rows
        if isinstance(s, dict) and _site_status_key(s) in active_statuses
    ]


def parse_sites_payload(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, list):
        return [s for s in data if isinstance(s, dict)]
    if isinstance(data, dict):
        inner = data.get("sites") or data.get("items") or []
        return [s for s in inner if isinstance(s, dict)] if isinstance(inner, list) else []
    return []


def combined_project_linked_fcs(projects: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge linked FC rows from multiple projects, deduplicated by marketId."""
    out: List[Dict[str, Any]] = []
    seen: set[int] = set()
    for project in projects:
        for fc in parse_project_linked_fcs(project):
            try:
                mid = int(fc["marketId"])
            except (KeyError, TypeError, ValueError):
                continue
            if mid in seen:
                continue
            seen.add(mid)
            out.append(dict(fc))
    out.sort(key=lambda x: str(x.get("label", "")).lower())
    return out
