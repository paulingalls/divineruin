"""Real casts cross the phase transaction and persist ordinary combat damage."""

from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from acceptance._capstone_helpers import _build_state, _d20, _enemy, _resolve_round
from acceptance.seeds import seed_player_with_pools
from sample_fixtures import make_context, make_mock_room
from voice_condition_fixtures import participant

import combat_turn
import db_mutations
import db_queries
import spells
from declaration_payloads import AbilityDecl, DefendDecl


async def saved_player(pid, *, conn=None):
    player = await db_queries.get_player(pid, conn=conn)
    assert player is not None
    return player


async def load_combat(combat_id, *, conn=None):
    state = await db_mutations.load_combat_state(combat_id, conn=conn)
    assert state is not None
    return state


@pytest.fixture
async def spell_fight(dev_db_pool):
    pool = dev_db_pool
    pid = f"spell_{uuid4().hex}"
    await seed_player_with_pools(
        pool,
        player_id=pid,
        class_="mage",
        known_spells=tuple(
            s.id for source in ("arcane", "divine", "primal") for s in spells.get_spells_by_source(source)
        ),
    )
    await pool.execute("UPDATE players SET data=jsonb_set(data,'{level}','8') WHERE player_id=$1", pid)
    ctx = make_context(pid, room=make_mock_room())
    state = _build_state(f"fight_{uuid4().hex}", pid, [_enemy("foe", 100)])
    state.terrain = "forest"
    participant(state, pid).level = 8
    participant(state, pid).attributes = {"intelligence": 18, "wisdom": 18}
    ctx.userdata.combat_state = state
    await db_mutations.save_combat_state(state.combat_id, state.to_dict(), conn=pool)
    try:
        yield ctx
    finally:
        await db_mutations.delete_combat_state(state.combat_id, conn=pool)
        await pool.execute("DELETE FROM players WHERE player_id=$1", pid)


async def declare_spell(ctx, spell_id="arcane_bolt", choice="", targets=None):
    await combat_turn.declare_phase(
        ctx,
        [
            AbilityDecl(
                kind="ability",
                actor_id=ctx.userdata.player_id,
                action=spell_id,
                targets=targets if targets is not None else ["foe"],
                argument_type=choice,
            ),
            DefendDecl(kind="defend", actor_id="foe"),
        ],
    )


@pytest.mark.parametrize("face,expected", [(15, 11), (1, 0)])
async def test_ordinary_bolt_hit_and_miss_persist_actual_damage(spell_fight, face, expected):
    ctx = spell_fight
    await declare_spell(ctx)
    with (
        patch("check_resolution.dice_roll", return_value=_d20(face)),
        patch("check_resolution_attack.dice_roll", return_value=SimpleNamespace(total=7)) as dice,
    ):
        result = await _resolve_round(ctx)
    packet = next(p for p in result["packets"] if p["actor_id"] == ctx.userdata.player_id)
    damage = packet["cast"]["damage_result"]
    assert (damage["hit"], damage["damage"], damage["damage_type"]) == (face != 1, expected, "force")
    assert damage["attack_total"] == face + 6
    if expected:
        assert dice.call_args.args[0] == "2d6"
    saved = await load_combat(ctx.userdata.combat_state.combat_id)
    assert participant(saved, "foe").hp_current == 100 - expected
    assert saved.to_dict() == ctx.userdata.combat_state.to_dict()


# Independent authored L8 totals with each die rolling 1, before cast-state modifiers.
DAMAGE_CASES = [
    ("arcane_frost_touch", 2, "cold"),
    ("arcane_spark", 2, "lightning"),
    ("arcane_magic_missile", 8, "force"),
    ("arcane_elemental_burst", 3, "cold"),
    ("arcane_fireball", 3, "fire"),
    ("arcane_lightning_bolt", 3, "lightning"),
    ("arcane_chain_lightning", 4, "lightning"),
    ("arcane_disintegrate", 25, "force"),
    ("arcane_meteor_swarm", 8, "fire"),
    ("divine_sacred_flame", 6, "radiant"),
    ("divine_sacred_word", 2, "radiant"),
    ("divine_flame_strike", 4, "fire"),
    ("divine_divine_judgment", 6, "radiant"),
    ("primal_thorn_whip", 6, "piercing"),
    ("primal_produce_flame", 2, "fire"),
    ("primal_call_lightning", 2, "lightning"),
    ("primal_blight", 4, "necrotic"),
    ("primal_ice_storm", 4, "bludgeoning"),
    ("primal_tsunami", 3, "bludgeoning"),
]


