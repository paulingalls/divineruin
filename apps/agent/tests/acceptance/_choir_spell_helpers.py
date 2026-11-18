"""Shared real-cast driver for Choir spell compatibility checks."""

from unittest.mock import patch

from acceptance._capstone_helpers import _d20, _resolve_round

import combat_turn


async def bolt(ctx, face=20):
    state = ctx.userdata.combat_state
    declarations = {p.id: {"type": "defend"} for p in state.participants if not p.is_fallen}
    declarations[ctx.userdata.player_id] = {"type": "ability", "action": "arcane_bolt", "target_id": "choir_zone"}
    await combat_turn._declare_phase_impl(ctx, declarations)
    with patch("check_resolution.dice_roll", return_value=_d20(face)):
        return await _resolve_round(ctx)
