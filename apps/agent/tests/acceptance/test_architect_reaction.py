"""Reactive Architecture through persisted combat commands."""

import json
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from _zhael_fate_fixtures import attack, defend
from acceptance._capstone_helpers import _d20, _damage_die, _enemy
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_architect_fight import WORKS, enter, pos
from acceptance.test_architect_fight import isolated_content_cache as isolated_content_cache
from acceptance.test_architect_fight import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_architect_terrain import set_favor
from acceptance.test_still_anchors import fresh_session
from sample_fixtures import published_payloads
from voice_condition_fixtures import participant

import character_spells
import combat_round_checkpoint
import combat_spatial
import combat_structures
import db
import db_mutations
import db_queries
import event_types as E
import spells
from combat_structures import blocks_path
from db_mutations_resonance import read_player_resonance


@pytest.fixture
async def archers(reset_db_pool):
    harness = MawlingHarness()
    try:
        await harness.prepare((20, 20, 20), companion=None, location=WORKS)
        item = json.loads(await harness.pool.fetchval("SELECT data FROM items WHERE id='shortbow_common'"))
        for actor in harness.players:
            player = await db_queries.get_player(actor)
            assert player is not None
            player["equipment"]["main_hand"] = {
                "name": item["name"],
                "damage": item["damage_dice"],
                "damage_type": item["effects"][0]["damage_type"],
                "properties": [*item["properties"], item["subtype"]],
            }
            await harness.pool.execute(
                "UPDATE players SET data=$2::jsonb WHERE player_id=$1", actor, json.dumps(player)
            )
            await harness.pool.execute(
                "INSERT INTO player_inventory (player_id, item_id, data) VALUES ($1,'shortbow_common',$2::jsonb)",
                actor,
                json.dumps({"equipped": True, "current_hits": 25}),
            )
        state = await enter(harness)
        assert state.architect_encounter is not None
        owner_id = state.architect_encounter["owner_id"]
        participant(state, owner_id).ac = 23
        combat_spatial.place(state, owner_id, pos(-25, 25))
        for i, (actor, point) in enumerate(
            zip(harness.players, (pos(-45, 25), pos(-50, 25), pos(-25, 45)), strict=True)
        ):
            archer = participant(state, actor)
            archer.initiative = 30 - i
            archer.enhancers.clear()
            combat_spatial.place(state, actor, point)
        await harness.persist()
        yield harness
    finally:
        await harness.close()


def wall_raised(before, after, attacker):
    record = after.architect_encounter
    [wall_id] = set(record["structure_ids"]) - set(before.architect_encounter["structure_ids"])
    assert record["reaction_round"] == before.round_number
    wall = participant(after, wall_id)
    assert (wall.ac, wall.hp_max) == (19, 30)
    positions = before.spatial["positions"]
    if not wall.is_dead:
        assert blocks_path(positions[attacker], positions[record["owner_id"]], after.spatial["structures"][wall_id])
    return wall


@contextmanager
def forced_rolls(face=20, damage=4):
    with (
        patch("check_resolution.dice_roll", return_value=_d20(face)) as d20,
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(damage)) as damage_dice,
        patch("dice.roll", return_value=_damage_die(damage)),
    ):
        yield d20, damage_dice


async def declare(archers, *actions):
    state = await archers.reload()
    actors = {action["actor_id"] for action in actions}
    await archers.command(
        "declare_phase",
        {"declarations": [*actions, *(defend(p) for p in state.initiative_order if p not in actors)]},
    )


