"""Exclusions and reaction producers exercised through real spell settlement."""

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _resolve_round
from acceptance._catalog_cutover_helpers import started as started
from acceptance._enemy_opportunity_helpers import attack as enemy_attack
from acceptance._enemy_opportunity_helpers import declare, move, resolve_allies, strikes
from acceptance._enemy_opportunity_helpers import fight as fight
from acceptance._spell_hostile_condition_helpers import STUN, add_player, cast_spell, defend, play, receipt, reload
from acceptance._spell_hostile_condition_helpers import dev_db_pool as dev_db_pool
from acceptance.defensive_reactions_harness import SHIELD, defense_fight, spend
from acceptance.test_architect_fight import isolated_content_cache as isolated_content_cache
from acceptance.test_architect_fight import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_architect_fight import pos
from acceptance.test_architect_reaction import archers as archers
from acceptance.test_architect_reaction import assert_cost, bow, cast, caster_pools, forced_rolls, set_favor, teach
from acceptance.test_architect_reaction import declare as declare_archers
from acceptance.test_choir_encounter import search
from acceptance.test_spell_damage_riders import FROST, JUDGMENT, RIDERS, SPARK, resolve_step, rider_foe, settle_cast
from acceptance.test_still_anchors import fresh_session
from acceptance.test_vanish_guards import veil
from combat.test_area_spell_recipients import add_enemies
from combat.test_spell_damage_lands import minimum_roll, prepare_spell
from combat.test_spell_damage_lands import spell_fight as spell_fight
from livekit.agents import ToolError
from voice_condition_fixtures import participant

import character_spells
import check_resolution_save
import combat_recharge
import combat_spatial
import combat_turn
import db
import db_mutations
import spells
from check_resolution import D20Roll

BOLT = "arcane_bolt"


@pytest.mark.parametrize("spell_id,condition,face", RIDERS)
async def test_killing_damage_does_not_write_a_condition(spell_fight, spell_id, condition, face):
    await prepare_spell(spell_fight, spell_id)
    await rider_foe(spell_fight, hp=1)
    await rider_foe(spell_fight, "bandit", foe_id="survivor")
    result, saved = await settle_cast(spell_fight, spell_id, face, extra=(defend("survivor"),))
    target = participant(saved, "foe")
    assert target.hp_current == 0 and target.is_fallen
    assert not target.conditions and result.get("condition_inflicted") != condition


async def test_spark_miss_writes_no_condition(spell_fight):
    result, state = await settle_cast(spell_fight, SPARK, 1)
    assert not result["hit"] and "condition_inflicted" not in result
    assert not participant(state, "foe").conditions


async def test_later_rider_spares_an_already_fallen_recipient(spell_fight):
    ctx = spell_fight
    first = ctx.userdata.player_id
    second = await add_player(ctx, "mage", (SPARK,))
    participant(ctx.userdata.combat_state, first).initiative = 20
    await rider_foe(ctx, hp=1)
    await rider_foe(ctx, "bandit", foe_id="survivor")
    packets, saved = await play(ctx, cast_spell(first, BOLT), cast_spell(second, SPARK), defend("survivor"), face=15)
    first_hit, second_hit = (receipt(packets, actor)["damage_result"] for actor in (first, second))
    assert first_hit["target_fallen"] and "no longer available" in second_hit["reason"]
    assert not participant(saved, "foe").conditions


