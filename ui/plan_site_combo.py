"""Pure helpers for plan-site combobox row state."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..i18n import tr


@dataclass
class PlanSiteComboUpdate:
    values: List[str]
    display: str
    state: str
    display_to_id: Dict[str, Optional[str]] = field(default_factory=dict)
    clear_selection: bool = False


def plan_site_cache_matches_system(key: Any, current: Any) -> bool:
    if key is None or current is None:
        return False
    try:
        return int(current) == int(key)
    except (TypeError, ValueError):
        return False


def plan_site_transient_update(message: str) -> PlanSiteComboUpdate:
    m = str(message)
    return PlanSiteComboUpdate(values=[m], display=m, state="disabled", clear_selection=True)


def plan_site_stale_cache_update() -> PlanSiteComboUpdate:
    msg = tr("Please Refresh")
    return PlanSiteComboUpdate(values=[msg], display=msg, state="disabled")


def plan_site_empty_rows_update(
    *,
    allow_create_new: bool,
    create_new_id: str,
) -> PlanSiteComboUpdate:
    placeholder = tr("— choose site —")
    create_new_lbl = tr("Create New")
    if allow_create_new:
        mapping = {placeholder: None, create_new_lbl: create_new_id}
        return PlanSiteComboUpdate(
            values=[placeholder, create_new_lbl],
            display=placeholder,
            state="readonly",
            display_to_id=mapping,
        )
    no_orb = tr("No Orbitals")
    return PlanSiteComboUpdate(
        values=[no_orb],
        display=no_orb,
        state="disabled",
        clear_selection=True,
    )


def plan_site_populated_rows_update(
    rows: List[Dict[str, Any]],
    *,
    allow_create_new: bool,
    create_new_id: str,
) -> PlanSiteComboUpdate:
    placeholder = tr("— choose site —")
    create_new_lbl = tr("Create New")
    mapping: Dict[str, Optional[str]] = {placeholder: None}
    labels: List[str] = [placeholder]
    if allow_create_new:
        labels.append(create_new_lbl)
        mapping[create_new_lbl] = create_new_id
    for site in rows:
        name = str(site.get("name") or "").strip()
        bt = str(site.get("buildType") or "").strip()
        label = f"{name} | {bt}" if name or bt else tr("(unnamed site)")
        sid = site.get("id")
        if label in mapping:
            label = f"{label}  ({sid})"
        mapping[label] = str(sid) if sid is not None else None
        labels.append(label)
    return PlanSiteComboUpdate(
        values=labels,
        display=placeholder,
        state="readonly",
        display_to_id=mapping,
    )
