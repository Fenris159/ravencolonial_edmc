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


def format_fc_jump_overlay_lines(snap: CarrierJumpSnapshot, delta: int) -> List[str]:
    cd = format_countdown(delta)
    if snap.phase == FleetCarrierJumpPhase.COOLDOWN and delta > 0:
        return [trf("> Jump cooldown {countdown}", countdown=cd)]

    if snap.phase != FleetCarrierJumpPhase.JUMPING or delta <= 0:
        return []

    dest = (snap.jump_destination_body or snap.jump_destination or tr("Unknown")).strip()
    lines = [trf("> Departure to {destination} in {countdown}", destination=dest, countdown=cd)]
    if delta < PAD_LOCKDOWN_SECONDS:
        lines.append(tr("Landing pads locked down"))
    elif delta < JUMP_LOCK_SECONDS:
        lines.append(
            trf(
                "Landing pad lockdown in {countdown}",
                countdown=format_countdown(delta - PAD_LOCKDOWN_SECONDS),
            )
        )
    else:
        lines.append(
            trf(
                "Jump initiation in {countdown}",
                countdown=format_countdown(delta - JUMP_LOCK_SECONDS),
            )
        )
    return lines