async def test_area_rider_keeps_each_recipients_save_health_and_immunity(spell_fight, monkeypatch):
    ctx = spell_fight
    caster = ctx.userdata.player_id
    spell_id = "divine_flame_strike"
    await prepare_spell(ctx, spell_id)
    ally = await add_player(ctx, "mage")
    choir = await rider_foe(ctx, "hollow_choir", foe_id="choir")
    assert "restrained" in choir.condition_immunities
    pool = await db.get_pool()
    row = json.loads(await pool.fetchval("SELECT data FROM spells WHERE id=$1", spell_id))
    row["combat_damage"]["rider"] = {"condition": "restrained", "expires": "target_turn_end"}
    monkeypatch.setitem(spells._spells, spell_id, spells.parse_spell_row(spell_id, row))
    await add_enemies(
        ctx,
        {
            "foe": (0, 0, 0),
            "saved": (1, 0, 0),
            "lethal": (2, 0, 0),
            "choir": (3, 0, 0),
            ally: (4, 0, 0),
            "outside": (20, 0, 0),
        },
    )
    state = ctx.userdata.combat_state
    participant(state, ally).initiative = 5
    participant(state, "lethal").hp_current = 1
    participant(state, "saved").attributes["dexterity"] = 40
    await db_mutations.save_combat_state(state.combat_id, state.to_dict())
    await combat_turn.declare_phase(ctx, [cast_spell(caster, spell_id)])
    with forced_rolls(2, 5), harmonic_save(20):
        response = await resolve_step(ctx)
    results = {r["target_id"]: r for r in receipt(response["packets"], caster)["damage_results"]}
    saved = await reload(ctx)
    assert set(results) == {"foe", "lethal", "saved", "choir", ally}
    assert results[ally]["condition_inflicted"] == "restrained"
    assert "inflicted_round" not in participant(saved, ally).conditions[0]
    assert results["foe"]["condition_inflicted"] == "restrained"
    assert participant(saved, "foe").conditions[0]["type"] == "restrained"
    assert results["saved"]["save"]["success"] and results["saved"]["damage"] == 4, results["saved"]
    assert results["lethal"]["target_fallen"]
    assert results["choir"]["condition_immune"] == "restrained" and results["choir"]["damage"] > 0
    for excluded in ("saved", "lethal", "choir", "outside"):
        assert "condition_inflicted" not in results.get(excluded, {})
        assert not participant(saved, excluded).conditions
    assert participant(saved, "outside").hp_current == 100


async def test_reactive_wall_takes_spark_damage_but_no_rider(archers):
    await teach(archers, SPARK)
    caster = archers.players[0]
    state = await archers.reload()
    owner = state.architect_encounter["owner_id"]
    await declare_archers(archers, cast(caster, SPARK, owner))
    with forced_rolls(18):
        result = await archers.command("resolve_phase", {})
    packet = next(p for p in result["packets"] if p["actor_id"] == caster)
    wall_id = packet["reactive_architecture"]["wall_id"]
    damage = packet["cast"]["damage_result"]
    after = await archers.reload()
    assert damage["target_id"] == wall_id and damage["damage"] > 0
    assert "condition_inflicted" not in damage
    assert not participant(after, wall_id).conditions and not participant(after, owner).conditions


async def test_judgment_rider_triggers_legendary_resistance_below_damage_threshold(archers):
    await teach(archers, JUDGMENT)
    caster = archers.players[0]
    state = await archers.reload()
    owner = state.architect_encounter["owner_id"]
    architect = participant(state, owner)
    key = combat_recharge.action_key(combat_recharge.LEGENDARY_RESISTANCE)
    prior = architect.action_ledger[key]["remaining"]
    state.architect_encounter["reaction_round"] = state.round_number
    await archers.persist()
    await declare_archers(archers, cast(caster, JUDGMENT, owner))
    with forced_rolls(1, 8):
        result = await archers.command("resolve_phase", {})
    damage = receipt(result["packets"], caster)["damage_result"]
    saved = participant(await archers.reload(), owner)
    assert damage["damage"] == 8 and 8 * damage["damage"] < architect.hp_current
    assert damage["save"]["success_override"] == "Legendary Resistance"
    assert saved.action_ledger[key]["remaining"] == prior - 1 and not saved.conditions


