"""Restoring Guard through registered reaction tools and persisted combat."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import patch

import asyncpg
import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import row
from _unbound_path_fixtures import world as world
from livekit.agents.llm import ToolError
from test_aelora_gift import _live_party
from test_encounter_facts_damage import GOBLIN, Fight, dice, fight, goblin_strike
from voice_condition_fixtures import participant, spatial_record

import db
import db_mutations
import db_mutations_concentration
import db_queries
from combat_init_participants import class_reaction_ids

CLAUSE = "aelora_restoring_guard"
INTERCEPT = "guardian_intercept"
BARK_SKIN = "warden_bark_skin"
FATE = "zhael_fates_thread"
SPELL = "arcane_haste"


@pytest.fixture
async def dev_db_pool(reset_db_pool: str) -> asyncpg.Pool:
    return await db.get_pool()


@asynccontextmanager
async def guard_fight(
    world: SimpleNamespace, archetype: str, start: int, *, patron: str = "aelora", case: str = "applied"
) -> AsyncIterator[Fight]:
    async with fight(world, patron, archetype=archetype, ally_hp=20) as f:
        await configure(
            world,
            patron,
            archetype,
            level=6,
            hp={"current": 100, "max": 100},
            stamina={"current": start, "max": 10},
            focus={"current": 5, "max": 5},
        )
        state = f.session.combat_state
        hero = participant(state, f.hero)
        hero.level = 6
        hero.reaction_ids = class_reaction_ids(archetype, 6)
        hero.has_reaction_ability = True
        spatial_record(state)["positions"][f.hero]["x"] = 6 if case == "range" else 5
        if case == "range":
            await configure(world, "thyra", "warden", index=1, level=6)
            ally = participant(state, f.ally)
            ally.reaction_ids = class_reaction_ids("warden", 6)
            ally.has_reaction_ability = True
        if case == "immune":
            hero.damage_affinities = {"immune": ["slashing"]}
        if case == "fate":
            await configure(world, "zhael", "warrior", index=1, patron_gifts={"zhael_lucky": {"spent": True}})
            f.session.member_state(f.hero).concentration.spell_id = SPELL
            await db_mutations_concentration.update_player_concentration(f.hero, SPELL, conn=world.pool)
        await db_mutations.save_combat_state(f.combat_id, state.to_dict())
        await f.reload()
        await f.declare(goblin_strike(GOBLIN, f.ally if archetype == "guardian" else f.hero))
        lifecycle = _live_party(f.session, *world.ids) if case == "fate" else None
        try:
            yield f
        finally:
            if lifecycle is not None:
                await lifecycle.aclose()


async def window(f: Fight, *, offered: str | None) -> dict:
    for _ in range(4):
        result = await f.call("resolve_phase")
        if offer := result.get("fate_offer"):
            result = await keep_original(f, offer)
        if waiting := result["next"]["waiting_on"]:
            assert waiting["stage"] == "post_roll"
            ids = {reaction["id"] for reaction in waiting["reactions"]}
            if offered is None:
                assert INTERCEPT not in ids
            else:
                assert offered in ids
            await f.reload()
            return waiting
    raise AssertionError("No protective window opened")


async def keep_original(f: Fight, offer: dict) -> dict:
    with f.session._bind_authenticated_actor(f.ally, 1, f.session.multiplayer_owner.lifecycle.require_authorized):
        return await f.call("activate", id=FATE, offer_id=offer["offer_id"], keep="original")


async def spend(f: Fight, ability: str) -> None:
    with f.session._bind_authenticated_actor(f.hero, 1, lambda *_: None):
        await f.call("activate", id=ability)
    await f.reload()


def reaction(packets: list[dict], ability: str) -> dict:
    (packet,) = [p for p in packets if p.get("ability_id") == ability]
    return packet


def receipt(gain: int) -> dict:
    return {"id": CLAUSE, "name": "Restoring Guard", "stamina_restored": gain}


async def guardian(world: SimpleNamespace, case: str) -> None:
    patron = "kaelen" if case == "other_patron" else "aelora"
    async with guard_fight(world, "guardian", 5, patron=patron, case=case) as f:
        with dice(17):
            await window(f, offered=None if case == "range" else INTERCEPT)
            if case == "range":
                with pytest.raises(ToolError, match="within 5 ft"):
                    await spend(f, INTERCEPT)
            else:
                await spend(f, INTERCEPT)
            assert (await row(world, 0))["stamina"]["current"] == (5 if case == "range" else 2)
            packets = (await f.call("resolve_phase"))["packets"]
            (hit,) = [p for p in packets if p["actor_id"] == GOBLIN and "hit" in p]
            damage = 0 if case == "immune" else 5
            assert hit["damage"] == damage
            assert hit.get("damage_target_id") == (None if case == "range" else f.hero)
            assert (await row(world, 1))["hp"]["current"] == (15 if case == "range" else 20)
            assert (await row(world, 0))["hp"]["current"] == (100 if case == "range" else 100 - damage)
            assert (await row(world, 0))["stamina"]["current"] == {"applied": 4, "range": 5}.get(case, 2)
            if case == "applied":
                packet = reaction(packets, INTERCEPT)
                assert packet["mechanical_effect"] == "damage_intercepted"
                assert packet["restoring_guard"] == receipt(2)
            else:
                assert all("restoring_guard" not in packet for packet in packets)


async def warden(world: SimpleNamespace, start: int, *, case: str = "applied") -> None:
    hit = case == "fate"
    async with guard_fight(world, "warden", start, case=case) as f:
        with dice(18, 7) if hit else dice(16):
            await window(f, offered=BARK_SKIN)
            await spend(f, BARK_SKIN)
            assert (await row(world, 0))["stamina"]["current"] == start
            assert (await row(world, 0))["focus"]["current"] == 3
            result = await f.call("resolve_phase")
            end = min(start + 2, 10)
            assert (await row(world, 0))["stamina"]["current"] == end
            if hit:
                offer = result["fate_offer"]
                assert (offer["roller_id"], offer["roll_kind"]) == (f.hero, "save")
                saved = (await f.reload()).held_actions[0]["pending_reaction_packets"]
                assert reaction(saved, BARK_SKIN)["restoring_guard"] == receipt(end - start)
                result = await keep_original(f, offer)
            packets = result["packets"]
        (attack,) = [p for p in packets if p["actor_id"] == GOBLIN and "hit" in p]
        assert (attack["hit"], attack["damage"], attack["target_ac"]) == (hit, 5 if hit else 0, 18)
        packet = reaction(packets, BARK_SKIN)
        assert packet["mechanical_effect"] == "round_ac_bonus"
        assert packet["restoring_guard"] == receipt(end - start)
        player = await row(world, 0)
        assert (player["stamina"]["current"], player["focus"]["current"]) == (end, 3)


async def restoring_guard(world: SimpleNamespace, archetype: str) -> None:
    if archetype == "guardian":
        await guardian(world, "applied")
    else:
        await warden(world, 5)


SCENARIOS = {CLAUSE: ("patron_synergy_combat:restore_guard_stamina", restoring_guard, [("guardian",), ("warden",)])}


@pytest.mark.parametrize("archetype", ["guardian", "warden"])
async def test_restoring_guard(world: SimpleNamespace, archetype: str) -> None:
    await restoring_guard(world, archetype)


@pytest.mark.parametrize("case", ["range", "immune", "other_patron"])
async def test_excluded_intercept(world: SimpleNamespace, case: str) -> None:
    await guardian(world, case)


@pytest.mark.parametrize("start", [9, 10])
async def test_bark_skin_cap(world: SimpleNamespace, start: int) -> None:
    await warden(world, start)


async def test_bark_skin_reload(world: SimpleNamespace) -> None:
    await warden(world, 5, case="fate")


async def test_bark_skin_refund_rolls_back_at_checkpoint(world: SimpleNamespace) -> None:
    async with guard_fight(world, "warden", 5) as f:
        with dice(16):
            await window(f, offered=BARK_SKIN)
            await spend(f, BARK_SKIN)
            committed = (await f.reload()).to_dict()

            async def fail_checkpoint(combat_id: str, state: dict, *, conn: asyncpg.Connection) -> None:
                player = await db_queries.get_player(f.hero, conn=conn)
                assert player is not None and player["stamina"]["current"] == 7
                raise RuntimeError("checkpoint failed")

            with (
                patch.object(db_mutations, "save_combat_state", side_effect=fail_checkpoint),
                pytest.raises(RuntimeError, match="checkpoint failed"),
            ):
                await f.call("resolve_phase")

            player = await row(world, 0)
            assert (player["stamina"]["current"], player["focus"]["current"]) == (5, 3)
            assert (await f.reload()).to_dict() == committed
            result = await f.call("resolve_phase")
            assert reaction(result["packets"], BARK_SKIN)["restoring_guard"] == receipt(2)
            player = await row(world, 0)
            assert (player["stamina"]["current"], player["focus"]["current"]) == (7, 3)
