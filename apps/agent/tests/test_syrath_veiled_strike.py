"""Veiled strikes through registered activation and combat phase verbs."""

from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import attack, game_tools
from acceptance._capstone_helpers import _d20, _player_attack_events
from test_aelora_gift import _live_party
from test_encounter_facts_damage import GOBLIN, Fight
from test_syrath_two_round_veil import activate_veil, assert_flags, scene
from voice_condition_fixtures import participant, spatial_record

import character_spells
from _gods_content import load_gods
from activate_tools import activate
from combat_turn import resolve_phase

CLAUSE = "syrath_veiled_strike"


@contextmanager
def strike_dice(*faces: int) -> Iterator[list[str]]:
    notations: list[str] = []

    def damage_roll(notation: str, **_kwargs: object) -> SimpleNamespace:
        if notation == "d20":
            return _d20(18)
        notations.append(notation)
        count, sides = notation.split("d")
        return SimpleNamespace(total=int(count) * {"6": 2, "8": 3}[sides])

    with (
        patch("check_resolution.dice_roll", side_effect=[_d20(face) for face in faces]),
        patch("check_resolution_attack.dice_roll", side_effect=damage_roll),
        patch("dice.roll", side_effect=damage_roll),
    ):
        yield notations


async def setup_attacker(w: SimpleNamespace, archetype: str) -> None:
    await configure(
        w,
        "syrath",
        archetype,
        level=5,
        attributes={"strength": 10, "dexterity": 10, "intelligence": 10},
        resonance={"current": 0},
    )
    w.ctx.userdata.resonance.current = 0


async def assert_strike(
    f: Fight, result: dict, damage: list[int], clauses: list[str | None]
) -> tuple[list[dict], list[dict]]:
    packet = next(p for p in result["packets"] if p["actor_id"] == f.hero)
    swings = packet.get("attacks", [packet])
    assert [s["damage"] for s in swings] == damage
    assert packet["damage"] == sum(damage)
    assert [s.get("synergy_clause_id") for s in swings] == clauses
    assert packet.get("synergy_clause_id") == next((c for c in clauses if c), None)
    events = _player_attack_events(f.session.room)
    assert [e["damage"] for e in events] == damage
    assert [e.get("synergy_clause_id") for e in events] == clauses
    saved = await f.reload()
    assert participant(saved, GOBLIN).hp_current == 50 - sum(damage)
    assert saved.round_number == 1
    return swings, events


async def veiled_strike(w: SimpleNamespace, archetype: str) -> None:
    async with scene(w, archetype) as f:
        await setup_attacker(w, archetype)
        await activate_veil(w, f)
        await f.declare(attack(f.hero, GOBLIN))
        with strike_dice(15) as notations:
            result = await f.call("resolve_phase")
        rogue = archetype == "rogue"
        swings, events = await assert_strike(f, result, [9 if rogue else 5], [CLAUSE])
        assert notations == ["1d8", "3d6" if rogue else "1d6"]
        for receipt in [swings[0], events[0]]:
            if rogue:
                assert receipt["sneak_attack_dice"] == "3d6"
                assert receipt["sneak_attack_raw_damage"] == 6
                assert not receipt.get("synergy_damage")
            else:
                assert not receipt.get("sneak_attack_dice")
                assert (receipt["synergy_damage"], receipt["synergy_damage_type"]) == (2, "slashing")
        await assert_flags(w, False)

        authored = next(g for g in load_gods() if g["god_id"] == "syrath")["layer_4_synergy_matrix"][archetype]
        assert (await f.call("query_info", kind="patron"))["synergy"] == authored
        assert [(c["status"], c["resolution"], c.get("implementation_id")) for c in authored["clauses"]] == [
            ("active", "engine", "syrath_two_round_veil"),
            ("active", "engine", CLAUSE),
        ]


SCENARIOS = {CLAUSE: ("patron_synergy_combat:veiled_strike", veiled_strike, [("rogue",), ("spy",), ("whisper",)])}


@pytest.mark.parametrize("face", [15, 1])
async def test_only_first_swing_can_gain_veiled_damage(world: SimpleNamespace, face: int) -> None:
    async with scene(world, "spy", extra=True) as f:
        await setup_attacker(world, "spy")
        await activate_veil(world, f)
        await f.declare(attack(f.hero, GOBLIN))
        with strike_dice(face, 15) as notations:
            result = await f.call("resolve_phase")
        hit = face != 1
        swings, _ = await assert_strike(f, result, [5 if hit else 0, 3], [CLAUSE if hit else None, None])
        assert [s.get("synergy_damage") or 0 for s in swings] == [2 if hit else 0, 0]
        assert notations == (["1d8", "1d6", "1d8"] if hit else ["1d8"])
        await assert_flags(world, False)


