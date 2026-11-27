"""Catalog damage riders through declarations, settlement and persisted combat."""

import json
from copy import deepcopy
from dataclasses import replace
from unittest.mock import patch

import pytest
from acceptance._enemy_opportunity_helpers import declare, move, resolve_allies, strikes
from acceptance._enemy_opportunity_helpers import fight as fight
from acceptance._spell_hostile_condition_helpers import attack, cast_spell, defend, play, receipt, reload, set_foe
from acceptance._spell_hostile_condition_helpers import dev_db_pool as dev_db_pool
from acceptance.test_architect_fight import isolated_content_cache as isolated_content_cache
from acceptance.test_architect_fight import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_architect_fight import pos
from acceptance.test_architect_reaction import archers as archers
from acceptance.test_architect_reaction import bow, cast, forced_rolls, teach
from acceptance.test_architect_reaction import declare as declare_archers
from combat.test_spell_damage_lands import minimum_roll, prepare_spell, saved_player
from combat.test_spell_damage_lands import spell_fight as spell_fight
from creature_combat_helpers import participant as catalog_participant
from voice_condition_fixtures import participant, place_actors, spatial_record

import character_spells
import choir_encounter
import combat_spatial
import combat_turn
import db
import db_mutations
import spells
from combat_state import CombatState
from creature_catalog import query_creature_by_id
from creature_combat import translate_creature
from declaration_payloads import MoveDecl

JUDGMENT = "divine_divine_judgment"
FROST = "arcane_frost_touch"
SPARK = "arcane_spark"
RIDERS = [(JUDGMENT, "stunned", 1), (FROST, "frost_slowed", 15), (SPARK, "reactions_suppressed", 15)]


async def rider_foe(ctx, creature="hollow_mawling", *, hp=100, foe_id="foe"):
    state = ctx.userdata.combat_state
    row = await query_creature_by_id(creature)
    derived = translate_creature(
        row, encounter_id=state.encounter_id or "spell_riders", enemy_id=foe_id, role="standard"
    )
    foe = catalog_participant(derived)
    foe.hp_current = foe.hp_max = hp
    if foe_id not in state.initiative_order:
        state.initiative_order.append(foe_id)
    state.participants = [actor for actor in state.participants if actor.id != foe_id] + [foe]
    place_actors(state)
    if creature == "hollow_choir" and state.encounter_id:
        choir_encounter.initialize(state)
    await db_mutations.save_combat_state(state.combat_id, state.to_dict())
    return foe


async def resolve_step(ctx) -> dict:
    raw = await combat_turn._resolve_phase_impl(ctx)
    assert isinstance(raw, str)
    return json.loads(raw)


async def settle_cast(ctx, spell, face, *, target="foe", extra=()):
    caster = ctx.userdata.player_id
    await combat_turn.declare_phase(ctx, [cast_spell(caster, spell, target), *extra])
    with forced_rolls(face), patch("dice.roll", side_effect=minimum_roll):
        response = await resolve_step(ctx)
    result = receipt(response["packets"], caster)
    return result["damage_result"], await reload(ctx)


@pytest.mark.parametrize("spell_id,condition,face", RIDERS)
async def test_rider_is_the_only_cast_difference_after_reload(spell_fight, spell_id, condition, face):
    ctx = spell_fight
    spell = await prepare_spell(ctx, spell_id)
    await rider_foe(ctx)
    caster = ctx.userdata.player_id
    baseline = ctx.userdata.combat_state.to_dict()
    pool = await db.get_pool()
    player_row = await pool.fetchval("SELECT data FROM players WHERE player_id=$1", caster)
    resonance = deepcopy(ctx.userdata.resonance)

    landed, state = await settle_cast(ctx, spell_id, face)
    assert landed["condition_inflicted"] == condition
    [instance] = participant(state, "foe").conditions
    assert instance["type"] == condition and instance["source"] == spell_id
    assert instance["duration"] == (None if spell_id == SPARK else 1)
    if spell_id == SPARK:
        assert instance["originating_participant_id"] == caster
    assert landed["target_id"] == "foe" and landed["condition_source"] == spell_id
    assert landed["condition_expires"] == ("caster_turn_start" if spell_id == SPARK else "target_turn_end")
    if spell_id == JUDGMENT:
        assert landed["damage_components"] == [{"dice": "8d8", "damage_type": "radiant", "damage": 16}]
        assert 100 - participant(state, "foe").hp_current == landed["damage"] == 16
    paid = await saved_player(caster)
    post_cast = state.to_dict()

    await pool.execute("UPDATE players SET data=$2::jsonb WHERE player_id=$1", caster, player_row)
    await db_mutations.save_combat_state(state.combat_id, baseline)
    ctx.userdata.combat_state = CombatState.from_dict(baseline)
    ctx.userdata.resonance = resonance
    profile = spell.combat_damage
    assert profile is not None
    with patch.dict(
        spells._spells, {spell_id: replace(spell, combat_damage={k: v for k, v in profile.items() if k != "rider"})}
    ):
        control, reloaded = await settle_cast(ctx, spell_id, face)
    assert control == {
        k: v for k, v in landed.items() if k not in {"condition_inflicted", "condition_expires", "condition_source"}
    }
    assert participant(reloaded, "foe").conditions == []
    assert participant(reloaded, "foe").hp_current == participant(state, "foe").hp_current
    for actor in post_cast["participants"]:
        if actor["id"] == "foe":
            actor["conditions"] = []
    assert reloaded.to_dict() == post_cast
    control_player = await saved_player(caster)
    assert (paid["focus"], paid.get("resonance")) == (control_player["focus"], control_player.get("resonance"))


