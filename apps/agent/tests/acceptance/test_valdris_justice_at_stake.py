"""Justice at Stake through registered combat and patron tools."""

from types import SimpleNamespace

import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import row
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import attack, game_tools
from _zhael_marshal_rally_fixtures import ability
from acceptance.synergy_discovery import ELEMENT, discover, prepare, roll_check
from acceptance.test_synergy_context import paired, setup_actor
from acceptance.test_valdris_oath_breach import dev_db_pool as dev_db_pool
from acceptance.test_valdris_oath_breach import oath_book, registered, swear
from sample_fixtures import published_payloads
from test_aelora_gift import _live_party
from test_encounter_facts_damage import GOBLIN, dice, fight, goblin_strike
from test_zhael_fate_sprint_saves import _reroll
from voice_condition_fixtures import participant

import character_spells
import db_mutations
from activate_tools import activate
from conditions import apply_condition
from creature_combat_loader import load_creature_enemy
from patron_gifts import VEYTHAR_INSIGHT
from query_tools import query_info


async def attack_against_first_aggressor(world: SimpleNamespace) -> None:
    async with fight(world, "valdris", archetype="paladin", ally_hp=20) as f:
        registered(f)
        oath = await swear(f.session)
        await f.round(goblin_strike(GOBLIN, f.hero), faces=(1,))
        target = participant(f.session.combat_state, GOBLIN)
        target.ac = 11
        packets = await f.round(attack(f.hero, GOBLIN), faces=(10,))
        packet = next(p for p in packets if p["actor_id"] == f.hero)
        assert packet["oath_justice"] == {
            "oath_id": oath["oath_id"],
            "context": "attack",
            "target_id": GOBLIN,
            "modifier": 2,
            "reason": "aggression",
        }
        assert packet["roll"] == 10 and packet["attack_total"] == packet["target_ac"] == 13
        assert packet["hit"] is True
        assert participant(f.session.combat_state, GOBLIN).hp_current == 45
        [event] = [e for e in published_payloads(f.session.room) if e.get("oath_justice")]
        assert event["total"] == 13 and event["oath_justice"] == packet["oath_justice"]


SCENARIOS = {"valdris_justice_at_stake": ("oath_justice:attack_receipt", attack_against_first_aggressor, [()])}
test_attack_against_first_aggressor = attack_against_first_aggressor


@pytest.mark.parametrize(
    "kind,skill", [("skill", "athletics"), ("social", "persuasion"), ("discover", "investigation")]
)
async def test_tag_returned_by_patron_query(world, kind, skill) -> None:
    if kind == "discover":
        await prepare(world, "paladin", patron="valdris")
    else:
        await setup_actor(world, "valdris", "paladin")
    session = world.ctx.userdata
    oath = await swear(session)
    profile = await game_tools(session, query_info)("query_info", kind="patron")
    clause = next(c for c in profile["synergy"]["clauses"] if c["implementation_id"] == "valdris_justice_at_stake")
    tag = clause["synergy_context"]
    assert (tag, clause["skill"], clause["bonus"]) == ("justice_at_stake", None, 2)
    if kind == "discover":
        roll = discover()
        before = await roll_check(world, roll)
        session.attempted_discoveries.clear()
        after = await roll_check(world, {**roll, "synergy_context": tag})
        assert (before["outcome"], after["outcome"]) == ("not_found", "discovered")
        assert (await row(world, 0))["flags"][f"{ELEMENT}.discovered"] is True
    else:
        before, after = await paired(world, kind, skill, tag)
    assert after["total"] - before["total"] == 2
    assert after["roll"] == before["roll"]
    receipt = after["context_synergy"]["oath_justice"]
    assert (receipt["oath_id"], receipt["modifier"], receipt["skill"]) == (oath["oath_id"], 2, skill)


@pytest.mark.parametrize("roll,critical,hit", [(1, False, False), (20, True, True)])
async def test_natural_attack_face_wins_over_total(world, roll, critical, hit) -> None:
    async with fight(world, "valdris", archetype="paladin", ally_hp=20) as f:
        registered(f)
        await swear(f.session)
        await f.round(goblin_strike(GOBLIN, f.hero), faces=(1,))
        target = participant(f.session.combat_state, GOBLIN)
        target.ac = 1 if roll == 1 else 40
        before = target.hp_current
        packets = await f.round(attack(f.hero, GOBLIN), faces=(roll,))
        packet = next(p for p in packets if p["actor_id"] == f.hero)
        assert (packet["roll"], packet["critical"], packet["hit"]) == (roll, critical, hit)
        assert packet["oath_justice"]["modifier"] == 2
        assert (participant(f.session.combat_state, GOBLIN).hp_current < before) == hit


async def test_spell_attack_against_wrongdoer(world) -> None:
    async with fight(world, "valdris", archetype="paladin", ally_hp=20) as f:
        registered(f)
        oath = await swear(f.session)
        await character_spells.record_learned(f.hero, "arcane_bolt", "training", is_prepared=True, conn=world.pool)
        await f.round(goblin_strike(GOBLIN, f.hero), faces=(1,))
        target = participant(f.session.combat_state, GOBLIN)
        target.ac = 11
        packets = await f.round(ability(f.hero, "arcane_bolt", GOBLIN), faces=(10,))
        attack_packet = next(p["cast"]["damage_result"] for p in packets if p["actor_id"] == f.hero)
        assert attack_packet["attack_total"] == 13
        assert attack_packet["hit"] is True
        assert attack_packet["oath_justice"]["oath_id"] == oath["oath_id"]
        assert attack_packet["oath_justice"]["target_id"] == GOBLIN


