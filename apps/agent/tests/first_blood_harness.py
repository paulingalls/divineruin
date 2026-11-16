"""Fixed basic-attack policy driven through real combat tools and persistence."""

import json
import random
from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

from sample_fixtures import make_context, make_mock_room

import combat_end
import db_mutations
from combat_death_save import request_death_save
from combat_down import is_terminally_down
from combat_turn import declare_phase, resolve_phase
from companion_profiles import get_companion_profile, select_companion_for_archetype
from condition_restrictions import cannot_act
from creation_rules import build_character_data
from declaration_payloads import AttackDecl, MultiattackDecl, StrikeSelection
from mode_tools import enter_mode

SEEDS = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19)
ARCHETYPES = ("warrior", "mage", "rogue", "cleric")
PATROL = "hollow_patrol_greyvale"


async def fight(pool, archetype, seed):
    pid = f"balance_{uuid4().hex}"
    row = build_character_data(
        "First Blood", "human", archetype, None, "", created_at=datetime(2026, 11, 1, tzinfo=UTC)
    )
    row["location_id"] = "greyvale_wilderness_north"
    await db_mutations.create_player(pid, None, row)
    companion = select_companion_for_archetype(archetype)
    ctx = make_context(pid, room=make_mock_room(), companion_id=companion)
    ctx.userdata.companion.name = get_companion_profile(companion).name
    ctx.userdata.location_id = row["location_id"]
    ending = []
    original = combat_end._end_combat_db

    async def capture(session, state, outcome, **kwargs):
        player = state.get_participant(pid)
        ending.append((outcome == "victory" and not is_terminally_down(player), player.hp_current > 0))
        return await original(session, state, outcome, **kwargs)

    previous_random = random.getstate()
    rng = random.Random(seed)
    random.seed(seed)
    try:
        with (
            patch("dice.random.SystemRandom", return_value=rng),
            patch("combat_end._end_combat_db", capture),
            patch("combat_wrap._end_combat_db", capture),
        ):
            await enter_mode(ctx, "combat", PATROL, "First Blood")
            for _ in range(100):
                state = ctx.userdata.combat_state
                assert state is not None
                enemies = [p for p in state.participants if p.type == "enemy" and not p.is_fallen]
                target = min(enemies, key=lambda p: p.hp_current) if enemies else None
                declarations = []
                for actor in state.participants:
                    if actor.is_fallen or cannot_act(actor.conditions):
                        continue
                    victim = pid if actor.type == "enemy" else target.id if target else None
                    if victim is None:
                        continue
                    if actor.type == "enemy" and actor.multiattack_sequence:
                        sequence = actor.multiattack_sequence
                        declarations.append(
                            MultiattackDecl(
                                kind="multiattack",
                                actor_id=actor.id,
                                action=sequence["name"],
                                strikes=[
                                    StrikeSelection(action=action, target_id=victim, held_item_id="")
                                    for action in sequence["attacks"]
                                ],
                            )
                        )
                    else:
                        declarations.append(
                            AttackDecl(
                                kind="attack",
                                actor_id=actor.id,
                                action=actor.action_pool[0]["name"],
                                target_id=victim,
                                held_item_id="",
                                rider="",
                            )
                        )
                assert declarations, "no acting combatants before terminal wrap"
                await declare_phase(ctx, declarations)
                for _ in range(64):
                    result = await resolve_phase(ctx)
                    if isinstance(result, tuple):
                        break
                    result = json.loads(result)
                    if result.get("next", {}).get("waiting_on") is None and result["beat"] == "declaration":
                        break
                else:
                    raise AssertionError("First Blood did not drain held actions within 64 calls")
                if isinstance(result, tuple):
                    assert len(ending) == 1
                    return ending[0]
                for actor_id in result["death_saves_due"]:
                    await request_death_save(ctx, actor_id)
            raise AssertionError("First Blood exceeded 100 rounds")
    finally:
        random.setstate(previous_random)
        if ctx.userdata.combat_state:
            await db_mutations.delete_combat_state(ctx.userdata.combat_state.combat_id)
        await pool.execute("DELETE FROM players WHERE player_id=$1", pid)


async def win_counts(pool):
    counts, standing = {}, {}
    for archetype in ARCHETYPES:
        results = [await fight(pool, archetype, seed) for seed in SEEDS]
        assert len(results) == 20
        counts[archetype] = sum(win for win, _ in results)
        standing[archetype] = sum(win and hp for win, hp in results)
    print(f"wins={counts}; HP>0 wins={standing}")
    return counts
