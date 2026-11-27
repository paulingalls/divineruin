"""Exclusions for party surrender and Measured Reprisal."""

from types import SimpleNamespace
from unittest.mock import patch

import asyncpg
import pytest
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import attack
from acceptance import test_architect_entomb, test_opportunity_strike
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_architect_fight import isolated_content_cache as isolated_content_cache
from acceptance.test_opportunity_strike import MOVER
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_valdris_party_yield import FACT, ability_action, hud_actor, registered, yield_action
from livekit.agents.llm import ToolError
from sample_fixtures import published_payloads
from test_encounter_facts_damage import GOBLIN, OTHER, fight, goblin_strike
from voice_condition_fixtures import participant

import character_spells
import conditions
import db
import db_mutations

grapple_fight = test_opportunity_strike.fight
entomb_fight = test_architect_entomb.fight


@pytest.fixture
async def dev_db_pool(reset_db_pool: str) -> asyncpg.Pool:
    return await db.get_pool()


async def test_only_attempts_on_currently_yielded_allies_count(world: SimpleNamespace) -> None:
    async with fight(world, "valdris", ally_hp=20) as f:
        registered(f)
        for target in (GOBLIN, OTHER):
            participant(f.session.combat_state, target).creature_id = "goblin"
        await f.round(goblin_strike(OTHER, f.ally), faces=(2,))
        assert (await f.reload()).encounter_facts[FACT] == []
        await f.round(yield_action(f.ally), goblin_strike(GOBLIN, f.ally), faces=(2,))
        packets = await f.round(attack(f.ally, GOBLIN), goblin_strike(OTHER, f.ally), faces=(2, 2))
        assert next(p for p in packets if p["actor_id"] == f.ally)["yield_ended"]
        assert (await f.reload()).encounter_facts[FACT] == [GOBLIN]
        await f.hit(None, OTHER)


@pytest.mark.parametrize(("patron", "archetype"), [("thyra", "warrior"), ("valdris", "mage")])
async def test_ineligible_hero_gains_no_damage(world: SimpleNamespace, patron: str, archetype: str) -> None:
    async with fight(world, patron, archetype=archetype, ally_hp=20) as f:
        registered(f)
        await f.round(yield_action(f.hero), goblin_strike(GOBLIN, f.hero), faces=(2,))
        assert (await f.reload()).encounter_facts[FACT] == [GOBLIN]
        await f.hit(None)


async def test_nonhostile_cast_preserves_yield(world: SimpleNamespace) -> None:
    async with fight(world, "valdris", archetype="mage") as f:
        registered(f)
        spell = "arcane_haste"
        await character_spells.record_learned(f.hero, spell, "training", is_prepared=True, conn=world.pool)
        await f.round(yield_action(f.hero), faces=())
        packets = await f.round(ability_action(f.hero, spell), faces=())
        receipt = next(p for p in packets if p["actor_id"] == f.hero)
        assert receipt["resolved"] is True and receipt["action"] == spell and receipt["cast"]["effect"]
        assert f.session.concentration.spell_id == spell and "yield_ended" not in receipt
        assert participant(await f.reload(), f.hero).yielded and hud_actor(f, f.hero)["yielded"]


async def test_refused_yield_and_stale_attack_preserve_state(world: SimpleNamespace) -> None:
    async with fight(world, "valdris") as f:
        registered(f)
        await f.round(yield_action(f.hero), faces=())
        before = (await f.reload()).to_dict()
        events = published_payloads(f.session.room)
        with pytest.raises(ToolError, match="Only players and companions"):
            await f.declare(yield_action(GOBLIN))
        with pytest.raises(ToolError, match="Unknown target"):
            await f.declare(attack(f.hero, "absent"))
        assert (await f.reload()).to_dict() == before
        assert published_payloads(f.session.room) == events

        await f.declare(attack(f.hero, GOBLIN))
        state = await f.reload()
        participant(state, f.hero).action_pool.clear()
        await db_mutations.save_combat_state(f.combat_id, state.to_dict())
        await f.reload()
        packets = (await f.call("resolve_phase"))["packets"]
        receipt = next(p for p in packets if p["actor_id"] == f.hero)
        assert receipt["resolved"] is False and "hit" not in receipt
        assert participant(await f.reload(), f.hero).yielded and hud_actor(f, f.hero)["yielded"]


@pytest.mark.parametrize("bad", [None, 1, "false"])
async def test_malformed_yield_checkpoint_is_refused(world: SimpleNamespace, bad: object) -> None:
    async with fight(world, "valdris") as f:
        data = f.session.combat_state.to_dict()
        data["participants"][0]["yielded"] = bad
        await db_mutations.save_combat_state(f.combat_id, data)
        with pytest.raises(ValueError, match="yielded must be a boolean"):
            await f.reload()


async def yielded_escape(fight: MawlingHarness, actor: str, source: str) -> dict:
    await fight.command("declare_phase", {"declarations": [yield_action(actor)]})
    with patch("combat_turn_start.dice_roll", return_value=SimpleNamespace(total=1)):
        await fight.drain()
    assert participant(await fight.reload(), actor).yielded
    escape = {"reshape": [], "kind": "maneuver", "actor_id": actor, "target_id": source}
    await fight.command("declare_phase", {"declarations": [escape]})
    with (
        patch("combat_maneuver.random", SimpleNamespace(randint=lambda *_: 1)),
        patch("combat_turn_start.dice_roll", return_value=SimpleNamespace(total=1)),
    ):
        receipt = next(p for p in await fight.drain() if p["actor_id"] == actor)
    assert receipt["escape"] == "failed"
    return receipt


@pytest.mark.parametrize("grapple_fight", ["hollow_mawling"], indirect=True)
async def test_failed_grapple_escape_from_a_foe_ends_yield(grapple_fight: MawlingHarness) -> None:
    warrior = grapple_fight.players[0]
    state = await grapple_fight.reload()
    hero = participant(state, warrior)
    hero.conditions = conditions.apply_condition(hero.conditions, "grappled", source=MOVER)
    await grapple_fight.persist()
    receipt = await yielded_escape(grapple_fight, warrior, MOVER)
    assert (receipt["yield_ended"], receipt["yielded"]) == (True, False) and receipt["dm_cue"]
    assert not participant(await grapple_fight.reload(), warrior).yielded


async def test_failed_entomb_chamber_escape_keeps_yield(entomb_fight: MawlingHarness) -> None:
    _, victim, chamber = await test_architect_entomb.seal(entomb_fight)
    receipt = await yielded_escape(entomb_fight, victim, chamber)
    assert not {"yield_ended", "yielded", "dm_cue"} & receipt.keys()
    assert participant(await entomb_fight.reload(), victim).yielded
