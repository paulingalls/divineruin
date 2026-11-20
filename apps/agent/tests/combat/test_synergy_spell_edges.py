"""Patron spell edges through registered combat tools and persisted HP."""

from unittest.mock import patch

import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import attack, defend, game_tools
from acceptance._capstone_helpers import _d20, _damage_die
from combat.test_spell_damage_lands import load_combat, minimum_roll
from combat.test_synergy_crit_edges import dice_events, fight, saved_hp
from creature_combat_helpers import participant as creature_participant
from test_aelora_gift import _live_party
from voice_condition_fixtures import participant

import character_spells
from _gods_content import load_gods
from activate_tools import activate
from combat_turn import declare_phase, resolve_phase
from creature_combat_loader import load_creature_enemy
from query_tools import query_info

MYSTERIES = "veythar_simplest_mysteries"
FORMULA = "mortaen_ashen_formula"
MERCY = "mortaen_threshold_mercy"
FLAME = "divine_sacred_flame"


async def configure_caster(world, patron, archetype, spell, *, total=0):
    await configure(world, patron, archetype, level=1, resonance={"current": total})
    world.ctx.userdata.resonance.current = total
    if spell:
        await character_spells.record_learned(world.ids[0], spell, "training", is_prepared=True, conn=world.pool)


async def declare(world, state, spell):
    host = world.ids[0]
    call = game_tools(world.ctx.userdata, declare_phase, resolve_phase, activate)
    strike = {**defend(host), "kind": "ability", "action": spell, "targets": ["foe"]} if spell else attack(host, "foe")
    await call("declare_phase", declarations=[strike, *[defend(p.id) for p in state.participants if p.id != host]])
    return call


async def authored_clause(world, patron, archetype, kind, implementation, *, second_implementation=None):
    god = next(g for g in load_gods() if g["god_id"] == patron)
    row = god["layer_4_synergy_matrix"][archetype]
    reported = await game_tools(world.ctx.userdata, query_info)("query_info", kind="patron")
    assert reported["synergy"] == row
    assert row["type"] == kind
    expected = [("active", "engine", implementation)]
    if second_implementation is not None:
        expected.append(("active", "engine", second_implementation))
    assert [(c["status"], c["resolution"], c.get("implementation_id")) for c in row["clauses"]] == expected


async def veythar_cast(world, archetype, total, band, bonus, dc, *, spell="arcane_bolt"):
    await configure_caster(world, "veythar", archetype, spell, total=total)
    async with fight(world, ac=10) as state:
        caster = participant(state, world.ids[0])
        caster.level = 1
        caster.archetype_id = "whisper"
        call = await declare(world, state, spell)
        notation = f"{(3 if spell == 'arcane_fireball' else 1) + bonus}d6"
        with (
            patch("check_resolution.dice_roll", return_value=_d20(15 if spell == "arcane_bolt" else 1)),
            patch("check_resolution_attack.dice_roll", side_effect=minimum_roll) as attack_dice,
            patch("dice.roll", side_effect=lambda n, **kw: _d20(18) if n == "d20" else minimum_roll(n, **kw)) as dice,
        ):
            result = await call("resolve_phase")
        cast = result["packets"][0]["cast"]
        assert cast["state"] == band and cast["ward_active"] is False
        assert cast["resonance_modifiers"] == {"damage_dice": bonus, "dc": dc}
        if spell != "arcane_fireball":
            assert cast["damage_dice"] == notation
        rolls = attack_dice if spell == "arcane_bolt" else dice
        assert rolls.call_args.args[0] == notation
        assert await saved_hp(state) == 100 - minimum_roll(notation).total


VEYTHAR_CASES = [
    (archetype, total, band, bonus, dc)
    for archetype in ("mage", "artificer", "seeker")
    for total, band, bonus, dc in [(0, "stable", 2, 0), (5, "flickering", 2, 0), (9, "overreach", 4, 2)]
]


async def veythar_mysteries(world, archetype, total, band, bonus, dc):
    await veythar_cast(world, archetype, total, band, bonus, dc)
    await authored_clause(world, "veythar", archetype, "natural", MYSTERIES)


@pytest.mark.parametrize("archetype,spell", [("mage", "arcane_fireball"), ("cleric", "arcane_bolt"), ("mage", FLAME)])
async def test_veythar_cast_scope(world, archetype, spell):
    await veythar_cast(world, archetype, 0, "stable", 0, 0, spell=spell)


