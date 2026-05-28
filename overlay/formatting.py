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


def build_overlay_text(
    *,
    header: str,
    needs: Mapping[str, int],
    cargo: Mapping[str, int],
    subheader: Optional[str] = None,
    complete: bool = False,
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

    rows: List[Tuple[str, int, int]] = []
    total_need = 0
    for key in sorted(needs.keys()):
        need = int(needs[key])
        if need <= 0:
            continue
        have = int(cargo.get(key, 0))
        rows.append((format_commodity_label(key), need, have))
        total_need += need
    if not rows:
        lines.append("No remaining commodities")
        return "\n".join(lines)

    name_w = max(len("Commodity"), max(len(r[0]) for r in rows))
    lines.append(f"{'Commodity'.ljust(name_w)}  Need   Have")
    lines.append("-" * (name_w + 14))
    for name, need, have in rows:
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