@pytest.mark.parametrize("spell_id,condition,face", [RIDERS[0], RIDERS[1]])
async def test_fate_holds_the_rider_until_damage_is_committed(archers, spell_id, condition, face):
    spell = await teach(archers, spell_id)
    await set_favor(archers, "zhael", 40)
    caster = archers.players[0]
    state = await archers.reload()
    owner = state.architect_encounter["owner_id"]
    state.architect_encounter["reaction_round"] = state.round_number
    architect = participant(state, owner)
    key = combat_recharge.action_key(combat_recharge.LEGENDARY_RESISTANCE)
    architect.action_ledger[key]["remaining"] = 0
    await archers.persist()
    before = await caster_pools(caster)
    await declare_archers(archers, cast(caster, spell_id, owner))
    with forced_rolls(face + (4 if spell_id == FROST else 0), 8):
        held = await archers.command("resolve_phase", {})
        assert held["fate_offer"]["die"] == (19 if spell_id == FROST else 1)
        saved = await archers.reload()
        assert participant(saved, owner).hp_current == architect.hp_current
        assert not participant(saved, owner).conditions
        paid = await caster_pools(caster)
        await fresh_session(archers, saved)
        result = await archers.command("resolve_phase", {})
    damage = receipt(result["packets"], caster)["damage_result"]
    saved = participant(await archers.reload(), owner)
    assert damage["condition_inflicted"] == condition
    assert saved.hp_current == architect.hp_current - damage["damage"] < architect.hp_current
    assert [c["type"] for c in saved.conditions] == [condition]
    assert_cost(before, await caster_pools(caster), spell)
    assert await caster_pools(caster) == paid


def harmonic_save(face: int, *, passing_actor: str | None = None):
    roll_save = check_resolution_save.roll_participant_save

    def roll(target, attribute, dc, effect, **kwargs):
        if effect != "Harmonic Shield":
            return roll_save(target, attribute, dc, effect, **kwargs)
        fixed_face = 20 if target.id == passing_actor else face
        with patch.object(D20Roll, "roll", lambda die, rng=None: die.evaluate(fixed_face)):
            return roll_save(target, attribute, dc, effect, **kwargs)

    return patch.object(check_resolution_save, "roll_participant_save", side_effect=roll)


def harmonic_available(response):
    [reaction] = next(p for p in response["participants"] if p["id"] == "choir_zone")["automatic_reactions"]
    assert reaction["id"] == "Harmonic Shield"
    return reaction["available"]


async def test_harmonic_shield_availability_and_redirect_follow_spark(started):
    ctx, _ = await started("hollow_choir", player_class="mage")
    assert harmonic_available(await search(ctx))
    caster = ctx.userdata.player_id
    ally = await add_player(ctx, "mage", (BOLT,))
    state = ctx.userdata.combat_state
    participant(state, caster).initiative = 20
    participant(state, ally).initiative = 15
    await db_mutations.save_combat_state(state.combat_id, state.to_dict())
    await character_spells.record_learned(caster, SPARK, "discovery")

    bolt = cast_spell(ally, BOLT, "choir_zone")
    with harmonic_save(1):
        before, _ = await play(ctx, defend(caster), bolt, face=18)
    assert receipt(before, ally)["damage_result"]["target_id"] == ally

    await combat_turn.declare_phase(ctx, [cast_spell(caster, SPARK, "choir_zone"), bolt])
    with forced_rolls(18), harmonic_save(1, passing_actor=caster):
        response = await _resolve_round(ctx)
    spark = receipt(response["packets"], caster)["damage_result"]
    assert spark["hit"] and spark["damage"] == 0 and spark["condition_inflicted"] == "reactions_suppressed"
    assert not harmonic_available(response)
    assert participant(await reload(ctx), "choir_zone").conditions[0]["type"] == "reactions_suppressed"
    assert receipt(response["packets"], ally)["damage_result"]["target_id"] == "choir_zone"

    await combat_turn.declare_phase(ctx, [bolt])
    with forced_rolls(18), harmonic_save(1):
        after = await _resolve_round(ctx)
    assert harmonic_available(after)
    assert receipt(after["packets"], ally)["damage_result"]["target_id"] == ally