@pytest.mark.parametrize("case", ["hit", "miss", "extra_attack", "inclined"])
async def test_first_arrow_strikes_wall(archers, case):
    actor = archers.players[0]
    state = await archers.reload()
    owner = state.architect_encounter["owner_id"]
    if case == "extra_attack":
        state.get_participant(actor).enhancers.append("extra_attack")
    if case == "inclined":
        combat_spatial.place(state, actor, pos(-40, 22))
        combat_spatial.place(state, owner, pos(-25, 25, 20))
    before = await archers.persist()
    await declare(archers, bow(actor, owner))
    with forced_rolls(1 if case == "miss" else 15) as (rolled, _):
        [result] = [p for p in (await archers.command("resolve_phase", {}))["packets"] if p["actor_id"] == actor]
    after = await archers.reload()
    wall = wall_raised(before, after, actor)
    assert after.get_participant(owner).hp_current == before.get_participant(owner).hp_current
    assert result["reactive_architecture"]["wall_id"] == wall.id
    assert result["target_id"] == wall.id and result["target_ac"] == 19
    assert 30 - wall.hp_current == result["damage"]
    assert result["hit"] is (case != "miss")
    if result["hit"]:
        assert 19 <= result["attack_total"] < 23
    assert rolled.call_count == 1
    if case == "extra_attack":
        first, second = result["attacks"]
        assert first["target_id"] == wall.id
        assert not second["resolved"] and wall.id in second["reason"] and "damage" not in second


async def test_later_shots_and_next_round(archers):
    first, crossing, clear = archers.players
    state = await archers.reload()
    encounter = state.architect_encounter
    owner = encounter["owner_id"]
    prior_wall = f"{owner}_reaction_wall_1"
    combat_structures.add_wall(state, prior_wall, "Architect's reaction wall", pos(0, 50), pos(10, 50))
    encounter["structure_ids"].append(prior_wall)
    encounter["reaction_round"] = 1
    state.round_number = 2
    async with db.transaction() as conn:
        # Round 2 starts here, so it takes the round-start checkpoint a real wrap would.
        await combat_round_checkpoint.capture(archers.sd, state, conn=conn, mutations=db_mutations)
    before = await archers.persist()
    await declare(archers, *(bow(actor, owner) for actor in archers.players))
    with forced_rolls() as (rolled, _):
        results = {p["actor_id"]: p for p in await archers.drain()}
    after = await archers.reload()
    wall = wall_raised(before, after, first)
    assert results[first]["target_id"] == wall.id
    assert not results[crossing]["resolved"] and wall.id in results[crossing]["reason"]
    assert results[clear]["target_ac"] == 25 and results[clear]["damage"] > 0
    assert after.get_participant(owner).hp_current < before.get_participant(owner).hp_current
    assert rolled.call_count == 2

    await declare(archers, bow(clear, owner))
    with forced_rolls():
        results = {p["actor_id"]: p for p in await archers.drain()}
    reloaded = await archers.reload()
    next_wall = wall_raised(after, reloaded, clear)
    assert next_wall.id != wall.id and results[clear]["target_id"] == next_wall.id
    assert reloaded.get_participant(owner).hp_current == after.get_participant(owner).hp_current
    for wrapped, expired in ((after, participant(after, prior_wall)), (after, wall), (reloaded, next_wall)):
        assert expired.id not in wrapped.spatial["structures"]
        assert expired.hp_current == 0 and expired.is_dead and expired.is_fallen
    assert set(before.spatial["structures"]) - {prior_wall} <= reloaded.spatial["structures"].keys()
    facts = await archers.command("query_info", {"kind": "combat"})
    hud = [event for event in published_payloads(archers.sd.room) if event["type"] == E.COMBAT_UI_UPDATE][-1]
    tracked = {entry["id"] for entry in hud["combatants"]}
    assert set(reloaded.spatial["structures"]) <= tracked
    for expired in (prior_wall, wall.id, next_wall.id):
        assert all(expired not in facts[field] for field in ("positions", "distances_ft", "speeds_ft"))
        assert all(expired not in line for line in facts["spoken"])
        assert expired not in tracked


def bow(actor, target):
    return {**attack(actor, target), "action": "Shortbow"}


@pytest.mark.parametrize("case", ["other", "melee"])
async def test_other_attacks_do_not_spend_reaction(archers, case):
    actor, _, _ = archers.players
    state = await archers.reload()
    owner = state.architect_encounter["owner_id"]
    if case == "other":
        target = state.architect_encounter["structure_ids"][0]
        combat_spatial.place(state, actor, pos(25, 30))
        action = "Shortbow"
    else:
        target = owner
        combat_spatial.place(state, actor, pos(-28, 25))
        give_melee(state, actor)
        action = "Longsword"
    before = await archers.persist()
    await declare(archers, {**attack(actor, target), "action": action})
    with forced_rolls():
        [result] = [p for p in await archers.drain() if p["actor_id"] == actor]
    after = await archers.reload()
    assert result["damage"] > 0 and "reactive_architecture" not in result
    assert after.get_participant(target).hp_current < before.get_participant(target).hp_current
    assert after.architect_encounter == before.architect_encounter


