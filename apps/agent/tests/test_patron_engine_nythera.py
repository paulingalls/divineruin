import json
from unittest.mock import MagicMock, patch

import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import world as world
from acceptance._capstone_helpers import _d20
from test_unbound_alone_bonus import check


async def uncharted_senses_uses_map_history(world, archetype, skill, bonus):
    w = world
    await configure(w, "nythera", archetype)
    await w.pool.execute(
        "INSERT INTO player_map_progress (player_id, location_id, data) VALUES ($1,$2,$3::jsonb)",
        w.ids[0],
        w.ctx.userdata.location_id,
        json.dumps({"revisited": False}),
    )
    assert (await check(w, skill))["total"] == 11 + bonus
    await w.pool.execute(
        "UPDATE player_map_progress SET data='{" + '"revisited":true' + "}' WHERE player_id=$1",
        w.ids[0],
    )
    assert (await check(w, skill))["total"] == 11


async def uncharted_handling_adds_minor_bonus(world, archetype, bonus):
    from check_tools import _check_impl

    w = world
    await configure(w, "nythera", archetype)
    await w.pool.execute(
        "INSERT INTO player_map_progress (player_id, location_id, data) VALUES ($1,$2,'{}')",
        w.ids[0],
        w.ctx.userdata.location_id,
    )
    with patch("check_resolution.dice_roll", side_effect=[_d20(4), _d20(17)]) as dice:
        packet = json.loads(await _check_impl(w.ctx, "skill", skill="animal_handling", difficulty="moderate"))
    assert packet["roll"] == 4 and dice.call_count == 1
    assert packet["total"] == 4 + packet["modifier"]
    assert packet["modifier"] == bonus
    await w.pool.execute(
        "UPDATE player_map_progress SET data=$2::jsonb WHERE player_id=$1",
        w.ids[0],
        json.dumps({"revisited": True}),
    )
    with patch("check_resolution.dice_roll", return_value=_d20(4)):
        revisited = json.loads(await _check_impl(w.ctx, "skill", skill="animal_handling", difficulty="moderate"))
    assert revisited["roll"] == 4
    assert revisited["modifier"] == 0
    assert revisited["total"] == 4


async def test_guest_discovery_and_reroll_use_first_stay(world):
    from unittest.mock import AsyncMock

    import db_mutations_conditions
    import db_mutations_skill_advancement
    import db_queries
    from check_skill import _check_skill_run
    from check_tools import _check_impl
    from skill_check_effects import SkillCheckEffects

    w = world
    await configure(w, "nythera", "spy", index=1)
    await w.pool.execute(
        "INSERT INTO player_map_progress (player_id, location_id, data) VALUES ($1,$2,'{}')",
        w.ids[1],
        w.ctx.userdata.location_id,
    )
    with (
        w.ctx.userdata._bind_authenticated_actor(w.ids[1], 4, lambda *_: None),
        patch("check_resolution.dice_roll", return_value=_d20(11)),
    ):
        packet = json.loads(
            await _check_impl(
                w.ctx,
                "discover",
                skill="perception",
                content=MagicMock(
                    get_item=AsyncMock(return_value=None),
                    get_location=AsyncMock(return_value={"hidden_elements": []}),
                ),
            )
        )
        assert packet["total"] == 14
        async with w.db.transaction() as conn:
            player = await db_queries.get_player(w.ids[1], conn=conn, for_update=True)
            effects = SkillCheckEffects()
            packet = json.loads(
                await _check_skill_run(
                    w.ctx,
                    "investigation",
                    "moderate",
                    "reroll",
                    hearing_only=False,
                    queries=db_queries,
                    mutations=db_mutations_skill_advancement,
                    db_mod=w.db,
                    conditions_mutations=db_mutations_conditions,
                    effects=effects,
                    conn=conn,
                    locked_player=player,
                    reroll_dc=12,
                )
            )
        assert packet["total"] == 14 and effects.events[0][1]["total"] == 14


@pytest.mark.parametrize("first_stay,bonus", [(True, 3), (False, 0)])
async def test_choir_search_carries_uncharted_senses(first_stay, bonus, mock_combat_agent_factory):
    import combat_packet
    from combat_phase import ResolutionPacket
    from declarations import resolve_declaration
    from tests.combat.test_choir_encounter import start_choir

    ctx, _, mutations, queries = await start_choir()
    state = ctx.userdata.combat_state
    actor = state.get_participant("player_1")
    queries.get_player.return_value = {
        **queries.get_player.return_value,
        "class": "seeker",
        "divine_favor": {"patron": "nythera", "level": 40, "max": 100},
    }
    decl = resolve_declaration({"type": "interact", "action": "choir_search_perception", "target_id": "choir_sound"})
    with (
        patch("check_resolution.dice_roll", return_value=_d20(10)),
        patch("choir_encounter.check_first_stay", return_value=first_stay),
    ):
        packet = await combat_packet._resolve_one_packet(
            ctx.userdata,
            state,
            ResolutionPacket(actor_id=actor.id, declaration=decl, initiative=actor.initiative),
            mutations=mutations,
            queries=queries,
            resolver=None,
            concentration_break_mod=None,
        )
    assert packet["total"] == 13 + bonus
    assert (packet.get("gift_name") == "Uncharted Senses") is first_stay


SCENARIOS = {
    "nythera_uncharted_senses": (
        "patron_gifts:skill_gift",
        uncharted_senses_uses_map_history,
        [(a, s, 3) for a in ("seeker", "spy") for s in ("investigation", "perception")]
        + [("bard", "investigation", 0), ("seeker", "athletics", 0)],
    ),
    "nythera_uncharted_handling": (
        "patron_gifts:skill_gift",
        uncharted_handling_adds_minor_bonus,
        [("druid", 1), ("beastcaller", 1), ("bard", 0)],
    ),
}
