"""Localized fleet-carrier jump countdown lines for the build overlay footer."""

from __future__ import annotations

from typing import List

try:
    from ..fc_jump_timer import (
        JUMP_LOCK_SECONDS,
        PAD_LOCKDOWN_SECONDS,
        FleetCarrierJumpPhase,
        CarrierJumpSnapshot,
        format_countdown,
    )
    from ..i18n import tr, trf
except ImportError:  # pragma: no cover
    from fc_jump_timer import (  # type: ignore[no-redef]
        JUMP_LOCK_SECONDS,
        PAD_LOCKDOWN_SECONDS,
        FleetCarrierJumpPhase,
        CarrierJumpSnapshot,
        format_countdown,
    )
    from i18n import tr, trf  # type: ignore[no-redef]


def format_fc_jump_overlay_lines(
    snap: CarrierJumpSnapshot,
    delta: int,
    *,
    carrier_label: str = "",
) -> List[str]:
    label = carrier_label.strip()
    prefix = f"{label}: " if label else ""
    cd = format_countdown(delta)
    if snap.phase == FleetCarrierJumpPhase.COOLDOWN and delta > 0:
        return [trf("> {prefix}Jump cooldown {countdown}", prefix=prefix, countdown=cd)]

    if snap.phase != FleetCarrierJumpPhase.JUMPING or delta <= 0:
        return []

    dest = (snap.jump_destination_body or snap.jump_destination or tr("Unknown")).strip()
    lines = [trf("> {prefix}Departure to {destination} in {countdown}", prefix=prefix, destination=dest, countdown=cd)]
    if delta < PAD_LOCKDOWN_SECONDS:
        lines.append(trf("> {prefix}Landing pads locked down", prefix=prefix))
    elif delta < JUMP_LOCK_SECONDS:
        lines.append(
            trf(
                "> {prefix}Landing pad lockdown in {countdown}",
                prefix=prefix,
                countdown=format_countdown(delta - PAD_LOCKDOWN_SECONDS),
            )
        )
    else:
        lines.append(
            trf(
                "> {prefix}Jump initiation in {countdown}",
                prefix=prefix,
                countdown=format_countdown(delta - JUMP_LOCK_SECONDS),
            )
        )
    return lines