@pytest.mark.parametrize("save_face", [1, 20])
async def test_judgment_stun_covers_one_enemy_turn(spell_fight, save_face):
    ctx = spell_fight
    await prepare_spell(ctx, JUDGMENT)
    caster = ctx.userdata.player_id
    await rider_foe(ctx)
    claw = attack("foe", "Claw", caster)
    with patch("dice.roll", side_effect=minimum_roll):
        packets, after = await play(
            ctx, cast_spell(caster, JUDGMENT), claw, faces=[save_face, 16] if save_face == 20 else None
        )
    damage = receipt(packets, caster)["damage_result"]
    succeeded = save_face == 20
    assert damage["save"]["success"] is succeeded
    assert damage["damage_components"][0]["dice"] == "8d8"
    assert damage["damage"] == (8 if succeeded else 16)
    assert not participant(after, "foe").conditions
    foe_packet = next(p for p in packets if p["actor_id"] == "foe")
    if succeeded:
        assert foe_packet["hit"] and "condition_inflicted" not in damage
    else:
        assert "stunned" in foe_packet["reason"]
    packets, _ = await play(ctx, defend(caster), claw, face=16)
    assert next(p for p in packets if p["actor_id"] == "foe")["hit"]


@pytest.mark.parametrize(("face", "distance", "moved"), [(15, 20, True), (15, 25, False), (1, 30, True)])
async def test_frost_touch_changes_live_movement_for_one_turn(spell_fight, face, distance, moved):
    ctx = spell_fight
    await set_foe(ctx)
    ctx.userdata.combat_state.terrain = "plains"
    caster = ctx.userdata.player_id
    first_move = MoveDecl(**move("foe", distance))
    packets, after = await play(ctx, cast_spell(caster, FROST), first_move, face=face)
    damage = receipt(packets, caster)["damage_result"]
    assert (damage.get("condition_inflicted") == "frost_slowed") is (face != 1)
    packet = next(p for p in packets if p["actor_id"] == "foe")
    if moved:
        assert packet["moved_ft"] == distance
    else:
        assert "exceeds speed 20 feet" in packet.get("reason", ""), packet
    x = distance if moved else 0
    assert spatial_record(after)["positions"]["foe"] == pos(x)
    packets, after = await play(ctx, defend(caster), MoveDecl(**move("foe", x + 30)))
    assert next(p for p in packets if p["actor_id"] == "foe")["moved_ft"] == 30
    assert spatial_record(after)["positions"]["foe"] == pos(x + 30)


@pytest.mark.parametrize("fight", [{"bandit": "hollow_mawling"}], indirect=True)
async def test_spark_blocks_mawling_until_casters_own_departure(fight):
    mover, caster = fight.players
    await fight.pool.execute(
        "UPDATE players SET data=jsonb_set(data,'{class}',to_jsonb('mage'::text)) WHERE player_id=$1", caster
    )
    await character_spells.record_learned(caster, SPARK, "discovery")
    state = await fight.reload()
    participant(state, mover).initiative = 20
    participant(state, caster).initiative = 15
    combat_spatial.place(state, caster, pos(3))
    await fight.persist()
    await declare(fight, cast(caster, SPARK, "bandit"))
    with forced_rolls(18):
        packets = await fight.drain()
    assert receipt(packets, caster)["damage_result"]["hit"]
    before = await fight.reload()
    await declare(fight, move(mover, 20), move(caster, 20))
    with forced_rolls(18):
        packets = await resolve_allies(fight)
    assert [strike["target_id"] for strike in strikes(packets)] == [caster]
    after = await fight.reload()
    assert participant(after, mover).hp_current == participant(before, mover).hp_current
    assert participant(after, caster).hp_current < participant(before, caster).hp_current
    assert not participant(after, "bandit").conditions
    assert participant(before, "bandit").conditions[0]["type"] == "reactions_suppressed"


async def test_spark_suppresses_reactive_architecture_until_caster_starts(archers):
    caster, early, late = archers.players
    await teach(archers, SPARK)
    state = await archers.reload()
    owner = state.architect_encounter["owner_id"]
    for actor, initiative, position in (
        (early, 20, pos(-45, 25)),
        (caster, 15, pos(-25, 45)),
        (late, 10, pos(-50, 25)),
    ):
        participant(state, actor).initiative = initiative
        combat_spatial.place(state, actor, position)
    await archers.persist()
    await declare_archers(archers, bow(early, owner), cast(caster, SPARK, owner))
    with forced_rolls():
        packets = await archers.drain()
    pre = next(p for p in packets if p["actor_id"] == early)
    assert pre["target_id"] == pre["reactive_architecture"]["wall_id"]
    assert receipt(packets, caster)["damage_result"]["damage"] > 0
    before = await archers.reload()

    await declare_archers(archers, bow(early, owner), bow(late, owner))
    with forced_rolls():
        result = await archers.command("resolve_phase", {})
    packets = {p["actor_id"]: p for p in result["packets"]}
    assert packets[early]["target"] == participant(before, owner).name
    assert "reactive_architecture" not in packets[early]
    wall = packets[late]["reactive_architecture"]["wall_id"]
    assert packets[late]["target_id"] == wall
    after = await archers.reload()
    assert after.architect_encounter["reaction_round"] == before.round_number
    assert 30 - participant(after, wall).hp_current == packets[late]["damage"] > 0
    assert participant(before, owner).hp_current - participant(after, owner).hp_current == packets[early]["damage"]