def give_melee(state, actor):
    participant(state, actor).action_pool.append({"name": "Longsword", "damage": "1d8", "damage_type": "slashing"})


async def teach(archers, spell_id):
    actor = archers.players[0]
    spell = spells.get_spell(spell_id)
    cls = {"divine": "cleric", "arcane": "mage"}[spell.source]
    await archers.pool.execute(
        "UPDATE players SET data=jsonb_set(data, '{class}', to_jsonb($2::text)) WHERE player_id=$1", actor, cls
    )
    await character_spells.record_learned(actor, spell_id, "discovery")
    return spell


def cast(actor, spell_id, target, argument=""):
    return {"kind": "ability", "actor_id": actor, "action": spell_id, "targets": [target], "argument_type": argument}


async def caster_pools(actor):
    player = await db_queries.get_player(actor)
    assert player is not None
    return player["focus"]["current"], (await read_player_resonance(actor))["current"]


def assert_cost(before, after, spell):
    # The caster is inside the Architect's aura, which adds one Resonance to a Focus-spending cast.
    generated = spell.resonance_by_source[spell.source] + int(spell.focus_cost > 0)
    assert after == (before[0] - spell.focus_cost, before[1] + generated)


@pytest.mark.parametrize("spell_id", ["arcane_bolt", "arcane_frost_touch"])
async def test_direct_spell_attack_strikes_wall(archers, spell_id):
    actor = archers.players[0]
    spell = await teach(archers, spell_id)
    pools = await caster_pools(actor)
    before = await archers.reload()
    owner = before.architect_encounter["owner_id"]
    await declare(archers, cast(actor, spell_id, owner))
    with forced_rolls(17) as (rolled, _):
        [result] = [p for p in (await archers.command("resolve_phase", {}))["packets"] if p["actor_id"] == actor]
    after = await archers.reload()
    wall = wall_raised(before, after, actor)
    [damage] = result["cast"]["damage_results"]
    assert result["reactive_architecture"]["wall_id"] == wall.id
    assert 19 <= damage["attack_total"] < 23
    assert damage["target_id"] == wall.id and damage["target_ac"] == 19
    assert 30 - wall.hp_current == damage["damage"] > 0
    assert after.get_participant(owner).hp_current == before.get_participant(owner).hp_current
    assert rolled.call_count == 1
    assert_cost(pools, await caster_pools(actor), spell)


async def use_area_attack(archers, monkeypatch, spell_id):
    row = json.loads(await archers.pool.fetchval("SELECT data FROM spells WHERE id=$1", spell_id))
    profile = row["combat_damage"]
    del profile["save"], profile["half"]
    profile.update(resolution="attack", ranged=True)
    monkeypatch.setitem(spells._spells, spell_id, spells.parse_spell_row(spell_id, row))


@pytest.mark.parametrize("attack_profile", [True, False], ids=["attack", "save"])
async def test_area_spell_keeps_other_recipients(archers, attack_profile, monkeypatch):
    actor, ally, outside = archers.players
    spell_id = "arcane_elemental_burst"
    if attack_profile:
        await use_area_attack(archers, monkeypatch, spell_id)
    spell = await teach(archers, spell_id)
    pools = await caster_pools(actor)
    state = await archers.reload()
    owner = state.architect_encounter["owner_id"]
    foe = "other_foe"
    state.participants.append(_enemy(foe, 100))
    state.initiative_order.append(foe)
    state.spatial["positions"][foe] = pos(-22, 27)
    state.spatial["speeds"][foe] = 30
    combat_spatial.place(state, ally, pos(-23, 26))
    before = await archers.persist()

    await declare(archers, cast(actor, spell_id, owner, "cold"))
    with forced_rolls(20 if attack_profile else 1):
        resolved = await archers.command("resolve_phase", {})
    [result] = [p for p in resolved["packets"] if p["actor_id"] == actor]
    after = await archers.reload()
    wall = wall_raised(before, after, actor)
    damage = result["cast"]["damage_results"]
    recipients = {p["target_id"]: p for p in damage}
    assert len(damage) == len(recipients)
    assert set(recipients) == ({foe, ally, wall.id} if attack_profile else {foe, ally})
    assert after.get_participant(owner).hp_current == before.get_participant(owner).hp_current
    assert after.get_participant(outside).hp_current == before.get_participant(outside).hp_current
    for other in (ally, foe):
        assert (
            before.get_participant(other).hp_current - after.get_participant(other).hp_current
            == recipients[other]["damage"]
            > 0
        )
    assert result["reactive_architecture"]["wall_id"] == wall.id
    if attack_profile:
        assert recipients[wall.id]["target_ac"] == 19
        assert 30 - wall.hp_current == recipients[wall.id]["damage"] > 0
    else:
        assert all("save" in other for other in damage)
        assert wall.hp_current == 30
    assert_cost(pools, await caster_pools(actor), spell)