@pytest.mark.parametrize("control", ["ordinary_hide", "warrior", "no_sneak_attack"])
async def test_weapon_exclusions(world: SimpleNamespace, control: str) -> None:
    archetype = "warrior" if control == "warrior" else "rogue"
    async with scene(world, archetype) as f:
        await setup_attacker(world, archetype)
        if control == "ordinary_hide":
            with strike_dice(20):
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
        else:
            await activate_veil(world, f, rounds=1 if archetype == "warrior" else 2)
            if control == "no_sneak_attack":
                spatial_record(f.session.combat_state)["positions"][f.ally]["x"] = 20
        await f.declare(attack(f.hero, GOBLIN))
        with strike_dice(15) as notations:
            result = await f.call("resolve_phase")
        hidden = control == "ordinary_hide"
        await assert_strike(f, result, [7 if hidden else 3], [None])
        assert notations == (["1d8", "2d6"] if hidden else ["1d8"])
        await assert_flags(world, False)


async def test_veiled_spy_spell_attack_has_only_spell_damage(world: SimpleNamespace) -> None:
    async with scene(world, "spy") as f:
        await setup_attacker(world, "spy")
        spell = "arcane_bolt"
        await character_spells.record_learned(f.hero, spell, "training", is_prepared=True, conn=world.pool)
        await activate_veil(world, f)
        await f.declare(
            {"kind": "ability", "actor_id": f.hero, "action": spell, "targets": [GOBLIN], "argument_type": ""}
        )
        with strike_dice(15) as notations:
            result = await f.call("resolve_phase")
        packet = next(p for p in result["packets"] if p["actor_id"] == f.hero)
        assert packet["cast"]["concealment"]["ended_by"] == "attack"
        assert "synergy_clause_id" not in packet["cast"]
        assert notations == ["2d6"]
        assert participant(await f.reload(), GOBLIN).hp_current == 46
        await assert_flags(world, False)


@pytest.mark.parametrize("archetype", ["rogue", "spy"])
async def test_critical_strike_doubles_veil_die(world: SimpleNamespace, archetype: str) -> None:
    async with scene(world, archetype) as f:
        await setup_attacker(world, archetype)
        await activate_veil(world, f)
        await f.declare(attack(f.hero, GOBLIN))
        with strike_dice(20) as notations:
            result = await f.call("resolve_phase")
        rogue = archetype == "rogue"
        swings, events = await assert_strike(f, result, [18 if rogue else 10], [CLAUSE])
        assert notations == ["1d8", "1d8", "6d6" if rogue else "2d6"]
        for receipt in [swings[0], events[0]]:
            assert receipt["critical"] is True
            if rogue:
                assert receipt["sneak_attack_raw_damage"] == 12
            else:
                assert receipt["synergy_damage"] == 4


@pytest.mark.parametrize("archetype", ["rogue", "spy"])
@pytest.mark.parametrize("keep", ["original", "reroll"])
async def test_fate_resumes_the_stored_veiled_strike(world: SimpleNamespace, archetype: str, keep: str) -> None:
    extra = archetype == "spy" and keep == "reroll"
    async with scene(world, archetype, extra=extra) as f:
        await setup_attacker(world, archetype)
        await configure(world, "zhael", "warrior", index=1, patron_gifts={"zhael_lucky": {"spent": True}})
        lifecycle = _live_party(f.session, f.hero, f.ally)
        try:
            await activate_veil(world, f)
            await f.declare(attack(f.hero, GOBLIN))
            rogue = archetype == "rogue"
            with strike_dice(15, 17, 16) as notations:
                offer = (await f.call("resolve_phase"))["fate_offer"]
                assert (offer["roller_id"], offer["die"]) == (f.hero, 15)
                assert f.ally in offer["eligible_followers"]
                held = await f.reload()
                assert participant(held, GOBLIN).hp_current == 50
                assert not notations and not _player_attack_events(f.session.room)
                assert held.ally_continuation is not None
                attacker_data = held.ally_continuation["attack"]["attacker_data"]
                assert attacker_data["veiled_strike"] == ("sneak_attack" if rogue else "weapon")
                await world.pool.execute(
                    """UPDATE players SET data=jsonb_set(data, '{flags}',
                    jsonb_set((data->'flags') - 'shadow_veil', '{concealed}', 'false'::jsonb))
                    WHERE player_id=$1""",
                    f.hero,
                )
                await assert_flags(world, False)
                call = game_tools(f.session, activate, resolve_phase)
                with f.session._bind_authenticated_actor(f.ally, 1, lifecycle.require_authorized):
                    choice = {"id": "zhael_fates_thread", "offer_id": offer["offer_id"]}
                    preview = await call("activate", **choice)
                    assert preview["reroll"]["die"] == 17
                    assert not notations
                    result = await call("activate", **choice, keep=keep)
            assert "fate_offer" not in result
            damage = [9 if rogue else 5]
            clauses: list[str | None] = [CLAUSE]
            if extra:
                damage.append(3)
                clauses.append(None)
            swings, events = await assert_strike(f, result, damage, clauses)
            assert events[0]["roll"] == (15 if keep == "original" else 17)
            if rogue:
                assert swings[0]["sneak_attack_dice"] == "3d6"
            assert f.session.combat_state.ally_continuation is None
        finally:
            await lifecycle.aclose()
