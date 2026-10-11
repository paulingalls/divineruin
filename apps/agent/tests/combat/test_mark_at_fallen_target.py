"""A non-damage hostile mark is wasted on a Fallen player (story-154 review F1)."""

import pytest
from combat.test_enemy_mark_actions import _action, _mark_state, _run_round


@pytest.mark.asyncio
async def test_a_rally_mark_at_a_fallen_player_is_wasted_and_writes_no_mark():
    state = _mark_state([("marker", _action("ashmark_sergeant", "Rally"))])
    fallen = state.get_participant("player_1")
    assert fallen is not None
    fallen.hp_current, fallen.is_fallen = 0, True

    ctx, _, payload = await _run_round(state)
    marker = next(packet for packet in payload["packets"] if packet["actor_id"] == "marker")

    assert (marker["resolved"], marker["reason"]) == (False, "Player 1 already fell")
    assert "player_1" not in ctx.userdata.combat_state.focus_marks