def minimum_roll(notation, **kwargs):
    import re

    match = re.fullmatch(r"(\d+)d\d+(?:\+(\d+))?", notation)
    return SimpleNamespace(total=sum(int(n or 0) for n in match.groups()) if match else int(notation))


async def prepare_spell(ctx, spell_id):
    import db

    spell = spells.get_spell(spell_id)
    cls = {"arcane": "mage", "divine": "cleric", "primal": "druid"}[spell.source]
    pool = await db.get_pool()
    await pool.execute(
        "UPDATE players SET data=jsonb_set(jsonb_set(data,'{class}',to_jsonb($2::text)),'{focus,current}','100') WHERE player_id=$1",
        ctx.userdata.player_id,
        cls,
    )
    return spell


@pytest.mark.parametrize("spell_id,base,damage_type", DAMAGE_CASES)
async def test_catalog_damage_lands_once_on_declared_recipient(spell_fight, spell_id, base, damage_type):

    ctx = spell_fight
    spell = await prepare_spell(ctx, spell_id)
    assert spell.combat_damage is not None
    participant(ctx.userdata.combat_state, "foe").category = "undead"
    before = await saved_player(ctx.userdata.player_id)
    await declare_spell(ctx, spell_id, "cold")
    with (
        patch(
            "check_resolution.dice_roll", return_value=_d20(15 if spell.combat_damage["resolution"] == "attack" else 1)
        ),
        patch("check_resolution_attack.dice_roll", side_effect=minimum_roll),
        patch("dice.roll", side_effect=minimum_roll),
    ):
        result = await _resolve_round(ctx)
    cast = next(p["cast"] for p in result["packets"] if p["actor_id"] == ctx.userdata.player_id)
    expected = base + cast["resonance_modifiers"]["damage_dice"]
    assert (cast["damage_result"]["damage"], cast["damage_result"]["damage_type"]) == (expected, damage_type)
    saved = await load_combat(ctx.userdata.combat_state.combat_id)
    assert participant(saved, "foe").hp_current == 100 - expected
    after = await saved_player(ctx.userdata.player_id)
    assert after["focus"]["current"] == before["focus"]["current"] - spell.focus_cost
    if spell.combat_damage.get("other_recipients"):
        assert any(d["not_affected"] and "NOT affected" in d["reason"] for d in cast["deferred"])


@pytest.mark.parametrize("spell_id,expected", [("arcane_fireball", 3), ("divine_sacred_flame", 0)])
async def test_successful_save_uses_authored_half_rule(spell_fight, spell_id, expected):
    ctx = spell_fight
    await prepare_spell(ctx, spell_id)
    await declare_spell(ctx, spell_id)
    with (
        patch("check_resolution.dice_roll", return_value=_d20(20)),
        patch("dice.roll", return_value=SimpleNamespace(total=7)),
    ):
        result = await _resolve_round(ctx)
    cast = next(p["cast"] for p in result["packets"] if p["actor_id"] == ctx.userdata.player_id)
    damage = cast["damage_result"]
    assert damage["save"]["success"] is True
    assert damage["damage"] == expected
    assert participant(ctx.userdata.combat_state, "foe").hp_current == 100 - expected


@pytest.mark.parametrize(
    "spell_id", ["divine_spiritual_weapon", "primal_wall_of_thorns", "primal_earthquake", "primal_storm_of_vengeance"]
)
async def test_event_spells_report_deferred_damage_and_spend_authored_focus(spell_fight, spell_id):

    ctx = spell_fight
    spell = await prepare_spell(ctx, spell_id)
    assert spell.combat_damage is not None
    await declare_spell(ctx, spell_id)
    result = await _resolve_round(ctx)
    cast = next(p["cast"] for p in result["packets"] if p["actor_id"] == ctx.userdata.player_id)
    assert "damage_result" not in cast
    assert cast["deferred"][0]["not_affected"] and cast["deferred"][0]["reason"]
    assert participant(ctx.userdata.combat_state, "foe").hp_current == 100
    assert (await saved_player(ctx.userdata.player_id))["focus"]["current"] == 100 - spell.focus_cost