@pytest.mark.parametrize("condition,faces,kept", [("restrained", (3, 14), 14), ("blinded", (3, 14), 3)])
async def test_attack_applies_justice_to_kept_face(world, condition, faces, kept) -> None:
    async with fight(world, "valdris", archetype="paladin", ally_hp=20) as f:
        registered(f)
        await swear(f.session)
        await f.round(goblin_strike(GOBLIN, f.hero), faces=(1,))
        actor = participant(f.session.combat_state, GOBLIN if condition == "restrained" else f.hero)
        actor.conditions = apply_condition([], condition, source=GOBLIN, duration=3)
        packets = await f.round(attack(f.hero, GOBLIN), faces=faces)
        packet = next(p for p in packets if p["actor_id"] == f.hero)
        assert packet["roll"] == kept
        assert packet["attack_total"] == kept + 3
        assert packet["oath_justice"]["modifier"] == 2


@pytest.mark.parametrize("breaking", [False, True])
async def test_held_attack_keeps_offer_math_and_commits_breach_on_settlement(world, breaking) -> None:
    async with fight(world, "valdris", archetype="paladin", ally_hp=20) as f:
        registered(f)
        oath = await swear(f.session)
        if breaking:
            await db_mutations.set_player_flag(f.ally, f"grievance:{GOBLIN}", "injustice")
        else:
            await f.round(goblin_strike(GOBLIN, f.hero), faces=(1,))
        participant(f.session.combat_state, GOBLIN).ac = 11
        await configure(world, "zhael", "warrior", index=1, patron_gifts={"zhael_lucky": {"spent": True}})
        lifecycle = _live_party(f.session, f.hero, f.ally)
        try:
            await f.declare(attack(f.hero, GOBLIN))
            with dice(8, 10):
                offer = (await f.call("resolve_phase"))["fate_offer"]
                assert offer["total"] == (9 if breaking else 11)
                assert (await oath_book(f.hero))["records"][0]["status"] == "active"
                with f.session._bind_authenticated_actor(f.ally, 1, lambda *_: None):
                    result = await _reroll(f.call, offer)
            packet = next(p for p in result["packets"] if p["actor_id"] == f.hero)
            assert packet["roll"] == 10
            assert packet["attack_total"] == (11 if breaking else 13)
            assert packet["hit"] is not breaking
            assert packet["oath_justice"]["oath_id"] == oath["oath_id"]
            assert participant(f.session.combat_state, GOBLIN).hp_current == (50 if breaking else 45)
            assert (await oath_book(f.hero))["records"][0]["status"] == ("broken" if breaking else "active")
        finally:
            await lifecycle.aclose()


@pytest.mark.parametrize("stored_tag", ["current", "legacy", "invalid"])
async def test_discovery_retry_composes_automatic_bonus_and_explicit_context(world, stored_tag) -> None:
    await prepare(world, "rogue", insight=True)
    tag = "justice_at_stake"
    before = await roll_check(world, {**discover(), "synergy_context": tag}, die=2)
    receipt = before["context_synergy"]
    assert receipt["oath_justice"]["reason"] == "unheld"
    assert receipt["automatic_discovery"]["clause_id"] == "veythar_hidden_knowledge"
    assert before["total"] == 3
    key = ["patron_gifts", VEYTHAR_INSIGHT, "pending", "synergy_context"]
    assert (await row(world, 0))["patron_gifts"][VEYTHAR_INSIGHT]["pending"]["synergy_context"] == tag
    if stored_tag == "legacy":
        await world.pool.execute("UPDATE players SET data=data #- $2::text[] WHERE player_id=$1", world.ids[0], key)
    if stored_tag == "invalid":
        await world.pool.execute(
            "UPDATE players SET data=jsonb_set(data, $2::text[], 'null') WHERE player_id=$1", world.ids[0], key
        )
    call = game_tools(world.ctx.userdata, activate)
    if stored_tag == "invalid":
        with pytest.raises(ValueError, match="Unknown synergy_context"), dice():
            await call("activate", id=VEYTHAR_INSIGHT)
        return
    with dice(14):
        after = await call("activate", id=VEYTHAR_INSIGHT)
    assert (after["total"], after["outcome"]) == (15, "discovered")
    assert after["context_synergy"] == (receipt if stored_tag == "current" else receipt["automatic_discovery"])


async def test_redirected_spell_checks_the_resolved_target(world) -> None:
    async with fight(world, "valdris", archetype="paladin", ally_hp=20) as f:
        registered(f)
        await swear(f.session)
        await character_spells.record_learned(f.hero, "arcane_bolt", "training", is_prepared=True, conn=world.pool)
        await f.round(goblin_strike(GOBLIN, f.hero), faces=(1,))
        state = f.session.combat_state
        spec = await load_creature_enemy("hollow_choir", encounter_id=f.combat_id, enemy_id=GOBLIN, role="standard")
        target = participant(state, GOBLIN)
        target.creature_id = "hollow_choir"
        target.choir_reaction = spec["choir_reaction"]
        packets = await f.round(ability(f.hero, "arcane_bolt", GOBLIN), faces=(1, 19))
        cast = next(p["cast"] for p in packets if p["actor_id"] == f.hero)
        assert cast["harmonic_shield_saves"][0]["oath_justice"]["source_id"] == GOBLIN
        attack_packet = cast["damage_result"]
        assert attack_packet["target_id"] == f.hero
        assert attack_packet["attack_total"] == 20
        assert attack_packet["oath_justice"]["target_id"] == f.hero
        assert attack_packet["oath_justice"]["modifier"] == 0
        assert participant(f.session.combat_state, GOBLIN).hp_current == 50
