"""Seeded combat policies driven through real combat tools and persistence."""

import json
import random
from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

from sample_fixtures import make_context, make_mock_room

import character_spells
import combat_end
import db_mutations
import db_queries
import spell_knowledge
import spells
from combat_death_save import request_death_save
from combat_down import is_terminally_down
from combat_turn import declare_phase, resolve_phase
from companion_profiles import get_companion_profile, select_companion_for_archetype
from companion_scaling import scale_companion_stats_to_player_level
from condition_restrictions import cannot_act
from creation_rules import build_character_data
from declaration_payloads import AbilityDecl, AttackDecl, MultiattackDecl, StrikeSelection
from mode_tools import enter_mode
from progression_tools import _award_xp_core
from rules_engine import XP_FOR_LEVEL

SEEDS = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19)
ARCHETYPES = ("warrior", "mage", "rogue", "cleric")
PATROL = "hollow_patrol_greyvale"


async def fight(pool, archetype, seed, encounter_id=PATROL, player_level=1, *, policy="basic"):
    assert policy in ("basic", "caster", "veilrender"), policy
    pid = f"balance_{uuid4().hex}"
    row = build_character_data(
        "First Blood", "human", archetype, None, "", created_at=datetime(2026, 11, 1, tzinfo=UTC)
    )
    row["location_id"] = "ashmark_corrupted_front" if policy == "veilrender" else "greyvale_wilderness_north"
    await db_mutations.create_player(pid, None, row)
    if player_level > 1:
        async with pool.acquire() as conn, conn.transaction():
            await _award_xp_core(
                player_id=pid,
                player=row,
                amount=XP_FOR_LEVEL[player_level],
                reason="balance reference",
                conn=conn,
                pending_events=[],
            )
        row = await db_queries.get_player(pid)
        assert row is not None
        fresh = {name: {**row[name], "current": row[name]["max"]} for name in ("hp", "stamina", "focus") if name in row}
        await pool.execute("UPDATE players SET data=data || $2::jsonb WHERE player_id=$1", pid, json.dumps(fresh))
    cantrip = None
    if policy in ("caster", "veilrender") and archetype in ("mage", "cleric"):
        library = await character_spells.get_known(pid)
        known = spell_knowledge.castable_spell_ids(archetype, (s["spell_id"] for s in library))
        damage_cantrips = sorted(
            sid
            for sid in known
            if spells.get_spell(sid).spell_tier == "cantrip" and spells.get_spell(sid).combat_damage
        )
        if archetype == "mage":
            assert "arcane_bolt" in damage_cantrips, "mage has no learned arcane_bolt damage cantrip"
            cantrip = "arcane_bolt"
        elif damage_cantrips:
            cantrip = damage_cantrips[0]
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
            await enter_mode(ctx, "combat", encounter_id, "Balance reference")
            state = ctx.userdata.combat_state
            assert state is not None
            player = state.get_participant(pid)
            ally = state.get_participant(companion)
            assert player is not None and player.level == player_level
            expected = scale_companion_stats_to_player_level(
                get_companion_profile(companion), player.hp_max, player_level
            )
            assert ally is not None
            assert (ally.level, ally.hp_max, ally.hp_current, ally.ac, ally.attributes) == (
                expected.level,
                expected.hp,
                expected.hp,
                expected.ac,
                expected.attributes,
            )

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
                    if policy == "veilrender":
                        from veilrender_harness import declaration

                        opponent = state.get_participant(victim)
                        assert opponent is not None
                        declarations.append(declaration(state, actor, opponent, cantrip if actor.id == pid else None))
                    elif actor.id == pid and cantrip:
                        declarations.append(
                            AbilityDecl(
                                kind="ability", actor_id=pid, action=cantrip, targets=[victim], argument_type=""
                            )
                        )
                    elif actor.type == "enemy" and actor.multiattack_sequence:
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
                                reshape=[],
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


async def win_counts(pool, encounter_id=PATROL, player_level=1, *, policy="basic"):
    counts, standing = {}, {}
    for archetype in ARCHETYPES:
        results = [await fight(pool, archetype, seed, encounter_id, player_level, policy=policy) for seed in SEEDS]
        assert len(results) == 20
        counts[archetype] = sum(win for win, _ in results)
        standing[archetype] = sum(win and hp for win, hp in results)
    print(f"policy={policy}; encounter={encounter_id}; level={player_level}; wins={counts}; HP>0 wins={standing}")
    return counts, standing
