"""Status-condition modifiers feeding checks, attacks, and saves (M4.3, story-003).

get_condition_effects (story-001) gives flat/scope effects; this story applies them at the
resolution seam: Exhausted -1/stack on checks/saves, Poisoned/Prone/Blinded disadvantage,
Stunned auto-fail STR/DEX saves, Enraged +2 damage / -2 AC. The pure resolvers read conditions
from the data dict they're given; the in-combat callers (combat_support, concentration_break)
thread the participant's conditions. Out-of-combat skill-check threading is deferred to story-004.
"""

import random
from unittest.mock import AsyncMock, MagicMock

from combat._helpers import _make_combat_state
from sample_fixtures import make_context

import check_resolution_save
from check_resolution import (
    _apply_condition_modifiers,
    _roll_d20_check,
    resolve_skill_check_dc,
)
from check_resolution_attack import AttackResult, resolve_attack
from combat_support import _resolve_attack_packet
from concentration_break import break_concentration_on_damage
from conditions import apply_condition, get_condition_effects
from rules_engine import has_iron_constitution
from session_data import SessionData


class _ScriptedRNG(random.Random):
    """An rng whose randint returns a scripted sequence, for deterministic d20s.
    Subclasses random.Random so it satisfies the resolvers' rng type."""

    def __init__(self, values):
        super().__init__()
        self.values = list(values)
        self.i = 0

    def randint(self, a, b):
        v = self.values[self.i]
        self.i += 1
        return v


# --- Slice 1: _roll_d20_check advantage/disadvantage ---


def test_advantage_keeps_higher_of_two_d20s():
    core = _roll_d20_check(0, 10, rng=_ScriptedRNG([5, 18]), advantage=True)
    assert core.roll == 18


def test_disadvantage_keeps_lower_of_two_d20s():
    core = _roll_d20_check(0, 10, rng=_ScriptedRNG([5, 18]), disadvantage=True)
    assert core.roll == 5


def test_advantage_and_disadvantage_cancel_to_single_roll():
    core = _roll_d20_check(0, 10, rng=_ScriptedRNG([7, 19]), advantage=True, disadvantage=True)
    assert core.roll == 7  # only one d20 consumed


# --- Slice 2: _apply_condition_modifiers ---


def test_apply_modifiers_empty():
    assert _apply_condition_modifiers(get_condition_effects([]), {"str"}) == (0, False, False, False)


def test_apply_modifiers_flat_from_exhausted():
    conds = apply_condition([], "exhausted")
    conds = apply_condition(conds, "exhausted")
    flat, adv, dis, auto = _apply_condition_modifiers(get_condition_effects(conds), {"str"})
    assert flat == -2 and adv is False and dis is False and auto is False


def test_apply_modifiers_disadvantage_on_matching_scope():
    conds = apply_condition([], "poisoned")  # str/dex/con
    _, _, dis, _ = _apply_condition_modifiers(get_condition_effects(conds), {"str", "athletics"})
    assert dis is True


def test_apply_modifiers_auto_fail_on_matching_save_scope():
    conds = apply_condition([], "stunned")  # auto-fail str/dex
    _, _, _, auto = _apply_condition_modifiers(get_condition_effects(conds), {"dex"})
    assert auto is True


# --- Slice 3: skill checks ---


def _player(**extra):
    base = {"attributes": {"strength": 14, "charisma": 14}, "level": 5, "skill_tiers": {}}
    base.update(extra)
    return base


def test_exhausted_lowers_check_modifier():
    plain = resolve_skill_check_dc(_player(), "athletics", 15, rng=_ScriptedRNG([10]))
    tired = resolve_skill_check_dc(
        _player(conditions=apply_condition([], "exhausted")), "athletics", 15, rng=_ScriptedRNG([10])
    )
    assert tired.modifier == plain.modifier - 1


def test_poisoned_disadvantages_physical_skill():
    conds = apply_condition([], "poisoned")
    result = resolve_skill_check_dc(_player(conditions=conds), "athletics", 15, rng=_ScriptedRNG([18, 5]))
    assert result.roll == 5  # disadvantage kept the lower die


def test_poisoned_does_not_disadvantage_charisma_skill():
    conds = apply_condition([], "poisoned")  # str/dex/con only
    result = resolve_skill_check_dc(_player(conditions=conds), "persuasion", 15, rng=_ScriptedRNG([18, 5]))
    assert result.roll == 18  # single die — charisma skill unaffected


# --- Slice 4: attacks ---


def _weapon():
    return {"name": "Longsword", "damage": "1d6", "damage_type": "slashing", "properties": []}


def test_prone_attacker_rolls_attack_at_disadvantage():
    attacker = {"attributes": {"strength": 14}, "level": 5, "conditions": apply_condition([], "prone")}
    result = resolve_attack(attacker, _weapon(), target_ac=5, target_hp=20, rng=_ScriptedRNG([18, 5, 4]))
    assert result.roll == 5  # kept the lower die