async def test_area_spell_names_untouched_other_recipient(spell_fight):
    from voice_condition_fixtures import place_actors

    ctx = spell_fight
    await prepare_spell(ctx, "arcane_fireball")
    other = _enemy("other", 100)
    state = ctx.userdata.combat_state
    state.participants.append(other)
    state.initiative_order.append(other.id)
    place_actors(state)
    await declare_spell(ctx, "arcane_fireball")
    with patch("check_resolution.dice_roll", return_value=_d20(1)):
        result = await _resolve_round(ctx)
    cast = next(p["cast"] for p in result["packets"] if p["actor_id"] == ctx.userdata.player_id)
    assert cast["damage_result"]["damage"] > 0
    assert participant(state, "other").hp_current == 100
    deferred = next(d for d in cast["deferred"] if d["effect"] == "other_recipients")
    assert deferred["target_ids"] == ["other"] and deferred["targets"] == ["Other"] and deferred["not_affected"]


@pytest.mark.parametrize(
    "targets,choice", [([], "cold"), (["missing"], "cold"), (["foe", "other"], "cold"), (["foe"], "")]
)
async def test_invalid_damage_recipient_or_element_is_refused_before_writes(spell_fight, targets, choice):
    from livekit.agents.llm import ToolError

    ctx = spell_fight
    before = ctx.userdata.combat_state.to_dict()
    with pytest.raises(ToolError):
        await declare_spell(ctx, "arcane_elemental_burst", choice, targets)
    assert ctx.userdata.combat_state.to_dict() == before
    assert (await load_combat(before["combat_id"])).to_dict() == before


async def test_sacred_word_living_recipient_is_unharmed(spell_fight):
    ctx = spell_fight
    await prepare_spell(ctx, "divine_sacred_word")
    await declare_spell(ctx, "divine_sacred_word")
    result = await _resolve_round(ctx)
    cast = next(p["cast"] for p in result["packets"] if p["actor_id"] == ctx.userdata.player_id)
    assert cast["damage_result"]["damage"] == 0
    assert participant(ctx.userdata.combat_state, "foe").hp_current == 100


@pytest.mark.parametrize("level,notation", [(1, "1d4"), (5, "2d4"), (11, "3d4"), (17, "4d4")])
async def test_cantrip_scaling_retains_its_authored_die(spell_fight, level, notation):
    ctx = spell_fight
    import db

    participant(ctx.userdata.combat_state, ctx.userdata.player_id).level = level
    await (await db.get_pool()).execute(
        "UPDATE players SET data=jsonb_set(data,'{level}',to_jsonb($2::int)) WHERE player_id=$1",
        ctx.userdata.player_id,
        level,
    )
    await declare_spell(ctx, "arcane_spark")
    with (
        patch("check_resolution.dice_roll", return_value=_d20(15)),
        patch("check_resolution_attack.dice_roll", side_effect=minimum_roll) as rolled,
    ):
        result = await _resolve_round(ctx)
    cast = next(p["cast"] for p in result["packets"] if p["actor_id"] == ctx.userdata.player_id)
    assert cast["damage_dice"] == notation
    assert rolled.call_args.args[0] == notation


async def test_ward_reduces_cantrip_to_zero_dice_without_an_attribute_bonus(spell_fight):
    ctx = spell_fight
    ctx.userdata.combat_state.veil_ward = {"source": "test", "rounds_remaining": None}
    participant(ctx.userdata.combat_state, ctx.userdata.player_id).level = 1
    await declare_spell(ctx, "arcane_frost_touch")
    with patch("check_resolution.dice_roll", return_value=_d20(15)):
        result = await _resolve_round(ctx)
    cast = next(p["cast"] for p in result["packets"] if p["actor_id"] == ctx.userdata.player_id)
    assert cast["damage_result"]["hit"] and cast["damage_result"]["damage"] == 0
