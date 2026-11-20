from types import SimpleNamespace
from unittest.mock import patch

import pytest
from _thyra_wrath_fixtures import GIFT, checkpoint, declare, fight, fighter, refuse, rolls, saved, snapshot
from _unbound_path_fixtures import row
from _unbound_path_fixtures import world as world
from sample_fixtures import published_payloads
from voice_condition_fixtures import participant

import combat_damage
import combat_fate
import combat_hold
import combat_phase
import event_types as E
from tool_support import SOUND_PLAYER_FALLEN


@pytest.mark.parametrize("field", ["ally_continuation", "held_actions"])
async def test_partly_resolved_round_refuses_wrath(world, field):
    foe = fighter("foe")
    async with fight(world, foe) as call:
        await declare(world, call)
        state = world.ctx.userdata.combat_state
        if field == "ally_continuation":
            resolving, advance = combat_phase.advance_combat_phase(state)
            allies, hostiles = combat_phase.partition_packets(resolving, advance.packets)
            state.ally_continuation = combat_fate.begin_ally_pass(resolving, allies, hostiles, {})
        else:
            state.held_actions = combat_hold.hold_enemy_packets(
                state, [SimpleNamespace(actor_id=foe.id, initiative=10)]
            )
        await checkpoint(world)
        assert getattr(state, field)
        await refuse(world, call, "partially resolved")


async def test_damage_batch_rolls_back_and_retries_after_first_landing(world):
    ordinary = fighter("raider", hp=5)
    async with fight(world, ordinary, fighter("survivor"), encounter="hollow_wisp", archetype="mage") as call:
        session = world.ctx.userdata
        state = session.combat_state
        hollow = participant(state, "hollow_wisp_1")
        hollow.hp_current = 5
        assert hollow.hollow is not None
        delta = hollow.hollow["resonance_on_death"]
        assert delta > 0
        await checkpoint(world)
        before = await snapshot(world)
        land = combat_damage.apply_attack_result

        async def fail_after_landing(*args, **kwargs):
            await land(*args, **kwargs)
            damaged = args[3]
            assert damaged.id == hollow.id and damaged.hollow_death_resolved
            assert (
                await kwargs["conn"].fetchval(
                    "SELECT (data->'resonance'->>'current')::int FROM players WHERE player_id=$1", world.ids[0]
                )
            ) == delta
            assert len(session.recent_events) == len(before["recent_events"]) + 1
            raise RuntimeError("injected after first Wrath landing")

        with patch.object(combat_damage, "apply_attack_result", side_effect=fail_after_landing), rolls() as dice:
            with pytest.raises(RuntimeError, match="injected after first Wrath landing"):
                await call("activate", id=GIFT)
            dice.assert_called_once_with("3d8")
        assert await snapshot(world) == before

        with rolls() as dice:
            result = await call("activate", id=GIFT)
        dice.assert_called_once_with("3d8")
        checkpointed = await saved(world)
        assert checkpointed.to_dict() == session.combat_state.to_dict()
        assert len(result["targets"]) == 3
        for original, dead, outcome in ((hollow, True, "dies"), (ordinary, False, "falls")):
            landed = participant(checkpointed, original.id)
            receipt = next(t for t in result["targets"] if t["id"] == original.id)
            assert (landed.hp_current, landed.is_fallen, landed.is_dead) == (0, True, dead)
            assert (receipt["damage"], receipt["target_fallen"], receipt["target_dead"]) == (15, True, dead)
            assert f"{original.name} takes 15 piercing and {outcome}" in result["dm_cue"]
        assert participant(checkpointed, hollow.id).hollow_death_resolved
        player = await row(world, 0)
        track = session.member_state(world.ids[0]).resonance
        assert track.current == player["resonance"]["current"] == delta
        assert player["patron_gifts"][GIFT] == {"spent": True}
        events = published_payloads(session.room)[len(before["client_events"]) :]
        assert sum(ev.get("sound_name") == SOUND_PLAYER_FALLEN for ev in events) == 2
        assert [(ev["caster_id"], ev["state"]) for ev in events if ev["type"] == E.RESONANCE_CHANGED] == [
            (world.ids[0], track.state),
        ]
