"""Beneficial bonus-die fold + consumption signal across the resolvers (M4.8 story-002).

story-001 modeled the +1d4 bonus die on Blessed/Inspired (conditions.ConditionEffects.bonus_dice).
This story rolls it: when a roll's KIND (attack/save/check) matches a die's scopes, the die is rolled
with the injected rng, folded into the roll total, and the granting condition is SIGNALLED as consumed
on the result packet. Pure — the removal/persist is story-003. Seeded with FixedRng so every die is
deterministic (FixedRng(n) forces every randint to n)."""

from sample_fixtures import FixedRng
from test_rules_core import SAMPLE_PLAYER

from check_resolution import resolve_skill_check_dc, roll_bonus_dice
from check_resolution_attack import resolve_attack
from check_resolution_save import resolve_saving_throw
from conditions import apply_condition

BLESSED = apply_condition([], "blessed")
INSPIRED = apply_condition([], "inspired")
BOTH = apply_condition(apply_condition([], "blessed"), "inspired")

WEAPON = {"name": "Longsword", "damage": "1d8", "damage_type": "slashing", "properties": []}


def _pc(conditions):
    return {**SAMPLE_PLAYER, "conditions": conditions}


# --- roll_bonus_dice helper: kind-scoped matching + consume signal ---


def test_blessed_die_applies_to_attack_and_save_not_check():
    assert roll_bonus_dice(BLESSED, "attack", FixedRng(3)) == (3, ("blessed",))
    assert roll_bonus_dice(BLESSED, "save", FixedRng(3)) == (3, ("blessed",))
    # Blessed is scoped attack+save only — a skill check gets nothing.
    assert roll_bonus_dice(BLESSED, "check", FixedRng(3)) == (0, ())


def test_inspired_die_applies_to_every_roll_kind():
    for kind in ("attack", "save", "check"):
        assert roll_bonus_dice(INSPIRED, kind, FixedRng(2)) == (2, ("inspired",))


def test_both_dice_sum_and_signal_both():
    total, consumed = roll_bonus_dice(BOTH, "attack", FixedRng(4))
    assert total == 8  # two 1d4, each forced to 4
    assert set(consumed) == {"blessed", "inspired"}


def test_no_beneficial_condition_rolls_nothing():
    assert roll_bonus_dice([], "attack", FixedRng(4)) == (0, ())
    assert roll_bonus_dice(apply_condition([], "poisoned"), "attack", FixedRng(4)) == (0, ())


# --- resolve_attack: +1d4 folds into the to-hit roll (content/spells.json: "+1d4 on attack rolls") ---


def test_attack_blessed_adds_die_to_to_hit_and_consumes():
    blessed = resolve_attack(_pc(BLESSED), WEAPON, 12, 30, rng=FixedRng(3))
    plain = resolve_attack(_pc([]), WEAPON, 12, 30, rng=FixedRng(3))
    # Same seed → same d20 + atk_mod; Blessed adds the rolled die (3) to the to-hit total.
    assert blessed.attack_total == plain.attack_total + 3
    assert blessed.consumed_conditions == ("blessed",)
    assert plain.consumed_conditions == ()


# --- resolve_saving_throw: +1d4 folds into the save; auto-fail wastes no die ---


def test_save_inspired_adds_die_and_consumes():
    insp = resolve_saving_throw(_pc(INSPIRED), "wisdom", 12, "stunned", rng=FixedRng(5))
    plain = resolve_saving_throw(_pc([]), "wisdom", 12, "stunned", rng=FixedRng(5))
    assert insp.total == plain.total + 5
    assert insp.consumed_conditions == ("inspired",)
    assert plain.consumed_conditions == ()


def test_save_autofail_does_not_consume_the_die():
    # Stunned auto-fails STR/DEX saves; a Blessed die must not be spent on a save that never rolls.
    conds = apply_condition(apply_condition([], "blessed"), "stunned")
    res = resolve_saving_throw(_pc(conds), "strength", 12, "knocked", rng=FixedRng(5))
    assert res.roll == 0  # auto-failed path
    assert res.success is False
    assert res.consumed_conditions == ()


# --- resolve_skill_check: Inspired applies (any roll), Blessed does not (attack+save only) ---


def test_skill_check_inspired_adds_die_and_consumes():
    insp = resolve_skill_check_dc(_pc(INSPIRED), "athletics", 10, FixedRng(3))
    plain = resolve_skill_check_dc(_pc([]), "athletics", 10, FixedRng(3))
    assert insp.total == plain.total + 3
    assert insp.consumed_conditions == ("inspired",)


def test_skill_check_blessed_does_not_apply():
    blessed = resolve_skill_check_dc(_pc(BLESSED), "athletics", 10, FixedRng(3))
    plain = resolve_skill_check_dc(_pc([]), "athletics", 10, FixedRng(3))
    assert blessed.total == plain.total  # Blessed is not check-scoped
    assert blessed.consumed_conditions == ()


def test_skill_check_beyond_tier_autofail_does_not_consume_die():
    # A DC beyond the character's tier auto-fails without a roll (athletics is trained here, DC 28
    # needs master). The Inspired die must not be spent on a task that cannot succeed — mirrors the
    # save auto-fail gate.
    res = resolve_skill_check_dc(_pc(INSPIRED), "athletics", 28, FixedRng(3))
    assert res.roll == 0 and res.success is False  # beyond-tier auto-fail, no roll
    assert res.consumed_conditions == ()
