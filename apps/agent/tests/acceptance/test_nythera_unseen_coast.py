"""Saltwind Casting through registered combat tools and saved encounter state."""

from types import SimpleNamespace
from unittest.mock import patch

import asyncpg
import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import defend, game_tools
from acceptance._capstone_helpers import _d20, _damage_die
from combat.test_spell_damage_lands import load_combat
from combat.test_synergy_crit_edges import dice_events, fight, saved_hp
from combat.test_synergy_spell_edges import authored_clause, configure_caster, declare
from test_aelora_gift import _live_party
from voice_condition_fixtures import participant

import db
import db_mutations
from combat_turn import declare_phase, resolve_phase

CLAUSE = "nythera_saltwind_casting"
COAST = "accord_market_square"
BOLT = "arcane_bolt"
FIREBALL = "arcane_fireball"


@pytest.fixture
async def dev_db_pool(reset_db_pool: str) -> asyncpg.Pool:
    return await db.get_pool()


async def cast_at_location(
    world: SimpleNamespace,
    *,
    modifier: int = 2,
    location: str = COAST,
    revisited: bool = False,
    patron: str = "nythera",
    archetype: str = "mage",
    spell: str | None = BOLT,
    held: bool = False,
) -> None:
    host, guest = world.ids
    session = world.ctx.userdata
    session.location_id = location
    await configure_caster(world, patron, archetype, spell)
    await db_mutations.upsert_map_progress(host, location, [], conn=world.pool)
    if revisited:
        await db_mutations.upsert_map_progress(host, location, [], conn=world.pool)
    if held:
        await configure(world, "zhael", "mage", index=1, patron_gifts={"zhael_lucky": {"spent": True}})
    lifecycle = _live_party(session, host, guest) if held else None
    try:
        async with fight(world, ac=15, ally=held) as state:
            state.location_id = location
            original_attack_mod = participant(state, host).attack_mod
            call = await declare(world, state, spell)
            with (
                patch("check_resolution.dice_roll", return_value=_d20(15)) as d20s,
                patch("check_resolution_attack.dice_roll", return_value=_damage_die(5)) as attack_damage,
                patch("dice.roll", return_value=_damage_die(7)) as save_damage,
            ):
                result = await call("resolve_phase")
                if lifecycle is not None:
                    offer = result["fate_offer"]
                    assert (offer["roller_id"], offer["die"]) == (host, 15)
                    assert guest in offer["eligible_followers"]
                    assert not attack_damage.called and await saved_hp(state) == 100
                    session.combat_state = await load_combat(state.combat_id)
                    with session._bind_authenticated_actor(guest, 1, lifecycle.require_authorized):
                        result = await call(
                            "activate", id="zhael_fates_thread", offer_id=offer["offer_id"], keep="original"
                        )
            packet = next(p for p in result["packets"] if p["actor_id"] == host)
            cast = packet["cast"] if spell else {}
            damage = cast["damage_result"] if spell else packet
            if spell == FIREBALL:
                assert "spell_attack_bonus" not in cast
                assert not dice_events(world)
                assert (damage["save"]["dc"], damage["save"]["total"], damage["damage"]) == (9, 15, 3)
                assert save_damage.call_args.args[0] == "3d6"
                assert await saved_hp(state) == 97
                return
            assert damage["attack_total"] == 15 + modifier
            assert damage["target_ac"] == 17
            assert [event["modifier"] for event in dice_events(world)] == [modifier]
            hit = modifier == 2
            assert (damage["hit"], damage["damage"]) == (hit, 5 if hit else 0)
            assert d20s.call_count == 1 and attack_damage.call_count == int(hit)
            saved = await load_combat(state.combat_id)
            assert participant(saved, host).attack_mod == original_attack_mod
            assert participant(saved, "foe").hp_current == (95 if hit else 100)
            if hit:
                assert cast["spell_attack_bonus"] == {"id": CLAUSE, "name": "Saltwind Casting", "bonus": 1}
            else:
                assert "spell_attack_bonus" not in (cast if spell else packet)
    finally:
        if lifecycle is not None:
            await lifecycle.aclose()


async def saltwind_casting(world: SimpleNamespace) -> None:
    await cast_at_location(world)
    await authored_clause(world, "nythera", "mage", "divine", CLAUSE)


SCENARIOS = {CLAUSE: ("patron_synergy_combat:saltwind_casting_bonus", saltwind_casting, [()])}


async def test_first_stay_coastal_spell_attack(world: SimpleNamespace) -> None:
    await saltwind_casting(world)


@pytest.mark.parametrize(
    "options",
    [
        pytest.param({"revisited": True}, id="returning"),
        pytest.param({"location": "millhaven"}, id="inland"),
        pytest.param({"patron": "kaelen"}, id="another-patron"),
        pytest.param({"archetype": "cleric"}, id="another-archetype"),
        pytest.param({"spell": FIREBALL}, id="spell-save"),
        pytest.param({"spell": None}, id="weapon"),
    ],
)
async def test_saltwind_scope(world: SimpleNamespace, options: dict) -> None:
    await cast_at_location(world, modifier=1, **options)


async def test_fate_hold_preserves_saltwind_after_reload(world: SimpleNamespace) -> None:
    await cast_at_location(world, held=True)


async def test_produce_flame_for_light_has_no_attack_receipt(world: SimpleNamespace) -> None:
    spell = "primal_produce_flame"
    host = world.ids[0]
    session = world.ctx.userdata
    session.location_id = COAST
    await configure_caster(world, "nythera", "mage", spell)
    await db_mutations.upsert_map_progress(host, COAST, [], conn=world.pool)
    async with fight(world):
        call = game_tools(session, declare_phase, resolve_phase)
        await call("declare_phase", declarations=[{**defend(host), "kind": "ability", "action": spell}, defend("foe")])
        result = await call("resolve_phase")
        cast = next(packet["cast"] for packet in result["packets"] if packet["actor_id"] == host)
        assert "spell_attack_bonus" not in cast
        assert "damage_result" not in cast and not dice_events(world)