@pytest.mark.parametrize("case", ["save", "automatic", "condition", "condition_clear"])
async def test_spell_without_attack_roll_is_blocked(archers, case, monkeypatch):
    spell_id = {"save": "divine_sacred_flame", "automatic": "arcane_magic_missile"}.get(case, "arcane_hold_person")
    if case.startswith("condition"):
        row = json.loads(await archers.pool.fetchval("SELECT data FROM spells WHERE id=$1", spell_id))
        monkeypatch.setitem(
            spells._spells, spell_id, spells.parse_spell_row(spell_id, {**row, "applies_condition": "restrained"})
        )
    spell = await teach(archers, spell_id)
    actor = archers.players[0]
    pools = await caster_pools(actor)
    state = await archers.reload()
    owner = state.architect_encounter["owner_id"]
    if case == "condition_clear":
        state.architect_encounter["reaction_round"] = state.round_number
    before = await archers.persist()

    await declare(archers, cast(actor, spell_id, owner))
    with forced_rolls(1) as (rolled, _):
        resolved = await archers.command("resolve_phase", {})
    [result] = [p for p in resolved["packets"] if p["actor_id"] == actor]
    after = await archers.reload()
    assert after.get_participant(owner).hp_current == before.get_participant(owner).hp_current
    assert after.get_participant(actor).conditions == before.get_participant(actor).conditions
    assert rolled.call_count == 0
    assert_cost(pools, await caster_pools(actor), spell)
    packet = result["cast"]
    if case == "condition_clear":
        assert packet["condition_targets"] == [owner] and packet["condition_applied"] == "restrained"
        assert after.architect_encounter == before.architect_encounter
        return
    wall = wall_raised(before, after, actor)
    assert wall.hp_current == 30
    assert not packet.get("damage_results") and "condition_applied" not in packet and "damage_result" not in packet
    assert after.get_participant(owner).conditions == before.get_participant(owner).conditions
    interception = result["reactive_architecture"]
    assert (interception["target_id"], interception["wall_id"], interception["redirected"]) == (owner, wall.id, False)
    assert packet["narration_cue"] == packet["effect"] == interception["cue"]


