"""Renewing Spark through registered spell and reaction settlement."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _damage_die
from acceptance._spell_hostile_condition_helpers import HOLD, add_player, cast_spell, play, receipt, set_foe
from acceptance._spell_hostile_condition_helpers import dev_db_pool as dev_db_pool
from acceptance.defensive_reactions_harness import (
    SHIELD,
    action_packet,
    declare_attacks,
    defense_fight,
    player_row,
    reaction_packet,
    spend,
)
from acceptance.test_guardian_intercept import SWORD, tool_receipt
from acceptance.test_marshal_rally import set_favor
from acceptance.test_spell_new_conditions import FIRE
from acceptance.test_still_anchors import declare, strike
from combat.test_spell_damage_lands import spell_fight as spell_fight
from livekit.agents import ToolError
from voice_condition_fixtures import participant, place_actors, spatial_record

import db
import db_mutations
import event_types as E
import temp_hp
from activate_tools import activate
from check_resolution import D20Roll
from combat_agent import create_combat_agent
from patron_passives import effective_hp
from session_data import CombatParticipant, CompanionState

CLAUSE = "orenthel_mage_warding"
FLY = "arcane_fly"
HASTE = "arcane_haste"
INVISIBILITY = "arcane_invisibility"
BOLT = "arcane_bolt"
MAGE_LIGHT = "arcane_mage_light"
LIBRARY_SHIELD = "arcane_shield_spell"


def ward(receipt: dict, recipient_id: str, before: int) -> None:
    assert receipt["mage_warding"] == {
        "id": CLAUSE,
        "name": "Renewing Spark",
        "recipients": [{"recipient_id": recipient_id, "granted": int(before == 0), "temp_hp": max(before, 1)}],
    }


async def update_player(pid: str, **changes: object) -> None:
    await (await db.get_pool()).execute(
        "UPDATE players SET data=data || $2::jsonb WHERE player_id=$1", pid, json.dumps(changes)
    )


async def check_pools(expected: dict[str, int], state=None) -> None:
    for pid, pool in expected.items():
        assert temp_hp.from_player(await player_row(pid)) == pool, pid
        if state is not None:
            assert participant(state, pid).temp_hp == pool, pid


@pytest.fixture
async def mage_party(spell_fight):
    ctx = spell_fight
    mage = ctx.userdata.player_id
    ally = await add_player(ctx, "mage")
    control = await add_player(ctx, "mage")
    await update_player(mage, divine_favor={"patron": "orenthel", "level": 40, "max": 100})
    await set_foe(ctx)
    return ctx, mage, ally, control


@pytest.mark.parametrize(
    ("spell", "combat", "before"),
    [(spell, combat, 0) for spell in (FLY, HASTE, INVISIBILITY) for combat in (False, True)]
    + [(HASTE, True, 1), (FLY, True, 5)],
)
async def test_wards_the_applied_ally(mage_party, spell, combat, before):
    ctx, mage, ally, control = mage_party
    if combat:
        state = ctx.userdata.combat_state
        await update_player(ally, temp_hp=before)
        participant(state, ally).temp_hp = before
        await db_mutations.save_combat_state(state.combat_id, state.to_dict())
        packets, state = await play(ctx, cast_spell(mage, spell, ally))
        cast = receipt(packets, mage)
    else:
        ctx.userdata.combat_state = None
        await update_player(ally, maxhp_override=-3)
        cast = json.loads(await activate(ctx, spell, target_id=ally))
        events = ctx.userdata.room.local_participant.publish_data.call_args_list
        (health_event,) = [call for call in events if json.loads(call.args[0])["type"] == E.HP_CHANGED]
        assert health_event.kwargs["destination_identities"] == [ally]
        health = json.loads(health_event.args[0])
        assert {key: health[key] for key in ("current", "max", "temp_hp")} == {
            **effective_hp(await player_row(ally)),
            "temp_hp": 1,
        }
        state = None
    await check_pools({mage: 0, ally: max(before, 1), control: 0}, state)
    ward(cast, ally, before)


@pytest.mark.parametrize(
    ("patron", "before", "total", "objection"),
    [
        ("orenthel", 0, 17, False),
        ("orenthel", 1, 17, False),
        ("orenthel", 5, 17, False),
        ("orenthel", 0, 22, False),
        ("orenthel", 0, 17, True),
        ("kaelen", 0, 17, False),
    ],
)
async def test_shield_wards_the_mage(reset_db_pool, patron, before, total, objection):
    await exercise_shield(patron, before, total, objection)


async def exercise_shield(patron: str, before: int, total: int, objection: bool) -> None:
    with patch("combat_agent.create_combat_agent", wraps=create_combat_agent):
        async with defense_fight("mage", ally_archetype="diplomat") as fight:
            mage, ally = fight.players
            await set_favor(fight, mage, patron)
            await update_player(mage, temp_hp=before)
            state = await fight.reload()
            participant(state, mage).temp_hp = before
            await fight.persist()
            if patron == "orenthel" and not before and total == 17 and not objection:
                path = Path(__file__).resolve().parents[4] / "packages/shared/fixtures/god_profiles.json"
                corpus = json.loads(path.read_text())["renewing_spark"]
                profile = (await fight.command("query_info", {"kind": "patron"}))["synergy"]
                assert (profile["name"], profile["type"]) == (corpus["name"], corpus["type"])
                (clause,) = profile["clauses"]
                assert {key: clause.get(key) for key in corpus["clauses"][0]} == corpus["clauses"][0]
            enemy = fight.enemies[0]
            await declare_attacks(fight, mage, enemy)
            with (
                patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(total - self.modifier)),
                patch("check_resolution_attack.dice_roll", return_value=_damage_die(8)),
                patch("combat_reaction_contest.random.randint", side_effect=[20, 1]),
            ):
                packets = await spend(fight, SHIELD, stage="pre_roll")
                await check_pools({mage: before, ally: 0}, await fight.reload())
                if objection:
                    result = await tool_receipt(fight, ally, "activate", {"id": "diplomat_objection"})
                    assert not result.is_error, result.output
                packets += await fight.drain()
            shield = reaction_packet(packets, SHIELD)
            assert shield["ac_bonus"] == 3
            if patron == "orenthel":
                ward(shield, mage, before)
            else:
                assert "mage_warding" not in shield
            if objection:
                assert any(p.get("hesitated") and p["actor_id"] == enemy for p in packets)
            else:
                attack = action_packet(packets, enemy, SWORD)
                assert attack["hit"] is (total > 19)
                if attack["hit"]:
                    assert attack["temp_hp_absorbed"] == 1
            expected = max(before, 1) if patron == "orenthel" and total < 19 else 0
            await check_pools({mage: expected, ally: 0}, await fight.reload())


async def renewing_spark(_world: SimpleNamespace) -> None:
    await exercise_shield("orenthel", 0, 17, False)


@pytest.mark.parametrize(("spell", "self_cast"), [(FLY, False), (HASTE, False), (LIBRARY_SHIELD, True)])
async def test_direct_combat_cast_wards_both_stores(mage_party, spell, self_cast):
    ctx, mage, ally, control = mage_party
    assert ctx.userdata.in_combat
    recipient = mage if self_cast else ally
    cast = json.loads(await activate(ctx, spell, target_id=None if self_cast else ally))
    ward(cast, recipient, 0)
    stored = await db_mutations.load_combat_state(ctx.userdata.combat_state.combat_id)
    assert stored is not None
    await check_pools({mage: int(self_cast), ally: int(not self_cast), control: 0}, ctx.userdata.combat_state)
    assert participant(stored, recipient).temp_hp == 1


async def test_direct_combat_cast_on_a_foe_wards_no_one(mage_party):
    ctx, mage, ally, control = mage_party
    cast = json.loads(await activate(ctx, HASTE, target_id="foe"))
    assert "mage_warding" not in cast
    assert participant(ctx.userdata.combat_state, "foe").temp_hp == 0
    await check_pools({mage: 0, ally: 0, control: 0}, ctx.userdata.combat_state)


async def test_exploration_ward_follows_applied_condition_targets(mage_party):
    ctx, mage, ally, control = mage_party
    ctx.userdata.combat_state = None
    cast = json.loads(await activate(ctx, INVISIBILITY, target_ids=[ally]))
    await check_pools({mage: 0, ally: 1, control: 0})
    ward(cast, ally, 0)


SCENARIOS = {CLAUSE: ("patron_synergy_heal:grant_mage_warding", renewing_spark, [()])}


@pytest.mark.parametrize(("spell", "combat"), [(LIBRARY_SHIELD, False), (LIBRARY_SHIELD, True), (HASTE, True)])
async def test_default_target_is_the_mage(mage_party, spell, combat):
    ctx, mage, ally, control = mage_party
    if combat:
        packets, state = await play(ctx, cast_spell(mage, spell, None))
        cast = receipt(packets, mage)
    else:
        ctx.userdata.combat_state = None
        cast = json.loads(await activate(ctx, spell))
        state = None
    await check_pools({mage: 1, ally: 0, control: 0}, state)
    ward(cast, mage, 0)


async def test_combat_companion_receives_the_ward(mage_party):
    ctx, mage, ally, control = mage_party
    state = ctx.userdata.combat_state
    companion = CombatParticipant("companion_kael", "Kael", "companion", 6, 25, 25, 14)
    state.participants.append(companion)
    state.initiative_order.append(companion.id)
    place_actors(state)
    await db_mutations.save_combat_state(state.combat_id, state.to_dict())
    packets, state = await play(ctx, cast_spell(mage, INVISIBILITY, companion.id))
    assert participant(state, companion.id).temp_hp == 1
    ward(receipt(packets, mage), companion.id, 0)
    await check_pools({mage: 0, ally: 0, control: 0}, state)


@pytest.mark.parametrize(
    ("spell", "target"),
    [(BOLT, "self"), (MAGE_LIGHT, "ally"), (FLY, "other_patron"), (INVISIBILITY, "companion")],
)
async def test_exploration_exclusions(mage_party, spell, target):
    ctx, mage, ally, control = mage_party
    ctx.userdata.combat_state = None
    if target == "other_patron":
        await update_player(mage, divine_favor={"patron": "kaelen", "level": 40, "max": 100})
    recipients = {"self": mage, "ally": ally, "other_patron": ally, "companion": "companion_kael"}
    if target == "companion":
        ctx.userdata.companion = CompanionState(recipients[target], "Kael")
    cast = json.loads(await activate(ctx, spell, target_id=recipients[target]))
    await check_pools({mage: 0, ally: 0, control: 0})
    assert "mage_warding" not in cast


@pytest.mark.parametrize(
    ("spell", "target"),
    [(BOLT, "foe"), (HOLD, "foe"), (HASTE, "foe"), (HASTE, "missing"), (HASTE, "fallen"), (INVISIBILITY, "immune")],
)
async def test_combat_exclusions(mage_party, spell, target):
    ctx, mage, ally, control = mage_party
    state = ctx.userdata.combat_state
    recipient = {"immune": ally, "fallen": ally, "foe": "foe", "missing": "missing"}[target]
    if target == "immune":
        participant(state, ally).condition_immunities = {"invisible": "innate immunity"}
        await db_mutations.save_combat_state(state.combat_id, state.to_dict())
    if target == "fallen":
        fallen = participant(state, ally)
        fallen.hp_current = 0
        fallen.is_fallen = True
        before = await player_row(ally)
        await update_player(ally, hp={**before["hp"], "current": 0})
        await db_mutations.save_combat_state(state.combat_id, state.to_dict())
    packets, state = await play(ctx, cast_spell(mage, spell, recipient))
    cast = receipt(packets, mage)
    await check_pools({mage: 0, ally: 0, control: 0}, state)
    assert participant(state, "foe").temp_hp == 0
    assert "mage_warding" not in cast
    if target == "immune":
        assert "condition_applied" not in cast


async def test_unaffordable_spell_leaves_each_pool_unchanged(mage_party):
    ctx, mage, ally, control = mage_party
    ctx.userdata.combat_state = None
    before = await player_row(mage)
    await update_player(mage, focus={**before["focus"], "current": 0})
    before = await player_row(mage)
    with pytest.raises(ToolError, match=r"[Ff]ocus"):
        await activate(ctx, HASTE, target_id=ally)
    assert await player_row(mage) == before
    await check_pools({mage: 0, ally: 0, control: 0})


async def test_earlier_outline_interrupts_queued_invisibility(mage_party):
    ctx, mage, ally, control = mage_party
    state = ctx.userdata.combat_state
    druid = await add_player(ctx, "druid", (FIRE,))
    participant(state, druid).initiative = 40
    spatial_record(state)["positions"][mage]["x"] = 40
    await db_mutations.save_combat_state(state.combat_id, state.to_dict())
    before = await player_row(mage)
    packets, state = await play(ctx, cast_spell(mage, INVISIBILITY, ally), cast_spell(druid, FIRE, ally))
    refused = next(p for p in packets if p["actor_id"] == mage)
    assert refused["resolved"] is False and "outline" in refused["reason"].lower()
    assert any(c["type"] == "outlined" for c in participant(state, ally).conditions)
    assert (await player_row(mage))["focus"] == before["focus"]
    await check_pools({mage: 0, ally: 0, control: 0}, state)


async def test_shield_against_an_auto_hit_grants_no_ward(reset_db_pool):
    with patch("combat_agent.create_combat_agent", wraps=create_combat_agent):
        async with defense_fight("mage", "still") as fight:
            mage, ally = fight.players
            await set_favor(fight, mage, "orenthel")
            (enemy,) = fight.enemies
            await declare(fight, actor_id=enemy, **strike(mage, action="Serenity's Touch"))
            packets = await spend(fight, SHIELD, stage="pre_roll")
            packets += await fight.drain()
            shield = reaction_packet(packets, SHIELD)
            assert shield["reason"] == "Shield Spell only protects against attack rolls."
            assert action_packet(packets, enemy, "Serenity's Touch")["temp_hp_absorbed"] == 0
            await check_pools({mage: 0, ally: 0}, await fight.reload())
            assert "mage_warding" not in shield
