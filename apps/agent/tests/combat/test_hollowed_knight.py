"""Knight catalog mechanics at validation and combat boundaries."""

import copy
import json
from pathlib import Path

import pytest
from combat.test_damage_affinity import catalog_fight as catalog_fight
from combat.test_damage_affinity import declare_weapon, resolve
from combat.test_damage_affinity import spell_fight as spell_fight
from combat.test_spell_damage_lands import load_combat
from voice_condition_fixtures import participant

from creature_combat import translate_creature
from creature_schema import validate_creature_stat_block

CATALOG = Path(__file__).parents[4] / "content/creatures.json"


def knight():
    return next(row for row in json.loads(CATALOG.read_text()) if row["id"] == "hollow_knight")


def test_knight_authored_mechanics():
    row = knight()
    assert validate_creature_stat_block(row) == []
    enemy = translate_creature(row, encounter_id="knight", enemy_id="knight", role="boss")
    assert enemy["unholy_fortitude"]["dc"] == 10
    assert enemy["resist_nonmagical_physical"] is True
    assert enemy["multiattack_sequence"]["attacks"] == ["Corrupted Blade"] * 2
    blade = enemy["action_pool"][0]
    assert blade["bonus_damage"] == {"dice": "1d6", "damage_type": "necrotic"}
    assert blade["critical_save"] == {"save": "CON", "dc": 14, "applies_condition": "hollowed"}
    assert {r["id"] for r in json.loads(CATALOG.read_text()) if r.get("resist_nonmagical_physical")} == {
        "hollow_knight",
        "war_golem",
        "deepstone_guardian",
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("resist_nonmagical_physical", "yes"),
        ("unholy_fortitude", {"save": "CON", "dc": 0, "increment": 5, "narration_cue": "rise"}),
        ("unholy_fortitude", {"save": "bad", "dc": 10, "increment": 5, "narration_cue": "rise"}),
        ("unholy_fortitude", {"save": "CON", "dc": 10, "increment": 0, "narration_cue": "rise"}),
        ("unholy_fortitude", {"dc": 10, "increment": 5, "narration_cue": "rise"}),
    ],
)
def test_knight_contract_rejects_malformed(field, value):
    row = copy.deepcopy(knight())
    row[field] = value
    assert any(field in error for error in validate_creature_stat_block(row))


@pytest.mark.parametrize("seed,ac,critical", [(0, 10, False), (2, 50, False), (5, 10, True)])
async def test_blade_packets(seed, ac, critical):
    from combat._catalog_fixtures import deps, setup
    from sample_fixtures import make_context

    from combat_packet import _resolve_one_packet

    enemy = translate_creature(knight(), encounter_id="knight", enemy_id="knight", role="standard")
    state, actor, packet = setup(enemy["action_pool"][0])
    target = state.participants[0]
    target.ac = ac
    target.hp_current = target.hp_max = 100
    actor.attributes = enemy["attributes"]
    import random
    from unittest.mock import patch

    with patch("dice.random.SystemRandom", return_value=random.Random(5)):
        result = await _resolve_one_packet(make_context().userdata, state, packet, **deps(seed))
    assert result["critical"] is critical
    assert ("critical_save" in result) is critical
    assert target.hp_current == 100 - result["damage"]
    assert not target.conditions
    if critical:
        assert result["critical_save"]["success"] is True
        assert result["critical_save"]["dc"] == 14


@pytest.mark.parametrize("creature", ["hollow_knight", "war_golem", "deepstone_guardian"])
@pytest.mark.parametrize("dtype", ["slashing", "piercing", "bludgeoning"])
@pytest.mark.parametrize("magical", [False, True])
async def test_equipment_origin_controls_physical_resistance(catalog_fight, creature, dtype, magical):
    ctx = await catalog_fight(
        creature, {"name": "Longsword", "damage": "1d8", "damage_type": dtype, "magical": magical}
    )
    state = ctx.userdata.combat_state
    actor = participant(state, ctx.userdata.player_id)
    target = participant(state, "foe")
    assert actor.action_pool[0]["magical"] is magical
    assert target.resist_nonmagical_physical is True
    hp = target.hp_current
    await declare_weapon(ctx)
    result = await resolve(ctx, raw=9, face=19)
    expected = 9 if magical else 4
    assert result["damage"] == expected
    saved = await load_combat(state.combat_id)
    assert participant(saved, "foe").hp_current == hp - expected