@pytest.mark.parametrize("case", ["arrow_reload", "arrow_miss", "spell_reload", "area_reload"])
async def test_held_wall_strike_resumes_once(archers, case, monkeypatch):
    actor = archers.players[0]
    before = await archers.reload()
    owner = before.architect_encounter["owner_id"]
    spell_id = {"spell_reload": "arcane_disintegrate", "area_reload": "arcane_elemental_burst"}.get(case)
    if case == "area_reload":
        await use_area_attack(archers, monkeypatch, spell_id)
    spell = await teach(archers, spell_id) if spell_id else None
    pools = await caster_pools(actor)
    await set_favor(archers, "zhael", 40)
    if spell is None:
        await declare(archers, bow(actor, owner))
    else:
        await declare(archers, cast(actor, spell.id, owner, "cold" if case == "area_reload" else ""))
    miss = case == "arrow_miss"
    face = 1 if miss else 16
    with forced_rolls(face, 40 if spell else 4) as (rolled, damage_dice):
        held = await archers.command("resolve_phase", {})
        assert held["fate_offer"]["die"] == face
        saved = await archers.reload()
        wall = wall_raised(before, saved, actor)
        segment = saved.spatial["structures"][wall.id]
        assert wall.hp_current == 30 and rolled.call_count == 1 and damage_dice.call_count == 0
        assert saved.get_participant(owner).hp_current == before.get_participant(owner).hp_current
        [pending] = [p for p in held["packets"] if p["actor_id"] == actor]
        assert pending["reactive_architecture"]["wall_id"] == wall.id and not pending["resolved"]
        cursor = saved.ally_continuation
        if spell is None:
            assert cursor["attack"]["target_id"] == owner
            assert cursor["attack"]["reactive_architecture"]["wall_id"] == wall.id
        else:
            landing = cursor["steps"]["landing"]
            assert (landing["target_ids"] or [landing["target_id"]]) == [wall.id]
            assert_cost(pools, await caster_pools(actor), spell)

        if miss:
            resumed = await archers.command(
                "activate", {"id": "zhael_fates_thread", "offer_id": held["fate_offer"]["offer_id"], "keep": "original"}
            )
        else:
            await fresh_session(archers, saved)
            assert (await archers.reload()).spatial["structures"][wall.id] == segment
            resumed = await archers.command("resolve_phase", {})
        [result] = [p for p in resumed["packets"] if p["actor_id"] == actor]
        blow = result if spell is None else result["cast"]["damage_result"]
        assert result["reactive_architecture"]["wall_id"] == wall.id
        assert blow["target_id"] == wall.id and blow["target_ac"] == 19 and blow["roll"] == face
        assert rolled.call_count == 1 and blow["hit"] is not miss
        assert damage_dice.call_count == int(not miss)
        after = await archers.reload()
        assert after.architect_encounter == saved.architect_encounter
        assert after.get_participant(owner).hp_current == before.get_participant(owner).hp_current
        assert after.get_participant(wall.id).hp_current == max(0, 30 - blow["damage"])
        if spell is not None:
            assert after.get_participant(wall.id).is_dead
            assert_cost(pools, await caster_pools(actor), spell)
        followup = await archers.command("resolve_phase", {})
        assert not any("reactive_architecture" in p for p in followup["packets"])
        assert rolled.call_count == 1 and damage_dice.call_count == int(not miss)


async def test_destroyed_architect_cannot_intercept_a_later_cast(archers):
    caster, striker, _ = archers.players
    await teach(archers, "arcane_bolt")
    state = await archers.reload()
    owner = state.architect_encounter["owner_id"]
    participant(state, owner).hp_current = 1
    participant(state, striker).initiative = 40
    give_melee(state, striker)
    combat_spatial.place(state, striker, pos(-28, 25))
    before = await archers.persist()
    await declare(archers, attack(striker, owner), cast(caster, "arcane_bolt", owner))
    with forced_rolls() as (rolled, _):
        resolved = await archers.command("resolve_phase", {})
    after = await archers.reload()
    assert after.get_participant(owner).is_dead and rolled.call_count == 1
    assert after.architect_encounter == {**before.architect_encounter, "phase": "destroyed"}
    [result] = [packet for packet in resolved["packets"] if packet["actor_id"] == caster]
    assert "reactive_architecture" not in result and not result["cast"]["damage_result"]["resolved"]


async def test_extra_attack_can_reach_architect_after_wall_collapses(archers):
    actor = archers.players[0]
    state = await archers.reload()
    owner = state.architect_encounter["owner_id"]
    participant(state, actor).enhancers.append("extra_attack")
    before = await archers.persist()
    await declare(archers, bow(actor, owner))
    with forced_rolls(face=19, damage=40):
        [result] = [packet for packet in await archers.drain() if packet["actor_id"] == actor]
    after = await archers.reload()
    wall = wall_raised(before, after, actor)
    first, second = result["attacks"]
    assert wall.is_dead and first["target_id"] == wall.id
    assert second["target"] == participant(before, owner).name and second["target_ac"] == 25
    assert participant(before, owner).hp_current - participant(after, owner).hp_current == second["damage"] > 0
    assert (result["target"], result["target_hp_status"], result["damage"]) == (
        first["target"],
        first["target_hp_status"],
        first["damage"],
    )
