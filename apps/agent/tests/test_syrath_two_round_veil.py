"""Shadow Veil duration at the registered combat and checkpoint boundaries."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import row
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import attack, game_tools
from acceptance.seeds import seed_known_spells
from test_encounter_facts_damage import GOBLIN, Fight, dice, fight

import db_mutations
import db_queries
from _gods_content import load_gods
from activate_tools import activate
from check_tools import check
from combat_end import end_combat
from combat_turn import declare_phase, resolve_phase
from query_tools import query_info

CLAUSE = "syrath_two_round_veil"
GIFT = "syrath_shadow_veil"
SPELL = "arcane_magic_missile"


def marker(rounds: int) -> dict:
    return {"remaining_rounds": rounds, "clause_id": CLAUSE}


@asynccontextmanager
async def scene(w: SimpleNamespace, archetype: str) -> AsyncIterator[Fight]:
    async with fight(w, "syrath", archetype=archetype, ally_hp=20) as f:
        f.call = game_tools(f.session, declare_phase, resolve_phase, activate, query_info, check, end_combat)
        await db_mutations.save_combat_state(f.combat_id, f.session.combat_state.to_dict())
        yield f


async def assert_flags(w: SimpleNamespace, lifetime: bool | dict, index: int = 0) -> None:
    player = await row(w, index)
    assert player["flags"]["concealed"] is bool(lifetime)
    assert player["flags"].get("shadow_veil", False) == lifetime
    assert ("shadow_veil" in player["flags"]) is bool(lifetime)


async def activate_veil(w: SimpleNamespace, f: Fight, rounds: int = 2, index: int = 0) -> None:
    info = await f.call("query_info", kind="patron")
    assert info["layer_1_gift"]["id"] == GIFT
    receipt = await f.call("activate", id=info["layer_1_gift"]["id"])
    await assert_flags(w, marker(2) if rounds == 2 else True, index)
    assert receipt == {
        "concealment": {
            "player_id": w.ids[index],
            "before": False,
            "concealed": True,
            "remaining_rounds": rounds,
            "clause_id": CLAUSE if rounds == 2 else None,
        },
        "expires_round": f.session.combat_state.round_number + rounds - 1,
    }
    assert (await row(w, index))["patron_gifts"][GIFT] == {"spent": True}


async def finish_round(w: SimpleNamespace, f: Fight, before: bool | dict, after: bool | dict) -> dict:
    round_number = f.session.combat_state.round_number
    for _ in range(5):
        result = await f.call("resolve_phase")
        state = await f.reload()
        if state.round_number != round_number:
            assert state.round_number == round_number + 1
            assert result["beat"] == "declaration"
            await assert_flags(w, after)
            return result
        await assert_flags(w, before)
        assert "shadow_veils" not in result
    raise AssertionError("round did not wrap")


def wrap_fact(f: Fight, rounds: int, clause: str | None = CLAUSE) -> list[dict]:
    return [
        {
            "player_id": f.hero,
            "before": True,
            "concealed": bool(rounds),
            "remaining_rounds": rounds,
            "clause_id": clause,
        }
    ]


async def two_round_veil(w: SimpleNamespace, archetype: str) -> None:
    authored = next(g for g in load_gods() if g["god_id"] == "syrath")["layer_4_synergy_matrix"][archetype]
    assert authored["clauses"] == [
        {
            "effect": "Shadow Veil extends to 2 rounds.",
            "status": "active",
            "resolution": "engine",
            "implementation_id": CLAUSE,
        },
        {"effect": "Invisible Sneak Attack +1d6", "status": "pending", "resolution": "engine"},
    ]
    async with scene(w, archetype) as f:
        assert (await f.call("query_info", kind="patron"))["synergy"] == authored
        await activate_veil(w, f)
        if archetype == "rogue":
            await configure(w, "syrath", "rogue", index=1)
            with f.session._bind_authenticated_actor(f.ally, 4, lambda *_: None), dice(20):
                result = await f.call(
                    "check",
                    roll={
                        "kind": "skill",
                        "skill": "stealth",
                        "difficulty": "easy",
                        "context_description": "Hide from the watcher",
                        "hearing_only": False,
                    },
                )
            assert result["concealment"]["concealed"] is True
        for before, after, rounds in [(marker(2), marker(1), 1), (marker(1), False, 0)]:
            await f.declare()
            result = await finish_round(w, f, before, after)
            assert result["shadow_veils"] == wrap_fact(f, rounds)
            if archetype == "rogue":
                assert (await row(w))["flags"] == {"concealed": True}
        assert (await row(w, 0))["patron_gifts"][GIFT] == {"spent": True}


SCENARIOS = {CLAUSE: ("patron_synergy_combat:shadow_veil_rounds", two_round_veil, [("rogue",), ("spy",), ("whisper",)])}


async def test_warrior_veil_ends_after_one_wrap(world: SimpleNamespace) -> None:
    async with scene(world, "warrior") as f:
        await activate_veil(world, f, rounds=1)
        await f.declare()
        result = await finish_round(world, f, True, False)
        assert result["shadow_veils"] == wrap_fact(f, 0, None)


async def test_legacy_rogue_veil_ends_after_one_wrap(world: SimpleNamespace) -> None:
    async with scene(world, "rogue") as f:
        await configure(world, "syrath", "rogue", flags={"concealed": True, "shadow_veil": True})
        await f.reload()
        await f.declare()
        result = await finish_round(world, f, True, False)
        assert result["shadow_veils"] == wrap_fact(f, 0, None)


async def test_guest_duration_uses_the_activators_player_row(world: SimpleNamespace) -> None:
    async with scene(world, "warrior") as f:
        await configure(world, "syrath", "rogue", index=1)
        f.session.party.members[1].patron_id = "thyra"
        f.session.combat_state.get_participant(f.ally).archetype_id = "warrior"
        before = await row(world, 0)
        with f.session._bind_authenticated_actor(f.ally, 4, lambda *_: None):
            await activate_veil(world, f, index=1)
        assert await row(world, 0) == before


@pytest.mark.parametrize("archetype,action", [("rogue", "attack"), ("whisper", "cast")])
async def test_second_round_action_ends_veil(world: SimpleNamespace, archetype: str, action: str) -> None:
    async with scene(world, archetype) as f:
        strike = attack(f.hero, GOBLIN)
        if action == "cast":
            await seed_known_spells(world.pool, f.hero, (SPELL,))
            strike = {"kind": "ability", "actor_id": f.hero, "action": SPELL, "targets": [GOBLIN], "argument_type": ""}
        await f.call("activate", id=GIFT)
        await f.declare()
        await finish_round(world, f, marker(2), marker(1))
        await f.declare(strike)
        with dice(1), patch("dice.roll", return_value=SimpleNamespace(total=3)):
            result = await f.call("resolve_phase")
        packet = next(p for p in result["packets"] if p["actor_id"] == f.hero)
        receipt = packet["cast"] if action == "cast" else packet
        assert receipt["concealment"]["ended_by"] == action
        assert (await f.reload()).round_number == 2
        await assert_flags(world, False)
        assert (await row(world, 0))["patron_gifts"][GIFT] == {"spent": True}


async def test_combat_end_clears_unspent_rounds(world: SimpleNamespace) -> None:
    async with scene(world, "rogue") as f:
        await f.call("activate", id=GIFT)
        await assert_flags(world, marker(2))
        await f.call("end_combat", outcome="fled")
        await assert_flags(world, False)
        assert await db_mutations.load_combat_state(f.combat_id) is None


async def test_failed_wrap_rolls_back_veil_tick_and_checkpoint(world: SimpleNamespace) -> None:
    async with scene(world, "rogue") as f:
        await f.call("activate", id=GIFT)
        await f.declare()
        await f.call("resolve_phase")
        checkpoint = (await f.reload()).to_dict()
        before = await row(world, 0)

        async def fail_save(_combat_id, _state, *, conn) -> None:
            player = await db_queries.get_player(f.hero, conn=conn)
            assert player is not None
            assert player["flags"]["shadow_veil"] == marker(1)
            raise RuntimeError("checkpoint unavailable")

        with patch.object(db_mutations, "save_combat_state", side_effect=fail_save):
            with pytest.raises(RuntimeError, match="checkpoint unavailable"):
                await f.call("resolve_phase")
        assert await row(world, 0) == before
        assert (await f.reload()).to_dict() == checkpoint
        result = await finish_round(world, f, marker(2), marker(1))
        assert result["shadow_veils"] == wrap_fact(f, 1)
