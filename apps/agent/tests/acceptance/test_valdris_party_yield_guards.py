"""Exclusions for party surrender and Measured Reprisal."""

from types import SimpleNamespace

import asyncpg
import pytest
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import attack
from acceptance.test_valdris_party_yield import FACT, ability_action, hud_actor, registered, yield_action
from livekit.agents.llm import ToolError
from sample_fixtures import published_payloads
from test_encounter_facts_damage import GOBLIN, OTHER, fight, goblin_strike
from voice_condition_fixtures import participant

import character_spells
import db
import db_mutations


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