@pytest.mark.parametrize(
    "field,value",
    [
        ("magical", "yes"),
        ("bonus_damage", {"dice": "oops", "damage_type": "necrotic"}),
        ("bonus_damage", {"dice": "1d6", "damage_type": "oops"}),
        ("bonus_damage", {"dice": "1d6"}),
        ("bonus_damage", {"dice": "1d6", "damage_type": "necrotic", "extra": True}),
        ("critical_save", {"save": "BAD", "dc": 14, "applies_condition": "hollowed"}),
        ("critical_save", {"save": "CON", "dc": 0, "applies_condition": "hollowed"}),
        ("critical_save", {"save": "CON", "dc": 14, "applies_condition": "unknown"}),
    ],
)
def test_blade_contract_rejects_malformed(field, value):
    row = knight()
    row["attacks"][0][field] = value
    assert any(field in error for error in validate_creature_stat_block(row))


@pytest.mark.parametrize(
    "trait,halved", [("resistant", False), ("immune", False), ("resistant", True), ("all_immune", False)]
)
async def test_dissolution_typed_damage_and_reaction(trait, halved):
    from combat._catalog_fixtures import deps, setup
    from sample_fixtures import make_context

    from combat_packet import _resolve_one_packet
    from combat_reaction_effect import halve
    from combat_support import apply_attack_result, deserialize_roll, roll_attack, serialize_roll
    from declarations import Declaration, DeclarationType

    enemy = translate_creature(knight(), encounter_id="k", enemy_id="k", role="standard")
    preparation = next(a for a in enemy["action_pool"] if a["name"] == "Dissolution Strike")
    state, actor, packet = setup(preparation)
    actor.action_pool.append(enemy["action_pool"][0])
    packet.declaration = Declaration(type=DeclarationType.ABILITY, action=preparation["name"])
    session = make_context().userdata
    await _resolve_one_packet(session, state, packet, **deps())
    target = state.participants[0]
    target.hp_current = target.hp_max = 100
    target.damage_affinities = {trait: ["necrotic"]} if trait != "all_immune" else {"immune": ["necrotic", "slashing"]}
    packet.declaration = Declaration(type=DeclarationType.ATTACK, action="Corrupted Blade", target_id=target.id)
    if halved:
        from combat_action_availability import begin_execution

        action = begin_execution(state, actor, actor.action_pool[1], packet.declaration)
        roll, ac = roll_attack(actor, action, target, resolver=deps()["resolver"], combat_state=state)
        head = {"roll": serialize_roll(roll, ac)}
        halve(head, target)
        result, ac = deserialize_roll(head["roll"])
        landing_deps = deps()
        landing_deps.pop("resolver")
        summary = await apply_attack_result(
            session, actor, action, target, result, ac, combat_state=state, **landing_deps
        )
        base = (roll.damage // 2) - roll.bonus_damage // 2 - roll.rider_damage // 2
        assert summary["damage"] == base + roll.bonus_damage // 2 // 2 + roll.rider_damage // 2
    else:
        summary = await _resolve_one_packet(session, state, packet, **deps())
    if not halved:
        assert summary["bonus_damage"] == 0
        assert summary["rider_damage"] == (12 if trait == "resistant" else 0)
        assert summary["damage"] == (23 if trait == "resistant" else 0 if trait == "all_immune" else 11)
    assert summary["rider_damage_type"] == "necrotic"
    assert summary["rider_ignores_resistance"] is True
    assert (summary["rider_damage"] > 0) is (trait == "resistant")
    assert target.hp_current == 100 - summary["damage"]
    assert actor.pending_preparation is None


async def test_physical_spell_has_magical_origin(catalog_fight):
    from combat.test_spell_damage_lands import declare_spell, prepare_spell

    ctx = await catalog_fight("war_golem")
    target = participant(ctx.userdata.combat_state, "foe")
    hp = target.hp_current
    await prepare_spell(ctx, "primal_thorn_whip")
    await declare_spell(ctx, "primal_thorn_whip")
    result = await resolve(ctx, raw=9, face=19)
    damage = result["cast"]["damage_result"]
    assert damage["damage"] == 9
    saved = await load_combat(ctx.userdata.combat_state.combat_id)
    assert participant(saved, "foe").hp_current == hp - 9


@pytest.mark.parametrize("spell", ["arcane_elemental_burst", "arcane_magic_missile"])
async def test_fortitude_from_save_and_automatic_damage(catalog_fight, spell):
    from combat.test_spell_damage_lands import declare_spell, prepare_spell

    ctx = await catalog_fight("hollow_knight")
    await prepare_spell(ctx, spell)
    await declare_spell(ctx, spell, "fire" if spell == "arcane_elemental_burst" else "")
    result = await resolve(ctx, raw=100, face=8)
    damage = result["cast"]["damage_result"]
    assert damage["unholy_fortitude"]["dc"] == 10
    assert damage["unholy_fortitude"]["success"] is True
    state = await load_combat(ctx.userdata.combat_state.combat_id)
    target = participant(state, "foe")
    assert target.unholy_fortitude is not None
    assert target.hp_current == 1 and target.unholy_fortitude["dc"] == 15
    assert not target.hollow_death_resolved and not target.is_fallen


async def test_dissolution_miss_retains_rider_and_catalog_recharges():
    import random
    from unittest.mock import patch

    from combat._catalog_fixtures import deps, setup, wrap
    from sample_fixtures import make_context

    import dice
    from combat_packet import _resolve_one_packet
    from declarations import Declaration, DeclarationType

    enemy = translate_creature(knight(), encounter_id="k", enemy_id="k", role="standard")
    preparation = next(a for a in enemy["action_pool"] if a["name"] == "Dissolution Strike")
    state, actor, packet = setup(preparation)
    actor.action_pool.append(enemy["action_pool"][0])
    packet.declaration = Declaration(type=DeclarationType.ABILITY, action=preparation["name"])
    session = make_context().userdata
    await _resolve_one_packet(session, state, packet, **deps())
    assert actor.action_ledger["dissolution strike"]["remaining"] == 0
    target = state.participants[0]
    target.ac = 50
    packet.declaration = Declaration(type=DeclarationType.ATTACK, action="Corrupted Blade", target_id=target.id)
    missed = await _resolve_one_packet(session, state, packet, **deps())
    assert not missed["hit"] and missed["rider_damage"] == 0
    assert actor.pending_preparation is not None
    target.ac = 10
    hit = await _resolve_one_packet(session, state, packet, **deps())
    assert hit["rider_damage"] > 0 and actor.pending_preparation is None
    next_hit = await _resolve_one_packet(session, state, packet, **deps())
    assert next_hit["rider_damage"] == 0
    for seed, expected in [(0, 0), (5, 1)]:
        rng = random.Random(seed)
        with patch("combat_recharge.roll", side_effect=lambda expr, rng=rng: dice.roll(expr, rng=rng)):
            state = await wrap(state)
        assert state.get_participant(actor.id).action_ledger["dissolution strike"]["remaining"] == expected


@pytest.mark.parametrize(
    "rider",
    [
        {"damage": "bad", "damage_type": "necrotic", "ignores_resistance": True},
        {"damage": "3d6", "damage_type": "bad", "ignores_resistance": True},
        {"damage": "3d6", "ignores_resistance": True},
        {"damage": "3d6", "damage_type": "necrotic", "ignores_resistance": False},
        {"damage": "3d6", "damage_type": "necrotic", "ignores_resistance": True, "extra": True},
    ],
)
def test_dissolution_rejects_malformed_damage_form(rider):
    row = knight()
    next(a for a in row["actives"] if a["name"] == "Dissolution Strike")["on_hit"] = rider
    assert any("on_hit" in error for error in validate_creature_stat_block(row))


async def test_blade_critical_escalates_existing_hollowed():
    import random
    from unittest.mock import patch

    from combat._catalog_fixtures import deps, setup
    from sample_fixtures import make_context

    import conditions
    from combat_packet import _resolve_one_packet

    enemy = translate_creature(knight(), encounter_id="k", enemy_id="k", role="standard")
    state, _actor, packet = setup(enemy["action_pool"][0])
    target = state.participants[0]
    target.hp_current = target.hp_max = 100
    target.conditions = conditions.apply_condition([], "hollowed")
    with patch("dice.random.SystemRandom", return_value=random.Random(1)):
        result = await _resolve_one_packet(make_context().userdata, state, packet, **deps(5))
    assert result["critical_save"]["success"] is False
    assert conditions.hollowed_stage(target.conditions) == 2