async def mortaen_attack(
    world, category, modifier, *, patron="mortaen", spell="arcane_bolt", held=False, archetype="mage"
):
    host, guest = world.ids
    session = world.ctx.userdata
    await configure_caster(world, patron, archetype, spell)
    if held:
        await configure(world, "zhael", "mage", index=1, patron_gifts={"zhael_lucky": {"spent": True}})
    lifecycle = _live_party(session, host, guest) if held else None
    try:
        async with fight(world, ac=10, ally=held) as state:
            participant(state, "foe").category = category
            call = await declare(world, state, spell)
            with (
                patch("check_resolution.dice_roll", return_value=_d20(15)) as d20s,
                patch("check_resolution_attack.dice_roll", return_value=_damage_die(5)) as damage,
            ):
                result = await call("resolve_phase")
                if held:
                    offer = result["fate_offer"]
                    assert (offer["roller_id"], offer["die"]) == (host, 15) and guest in offer["eligible_followers"]
                    assert not damage.called and await saved_hp(state) == 100
                    session.combat_state = await load_combat(state.combat_id)
                    assert lifecycle is not None
                    with session._bind_authenticated_actor(guest, 1, lifecycle.require_authorized):
                        result = await call(
                            "activate", id="zhael_fates_thread", offer_id=offer["offer_id"], keep="original"
                        )
                packet = next(p for p in result["packets"] if p["actor_id"] == host)
                result = packet["cast"]["damage_result"] if spell else packet
                assert dice_events(world)[-1]["modifier"] == modifier
                assert result["attack_total"] == 15 + modifier
                assert d20s.call_count == damage.call_count == 1
                assert result["damage"] == 5 and await saved_hp(state) == 95
                if spell:
                    assert result["damage_type"] == "force"
    finally:
        if lifecycle is not None:
            await lifecycle.aclose()


async def mortaen_formula(world):
    await mortaen_attack(world, "undead", 2)
    await authored_clause(world, "mortaen", "mage", "divine", FORMULA)


@pytest.mark.parametrize(
    "patron,category,spell,archetype",
    [
        ("mortaen", "beast", "arcane_bolt", "mage"),
        ("kaelen", "undead", "arcane_bolt", "mage"),
        ("mortaen", "undead", None, "mage"),
        # Threshold Mercy turns only Sacred Flame necrotic: a Mortaen cleric's other spells keep their type.
        ("mortaen", "beast", "arcane_bolt", "cleric"),
    ],
)
async def test_ashen_formula_scope(world, patron, category, spell, archetype):
    await mortaen_attack(world, category, 1, patron=patron, spell=spell, archetype=archetype)


async def test_ashen_formula_fate_hold(world):
    await mortaen_attack(world, "undead", 2, held=True)


async def sacred_flame(world, patron, *, veilrender=False):
    await configure_caster(world, patron, "cleric", FLAME)
    async with fight(world, ac=10) as state:
        foe = participant(state, "foe")
        foe.damage_affinities = {"resistant": ["necrotic"]}
        if veilrender:
            boss = await load_creature_enemy(
                "hollow_veilrender", encounter_id=state.combat_id, enemy_id="foe", role="standard"
            )
            state.participants[1] = creature_participant(boss)
            state.participants[1].hp_current = 100
            participant(state, world.ids[0]).veilrender_turn_round = state.round_number
        call = await declare(world, state, FLAME)
        with patch("check_resolution.dice_roll", return_value=_d20(1)), patch("dice.roll", return_value=_damage_die(5)):
            result = await call("resolve_phase")
        cast = result["packets"][0]["cast"]
        if veilrender:
            assert [entry["target_id"] for entry in cast["absorbed"]] == ["foe"]
            assert "damage_result" not in cast
            saved = await load_combat(state.combat_id)
            assert not participant(saved, "foe").radiant_suppression_pending
            assert participant(saved, "foe").hp_current == 100
        else:
            damage_type, hp_loss = ("necrotic", 2) if patron == "mortaen" else ("radiant", 5)
            damage = cast["damage_result"]
            assert damage["save"]["success"] is False
            assert damage["damage_type"] == damage_type
            assert damage["damage_components"] == [{"dice": "1d6", "damage_type": damage_type, "damage": hp_loss}]
            assert damage["damage"] == hp_loss and await saved_hp(state) == 100 - hp_loss


async def mortaen_mercy(world):
    await sacred_flame(world, "mortaen")
    await authored_clause(
        world, "mortaen", "cleric", "natural", MERCY, second_implementation="mortaen_threshold_healing"
    )
    await sacred_flame(world, "kaelen")


async def test_necrotic_flame_is_absorbed(world):
    await sacred_flame(world, "mortaen", veilrender=True)


SCENARIOS = {
    MYSTERIES: ("cast_modifiers:ward_combat_modifiers", veythar_mysteries, VEYTHAR_CASES),
    FORMULA: ("patron_synergy_combat:spell_attack_bonus", mortaen_formula, [()]),
    MERCY: ("spell_cast_effects:_finish_cast", mortaen_mercy, [()]),
}
