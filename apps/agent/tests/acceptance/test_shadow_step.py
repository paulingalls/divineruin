"""Shadow Step through the registered declaration and resolution tools."""

import pytest
from acceptance._enemy_opportunity_helpers import declare, strikes
from acceptance._shadow_step_helpers import DESTINATION, STEP, step
from acceptance._shadow_step_helpers import shadow_fight as shadow_fight
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_architect_fight import pos
from acceptance.test_opportunity_strike import participant, reconnect
from acceptance.test_self_buff_electives import discovered, receipt
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory

import ability_persistence
import architect_entomb
import combat_spatial
import combat_structures
import concealment
import db_queries
import mentor_variant_progress


@pytest.mark.parametrize("cover", ["wall", "endpoint", "chamber", "smoke", "variant"])
async def test_step_commits_and_survives_reconnect(shadow_fight: MawlingHarness, cover: str) -> None:
    walk = shadow_fight
    rogue, ally = walk.players
    variant = "rogue_shadow_step_keldaran" if cover == "variant" else None
    if variant:
        await mentor_variant_progress.record_unlocked(rogue, variant, conn=walk.pool)
        await ability_persistence.set_active_variant(rogue, STEP, variant, conn=walk.pool)
    state = await walk.reload()
    assert state.architect_encounter is not None
    if cover == "smoke":
        combat_spatial.add_smoke(state, ally)
    elif cover == "chamber":
        architect_entomb.land(state, participant(state, "architect"), participant(state, ally), {"save_success": False})
    else:
        wall = state.architect_encounter["structure_ids"][0]
        start, end = (pos(28, 4), pos(48, 4)) if cover == "endpoint" else (pos(15, 4), pos(35, 4))
        combat_structures.move_wall(state, wall, start, end)
    await walk.persist()

    row = await discovered(walk, STEP)
    assert row["declaration"] == {"kind": "ability_move", "destination": "required {x,y,z} coordinates in feet"}
    assert row.get("active_variant_id") == variant
    instructions = walk.session.current_agent.instructions
    assert isinstance(instructions, str)
    assert 'ability_move — Shadow Step uses action="rogue_shadow_step" or its active variant id' in instructions
    before = await db_queries.get_player(rogue)
    assert before is not None and not concealment.is_concealed(before)
    await declare(
        walk, step(rogue, DESTINATION, action=row.get("active_variant_id", row["id"]), kind=row["declaration"]["kind"])
    )
    result = await walk.command("resolve_phase", {})
    assert result["next"]["waiting_on"] is None
    packets = result["packets"]
    stepped = receipt(packets, rogue)
    cost = {"stamina": 3, "focus": 1} if variant else {"stamina": 4, "focus": 0}
    assert stepped["resolved"] and stepped["declaration_type"] == "ability"
    assert stepped["destination"] == DESTINATION and stepped["moved_ft"] == stepped["movement_spent_ft"] == 25
    assert stepped["deducted"] == cost
    assert stepped["concealment"] == {"player_id": rogue, "before": False, "concealed": True}
    assert stepped.get("variant_id") == variant
    if variant:
        assert stepped["cultural_attribution"] == "Keldaran Holds technique"
    assert not strikes(packets)

    await reconnect(walk)
    state = await walk.reload()
    assert combat_spatial.position(combat_spatial.require_spatial(state), rogue) == DESTINATION
    assert not state.reactions_available["bandit"]["spent"]
    assert participant(state, rogue).hp_current == before["hp"]["current"]
    assert not strikes(await walk.drain())
    after = await db_queries.get_player(rogue)
    assert after is not None and concealment.is_concealed(after)
    for resource, amount in cost.items():
        assert after[resource]["current"] == before[resource]["current"] - amount
