"""Pure helpers for build-project overlay text."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple


try:
    from ..api.client import normalize_commodity_key
except ImportError:  # pragma: no cover
    from api.client import normalize_commodity_key


def format_commodity_label(key: str) -> str:
    if not key:
        return ""
    parts = key.replace("_", " ").split()
    return " ".join(p[:1].upper() + p[1:] if p else "" for p in parts)


def merge_need_maps(*maps: Optional[Mapping[str, Any]]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for m in maps:
        if not m:
            continue
        for raw_k, raw_v in m.items():
            nk = normalize_commodity_key(str(raw_k))
            if not nk:
                continue
            try:
                amount = int(raw_v)
            except (TypeError, ValueError):
                continue
            if amount <= 0:
                continue
            out[nk] = out.get(nk, 0) + amount
    return out


def normalize_cargo_hold(hold: Optional[Mapping[str, Any]]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    if not hold:
        return out
    for raw_k, raw_v in hold.items():
        nk = normalize_commodity_key(str(raw_k))
        if not nk:
            continue
        try:
            count = int(raw_v)
        except (TypeError, ValueError):
            continue
        if count > 0:
            out[nk] = out.get(nk, 0) + count
    return out



AssignmentKind = Optional[str]  # "me", "other", or None

# SrvSurvey parity: pin = yours, x = assigned to another commander
ASSIGN_SYMBOL_ME = "📌"  # pin
ASSIGN_SYMBOL_OTHER = "x"
ASSIGN_COLUMN_HEADER = "Asg"


def _commodity_assigned_to(commanders: Mapping[str, Any], commodity_key: str) -> List[str]:
    """Commander names assigned to this commodity (normalized key)."""
    assigned: List[str] = []
    for raw_cmdr, raw_items in commanders.items():
        if raw_items is None:
            continue
        items: Any = raw_items
        if isinstance(items, dict):
            items = items.keys()
        if not isinstance(items, (list, tuple, set)):
            continue
        for raw_name in items:
            nk = normalize_commodity_key(str(raw_name))
            if nk == commodity_key:
                assigned.append(str(raw_cmdr).strip())
                break
    return assigned


def resolve_assignments_for_needs(
    needs: Mapping[str, int],
    project: Optional[Mapping[str, Any]],
    cmdr_name: Optional[str],
) -> Dict[str, AssignmentKind]:
    """
    Map normalized commodity keys to assignment hint for overlay rows.

    Matches SrvSurvey ColonyData.getNeeds: pin if assigned to you, block if only others.
    """
    out: Dict[str, AssignmentKind] = {}
    if not project or not cmdr_name or not needs:
        return out
    commanders = project.get("commanders")
    if not isinstance(commanders, dict) or not commanders:
        return out
    me = str(cmdr_name).strip().lower()
    if not me:
        return out
    for key in needs:
        if int(needs.get(key, 0) or 0) <= 0:
            continue
        nk = normalize_commodity_key(str(key))
        if not nk:
            continue
        assigned_to = _commodity_assigned_to(commanders, nk)
        if not assigned_to:
            continue
        if any(c.lower() == me for c in assigned_to):
            out[nk] = "me"
        else:
            out[nk] = "other"
    return out


def _format_assignment_cell(kind: AssignmentKind) -> str:
    if kind == "me":
        return ASSIGN_SYMBOL_ME
    if kind == "other":
        return ASSIGN_SYMBOL_OTHER
    return " "


def build_overlay_text(
    *,
    header: str,
    needs: Mapping[str, int],
    cargo: Mapping[str, int],
    subheader: Optional[str] = None,
    complete: bool = False,
    assignments: Optional[Mapping[str, AssignmentKind]] = None,
) -> str:
    lines: List[str] = []
    if header:
        lines.append(header.strip())
    if subheader:
        lines.append(subheader.strip())
    if complete:
        lines.append("Construction complete")
        return "\n".join(lines)
    if not needs:
        lines.append("No remaining commodities")
        return "\n".join(lines)

    assign_map = dict(assignments or {})
    show_assign = bool(assign_map)

    rows: List[Tuple[str, str, int, int]] = []
    total_need = 0
    for key in sorted(needs.keys()):
        need = int(needs[key])
        if need <= 0:
            continue
        have = int(cargo.get(key, 0))
        nk = normalize_commodity_key(str(key))
        asg = _format_assignment_cell(assign_map.get(nk) if show_assign else None)
        rows.append((format_commodity_label(key), asg, need, have))
        total_need += need
    if not rows:
        lines.append("No remaining commodities")
        return "\n".join(lines)

    name_w = max(len("Commodity"), max(len(r[0]) for r in rows))
    if show_assign:
        lines.append(f"{ASSIGN_COLUMN_HEADER}  {'Commodity'.ljust(name_w)}  Need   Have")
        lines.append("-" * (name_w + 20))
        for name, asg, need, have in rows:
            lines.append(f"{asg:>3}  {name.ljust(name_w)}  {need:5d}  {have:5d}")
        lines.append("")
        lines.append(f"{ASSIGN_SYMBOL_ME} = yours   {ASSIGN_SYMBOL_OTHER} = other CMDR")
    else:
        lines.append(f"{'Commodity'.ljust(name_w)}  Need   Have")
        lines.append("-" * (name_w + 14))
        for name, _asg, need, have in rows:
            lines.append(f"{name.ljust(name_w)}  {need:5d}  {have:5d}")
    lines.append("")
    lines.append(f"Remaining: {total_need:,} units")
    return "\n".join(lines)


def project_header_line(project: Mapping[str, Any]) -> str:
    name = str(project.get("buildName") or project.get("name") or "Build").strip()
    build_type = str(project.get("buildType") or "").strip()
    if build_type:
        return f"{name} ({build_type})"
    return name


def resolve_project_needs(
    project: Optional[Mapping[str, Any]],
    *,
    depot_remaining: Optional[Mapping[str, int]] = None,
) -> Dict[str, int]:
    if depot_remaining:
        merged = merge_need_maps(depot_remaining)
        if merged:
            return merged
    if project:
        commodities = project.get("commodities")
        if isinstance(commodities, dict):
            return merge_need_maps(commodities)
    return {}