def test_enraged_attacker_adds_two_damage():
    plain_attacker = {"attributes": {"strength": 14}, "level": 5}
    enraged_attacker = {"attributes": {"strength": 14}, "level": 5, "conditions": apply_condition([], "enraged")}
    plain = resolve_attack(plain_attacker, _weapon(), target_ac=5, target_hp=20, rng=_ScriptedRNG([15, 4]))
    enraged = resolve_attack(enraged_attacker, _weapon(), target_ac=5, target_hp=20, rng=_ScriptedRNG([15, 4]))
    assert enraged.damage == plain.damage + 2


# --- Slice 5: saves ---


def test_exhausted_lowers_save_modifier():
    plain = check_resolution_save.resolve_saving_throw(
        {"attributes": {"constitution": 14}, "level": 5}, "constitution", 12, "stunned", rng=_ScriptedRNG([10])
    )
    tired = check_resolution_save.resolve_saving_throw(
        {"attributes": {"constitution": 14}, "level": 5, "conditions": apply_condition([], "exhausted")},
        "constitution",
        12,
        "stunned",
        rng=_ScriptedRNG([10]),
    )
    assert tired.modifier == plain.modifier - 1


def test_stunned_auto_fails_strength_save():
    result = check_resolution_save.resolve_saving_throw(
        {"attributes": {"strength": 18}, "level": 5, "conditions": apply_condition([], "stunned")},
        "strength",
        5,  # trivially low DC — would pass if rolled
        "knocked_down",
        rng=_ScriptedRNG([20]),
    )
    assert result.success is False
    assert result.roll == 0
    assert result.effect_applied == "knocked_down"


# --- Slice 6: Iron Constitution exhaustion cap ---


def test_has_iron_constitution_true_for_endurance_master():
    assert has_iron_constitution({"skill_tiers": {"endurance": "master"}}) is True


def test_has_iron_constitution_false_otherwise():
    assert has_iron_constitution({"skill_tiers": {"endurance": "expert"}}) is False
    assert has_iron_constitution({}) is False


def test_iron_constitution_caps_exhaustion_at_three():
    player = {"skill_tiers": {"endurance": "master"}}
    cap = 3 if has_iron_constitution(player) else 5
    conds = []
    for _ in range(5):
        conds = apply_condition(conds, "exhausted", max_stacks=cap)
    assert conds[0]["stacks"] == 3


# --- Slice 7: in-combat caller threading ---


def _capturing_attack_resolver():
    result = AttackResult(
        hit=True,
        roll=15,
        attack_modifier=3,
        attack_total=18,
        target_ac=11,
        damage=5,
        damage_type="slashing",
        critical_success=False,
        critical_failure=False,
        target_hp_remaining=2,
        target_killed=False,
        narrative_hint="A clean strike.",
    )
    resolver = MagicMock()
    resolver.resolve_attack = MagicMock(return_value=result)
    return resolver


async def test_combat_support_threads_attacker_conditions_and_target_ac():
    ctx = make_context()
    cs = _make_combat_state()
    attacker = cs.get_participant("player_1")
    target = cs.get_participant("goblin_scout_1")
    assert attacker is not None and target is not None
    attacker.conditions = apply_condition([], "prone")
    target.conditions = apply_condition([], "enraged")  # -2 AC
    resolver = _capturing_attack_resolver()
    action = {"name": "Longsword", "damage": "1d6", "damage_type": "slashing", "properties": []}

    await _resolve_attack_packet(
        ctx.userdata,
        attacker,
        action,
        target,
        mutations=MagicMock(update_item_durability=AsyncMock()),
        queries=MagicMock(),
        resolver=resolver,
        concentration_break_mod=MagicMock(break_concentration_on_damage=AsyncMock(return_value=None)),
    )

    passed_attacker_data, _action, passed_ac, _hp = resolver.resolve_attack.call_args.args
    assert passed_attacker_data["conditions"] == attacker.conditions
    assert passed_ac == target.ac - 2  # Enraged target is easier to hit


async def test_concentration_break_threads_caster_conditions_into_save():
    session = SessionData(player_id="player_1", location_id="accord_guild_hall", room=None)
    session.concentration.spell_id = "arcane_fly"
    cs = _make_combat_state()
    caster = cs.get_participant("player_1")
    assert caster is not None
    caster.conditions = apply_condition([], "exhausted")
    session.combat_state = cs

    queries = MagicMock()
    queries.get_player = AsyncMock(return_value={"attributes": {"constitution": 14}, "level": 5})
    resolver = MagicMock()
    resolver.resolve_saving_throw = MagicMock(return_value=MagicMock(total=99))  # holds; we assert the input
    cm = MagicMock(update_player_concentration=AsyncMock())

    await break_concentration_on_damage(
        session,
        10,
        incapacitated=False,
        damaged_player_id="player_1",
        queries=queries,
        resolver=resolver,
        concentration_mutations=cm,
    )

    passed_player = resolver.resolve_saving_throw.call_args.args[0]
    assert passed_player["conditions"] == caster.conditions