async def test_redirected_judgment_stays_on_the_caster_through_its_next_turn(spell_fight):
    ctx = spell_fight
    await prepare_spell(ctx, JUDGMENT)
    caster = ctx.userdata.player_id
    await rider_foe(ctx, "hollow_choir")
    with patch("dice.roll", side_effect=minimum_roll):
        packets, saved = await play(ctx, cast_spell(caster, JUDGMENT), defend("foe"), face=1)
    damage = receipt(packets, caster)["damage_result"]
    assert damage["target_id"] == caster and damage["condition_inflicted"] == "stunned"
    assert not participant(saved, "foe").conditions
    assert participant(saved, caster).conditions[0]["type"] == "stunned"
    with pytest.raises(ToolError, match="stunned"):
        await combat_turn.declare_phase(ctx, [defend(caster), defend("foe")])
    _, saved = await play(ctx, defend("foe"))
    assert not participant(saved, caster).conditions
    await play(ctx, defend(caster), defend("foe"))


@pytest.mark.parametrize("judgment_first", [False, True])
async def test_judgment_and_power_word_stun_preserve_the_con_resave(spell_fight, judgment_first):
    ctx = spell_fight
    judgment = ctx.userdata.player_id
    await prepare_spell(ctx, JUDGMENT)
    mage = await add_player(ctx, "mage", (STUN,))
    state = ctx.userdata.combat_state
    participant(state, judgment).initiative = 20 if judgment_first else 10
    participant(state, mage).initiative = 10 if judgment_first else 20
    await rider_foe(ctx, hp=70)
    await combat_turn.declare_phase(ctx, [cast_spell(judgment, JUDGMENT), cast_spell(mage, STUN), defend("foe")])
    with forced_rolls(1, 8):
        response = await resolve_step(ctx)
    damage = receipt(response["packets"], judgment)["damage_result"]
    expectation = "condition_inflicted" if judgment_first else "condition_already_held"
    assert damage[expectation] == "stunned"
    [instance] = participant(await reload(ctx), "foe").conditions
    assert (instance["source"], instance["duration"], instance["tick_save"]) == (STUN, None, "con")
    with forced_rolls(1):
        await _resolve_round(ctx)
    _, next_round = await play(ctx, defend(judgment), defend(mage))
    assert [condition["source"] for condition in participant(next_round, "foe").conditions] == [STUN]


async def test_stunned_veilrender_cannot_absorb(spell_fight):
    ctx = spell_fight
    caster = ctx.userdata.player_id
    await prepare_spell(ctx, JUDGMENT)
    mage = await add_player(ctx, "mage", ("arcane_magic_missile",))
    participant(ctx.userdata.combat_state, caster).initiative = 20
    await rider_foe(ctx, "hollow_veilrender", hp=70)
    await combat_turn.declare_phase(
        ctx, [cast_spell(caster, JUDGMENT), cast_spell(mage, "arcane_magic_missile"), defend("foe")]
    )
    with forced_rolls(1, 4):
        response = await resolve_step(ctx)
    packets = response["packets"]
    stunned = receipt(packets, caster)["damage_result"]
    assert stunned["condition_inflicted"] == "stunned"
    missile = receipt(packets, mage)
    assert "absorbed" not in missile and missile["damage_result"]["damage"] > 0
    assert participant(await reload(ctx), "foe").hp_current < stunned["target_hp_current"]


async def test_stunned_architect_cannot_raise_a_wall(archers):
    caster, archer, _ = archers.players
    await teach(archers, STUN)
    state = await archers.reload()
    owner = state.architect_encounter["owner_id"]
    participant(state, owner).hp_current = 75
    state.architect_encounter["reaction_round"] = state.round_number
    await archers.persist()
    await declare_archers(archers, cast(caster, STUN, owner))
    with forced_rolls(1):
        packets = await archers.drain()
    assert receipt(packets, caster)["condition_inflicted"] == "stunned"
    before = await archers.reload()
    await archers.command("declare_phase", {"declarations": [bow(archer, owner)]})
    with forced_rolls():
        result = await archers.command("resolve_phase", {})
    strike = next(p for p in result["packets"] if p["actor_id"] == archer)
    assert strike["target"] == participant(before, owner).name and strike["damage"] > 0
    assert "reactive_architecture" not in strike
    assert (await archers.reload()).architect_encounter["structure_ids"] == before.architect_encounter["structure_ids"]


