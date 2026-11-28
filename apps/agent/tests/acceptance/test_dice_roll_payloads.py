from unittest.mock import patch

from acceptance._capstone_helpers import _build_state, _d20, _enemy, _resolve_round
from acceptance._catalog_cutover_helpers import started as started
from acceptance.seeds import seed_player_with_pools
from sample_fixtures import make_context, make_mock_room, published_payloads

import choir_encounter
import combat_turn
import db
import db_mutations


async def test_choir_turn_start_publishes_the_aura_save(started) -> None:
    ctx, _ = await started("hollow_choir", player_class="cleric")
    session = ctx.userdata
    await combat_turn._declare_phase_impl(ctx, {p.id: {"type": "defend"} for p in session.combat_state.participants})
    saves = []
    packet_save = choir_encounter.packet_save

    async def capture_save(*args, **kwargs):
        result = await packet_save(*args, **kwargs)
        if args[2] == session.player_id:
            saves.append(result)
        return result

    with (
        patch.object(choir_encounter, "packet_save", side_effect=capture_save),
        patch("check_resolution.dice_roll", return_value=_d20(14)),
    ):
        await _resolve_round(ctx)

    [save] = saves
    assert save.roll == 14 and save.modifier != 0
    [packet] = [e for e in published_payloads(session.room) if e.get("roll_type") == "choir_aura"]
    assert packet == {
        "type": "dice_roll",
        "roll_type": "choir_aura",
        "actor_id": session.player_id,
        "save_type": "wisdom",
        "dc": 15,
        "roll": save.roll,
        "modifier": save.modifier,
        "total": save.total,
        "success": save.success,
        "concentration_broken": None,
        "cue": "Lost voices tug at your focus.",
        **save.oath_fields(),
    }


async def test_failed_argument_publishes_the_check_and_round(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    pid = "dice_payload_diplomat"
    await seed_player_with_pools(pool, player_id=pid, class_="diplomat", focus_current=3)
    await pool.execute(
        "UPDATE players SET data = jsonb_set(data, '{attributes,charisma}', '20') WHERE player_id = $1", pid
    )
    foe = _enemy("dice_payload_foe", hp=10)
    state = _build_state("combat_dice_payloads", pid, [foe])
    player = state.get_participant(pid)
    assert player is not None
    ctx = make_context(pid, room=make_mock_room())
    await db_mutations.save_combat_state(state.combat_id, state.to_dict(), conn=pool)
    ctx.userdata.combat_state = state
    try:
        await combat_turn._declare_phase_impl(
            ctx,
            {
                pid: {"type": "ability", "action": "de_escalate", "argument_type": "threat", "target_id": foe.id},
                foe.id: {"type": "defend"},
            },
        )
        with patch("check_resolution.dice_roll", return_value=_d20(3)):
            await _resolve_round(ctx)

        [packet] = [e for e in published_payloads(ctx.userdata.room) if e.get("roll_type") == "de_escalate"]
        assert packet == {
            "type": "dice_roll",
            "roll_type": "de_escalate",
            "skill": "persuasion",
            "roll": 3,
            "modifier": 6,
            "total": 9,
            "success": False,
            "actor": player.name,
            "round": 1,
            "surrendered": 0,
            "living": 1,
            "ends_combat": False,
            "dramatic": True,
            "context": "de_escalate",
        }
    finally:
        await db_mutations.delete_combat_state(state.combat_id, conn=pool)
        await pool.execute("DELETE FROM players WHERE player_id = $1", pid)