@pytest.mark.parametrize("fight", [{"bandit": "hollow_mawling", "player": {"class": "rogue"}}], indirect=True)
async def test_concealment_survives_spark_expiring_on_a_packetless_turn(fight):
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
        await fight.drain()
    assert participant(await fight.reload(), "bandit").conditions[0]["type"] == "reactions_suppressed"
    await veil(fight)

    await fight.command("declare_phase", {"declarations": [move(mover, 20)]})
    with forced_rolls(18):
        packets = await resolve_allies(fight)
    assert not strikes(packets)
    state = await fight.reload()
    assert state.spatial["positions"][mover] == pos(20)
    assert not state.reactions_available["bandit"]["spent"]
    assert not participant(state, "bandit").conditions
    await fight.drain()

    state = await fight.reload()
    combat_spatial.place(state, mover, pos(3))
    await fight.persist()
    await declare(fight, move(mover, 20), move(caster, 20))
    with forced_rolls(18):
        packets = await resolve_allies(fight)
    assert [strike["target_id"] for strike in strikes(packets)] == [caster]
    assert (await fight.reload()).spatial["positions"][mover] == pos(20)


async def test_redirected_spark_suppresses_the_mages_reaction_until_next_turn(reset_db_pool):
    async with defense_fight("mage", ally_archetype="mage") as harness:
        mage = harness.players[0]
        enemy = harness.enemies[0]
        await character_spells.record_learned(mage, SPARK, "discovery")
        await rider_foe(SimpleNamespace(userdata=harness.sd), "hollow_choir", foe_id="choir")
        state = await harness.reload()
        assert SHIELD in participant(state, mage).reaction_ids
        await harness.command(
            "declare_phase",
            {
                "declarations": [
                    {
                        "kind": "interact",
                        "actor_id": mage,
                        "action": "choir_search_arcana",
                        "target_id": "choir_sound",
                        "reshape": [],
                    }
                ]
            },
        )
        with forced_rolls():
            await harness.drain()
        choir = (await harness.reload()).choir_encounter
        assert choir is not None and choir["phase"] == "exposed"
        blade = enemy_attack(enemy, mage, "Short Sword")
        await harness.command("declare_phase", {"declarations": [blade]})
        with forced_rolls(18):
            await spend(harness, SHIELD, stage="pre_roll")
            await harness.drain()

        await harness.command("declare_phase", {"declarations": [cast(mage, SPARK, "choir"), blade]})
        with forced_rolls(18), harmonic_save(1):
            result = await harness.command("resolve_phase", {})
            spark = receipt(result["packets"], mage)["damage_result"]
            assert spark["target_id"] == mage and spark["condition_inflicted"] == "reactions_suppressed"
            saved = await harness.reload()
            assert participant(saved, mage).conditions[0]["originating_participant_id"] == mage
            refusal = await harness.command("activate", {"id": SHIELD}, error=True)
            assert "cannot take reactions" in refusal
            result = await harness.command("resolve_phase", {})
            assert result["next"]["waiting_on"] is None
            assert any(p["actor_id"] == enemy and p.get("damage", 0) > 0 for p in result["packets"])
            if (await harness.reload()).round_number == saved.round_number:
                await harness.drain()

        await harness.command("declare_phase", {"declarations": [blade]})
        with forced_rolls(18):
            await spend(harness, SHIELD, stage="pre_roll")
        assert not participant(await harness.reload(), mage).conditions


async def test_a_second_spark_refreshes_the_source_turn(spell_fight):
    ctx = spell_fight
    early = ctx.userdata.player_id
    late = await add_player(ctx, "mage", (SPARK,))
    participant(ctx.userdata.combat_state, early).initiative = 20
    await rider_foe(ctx)
    packets, after = await play(ctx, cast_spell(early, SPARK), cast_spell(late, SPARK), face=18)
    assert receipt(packets, early)["damage_result"]["condition_inflicted"] == "reactions_suppressed"
    assert receipt(packets, late)["damage_result"]["condition_inflicted"] == "reactions_suppressed"
    [condition] = participant(after, "foe").conditions
    assert condition["originating_participant_id"] == late
