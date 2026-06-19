"""story-001 (M4.5): the pure dramatic-dice evaluator.

Covers every Always / Contextual / Never row from the canonical catalog in
docs/game_mechanics/game_mechanics_combat.md §Dramatic Dice (L15-75). The bar is
HIGH by design (0-2 reveals per 5-phase fight) — `evaluate_dramatic_context`
flags a roll dramatic only when one catalog predicate holds, and returns the
first-matching reason label (catalog order = severity order)."""

from dramatic import DramaticContext, DramaticVerdict, evaluate_dramatic_context


def _verdict(**signals) -> DramaticVerdict:
    return evaluate_dramatic_context(DramaticContext(**signals))


# --- Always dramatic (engine flags automatically) -------------------------------


def test_natural_20_is_dramatic():
    v = _verdict(raw_die=20, roll_type="attack")
    assert v.dramatic is True
    assert v.context == "natural_20"


def test_natural_1_is_dramatic():
    v = _verdict(raw_die=1, roll_type="attack")
    assert v.dramatic is True
    assert v.context == "natural_1"


def test_death_save_is_always_dramatic():
    v = _verdict(raw_die=11, roll_type="death_save")
    assert v.dramatic is True
    assert v.context == "death_save"


def test_boss_attack_against_player_is_dramatic():
    # Tier 4 == Named/boss targeting the player directly.
    v = _verdict(raw_die=12, roll_type="attack", attacker_tier=4)
    assert v.dramatic is True
    assert v.context == "boss_attack"


def test_counterspell_contest_is_dramatic():
    v = _verdict(raw_die=10, ability="counterspell")
    assert v.dramatic is True
    assert v.context == "counterspell"


def test_de_escalate_attempt_is_dramatic():
    v = _verdict(raw_die=9, ability="de_escalate")
    assert v.dramatic is True
    assert v.context == "de_escalate"


def test_concentration_after_major_damage_is_dramatic():
    v = _verdict(raw_die=8, roll_type="concentration", damage_taken=15)
    assert v.dramatic is True
    assert v.context == "concentration_major_damage"


def test_concentration_below_major_damage_threshold_is_not_dramatic():
    # 14 < 15: a routine concentration check is bookkeeping, not drama.
    v = _verdict(raw_die=8, roll_type="concentration", damage_taken=14)
    assert v.dramatic is False
    assert v.context == ""


# --- Contextually dramatic (engine evaluates; any true => dramatic) -------------


def test_possible_killing_blow_is_dramatic():
    # This hit could drop the target: damage_potential >= remaining HP.
    v = _verdict(raw_die=12, roll_type="attack", target_hp_remaining=6, damage_potential=8)
    assert v.dramatic is True
    assert v.context == "killing_blow"


def test_attack_that_cannot_kill_is_not_dramatic():
    v = _verdict(raw_die=12, roll_type="attack", target_hp_remaining=20, damage_potential=8)
    assert v.dramatic is False
    assert v.context == ""


def test_near_death_defense_is_dramatic_at_boundary():
    v = _verdict(raw_die=12, roll_type="defense", player_hp_percent=0.25)
    assert v.dramatic is True
    assert v.context == "player_near_death"


def test_near_death_only_counts_on_defense_rolls():
    # Same low HP on a non-defense roll does not, by itself, flag dramatic.
    v = _verdict(raw_die=12, roll_type="attack", player_hp_percent=0.25)
    assert v.dramatic is False
    assert v.context == ""


def test_healthy_player_defense_is_not_dramatic():
    v = _verdict(raw_die=12, roll_type="defense", player_hp_percent=0.26)
    assert v.dramatic is False
    assert v.context == ""


def test_first_attack_of_combat_sets_the_tone():
    v = _verdict(raw_die=12, roll_type="attack", is_first_attack_of_combat=True)
    assert v.dramatic is True
    assert v.context == "first_attack"


def test_last_enemy_finishing_attack_is_dramatic():
    v = _verdict(raw_die=12, roll_type="attack", enemies_remaining=1)
    assert v.dramatic is True
    assert v.context == "last_enemy"


def test_last_enemy_only_counts_on_attack_rolls():
    v = _verdict(raw_die=12, roll_type="defense", enemies_remaining=1)
    assert v.dramatic is False
    assert v.context == ""


def test_razor_thin_margin_is_dramatic():
    v = _verdict(raw_die=12, roll_type="attack", margin=1)
    assert v.dramatic is True
    assert v.context == "razor_thin"


def test_razor_thin_margin_negative_one_is_dramatic():
    v = _verdict(raw_die=12, roll_type="attack", margin=-1)
    assert v.dramatic is True
    assert v.context == "razor_thin"


def test_comfortable_margin_is_not_dramatic():
    v = _verdict(raw_die=12, roll_type="attack", margin=2)
    assert v.dramatic is False
    assert v.context == ""


def test_high_stakes_social_is_dramatic():
    v = _verdict(raw_die=12, roll_type="skill_check", social_stakes="high")
    assert v.dramatic is True
    assert v.context == "high_stakes_social"


def test_low_stakes_social_is_not_dramatic():
    v = _verdict(raw_die=12, roll_type="skill_check", social_stakes="low")
    assert v.dramatic is False
    assert v.context == ""


# --- Never dramatic (always invisible) ------------------------------------------


def test_minor_damage_roll_is_never_dramatic():
    v = _verdict(raw_die=7, roll_type="damage")
    assert v.dramatic is False
    assert v.context == ""


def test_npc_initiative_is_never_dramatic():
    v = _verdict(raw_die=13, roll_type="initiative")
    assert v.dramatic is False
    assert v.context == ""


def test_routine_skill_check_is_never_dramatic():
    v = _verdict(raw_die=14, roll_type="skill_check")
    assert v.dramatic is False
    assert v.context == ""


def test_easy_encounter_enemy_attack_is_never_dramatic():
    # Tier 1 creature against a high-level player: no real threat, no tension.
    v = _verdict(raw_die=11, roll_type="attack", attacker_tier=1)
    assert v.dramatic is False
    assert v.context == ""


# --- Severity ordering + purity -------------------------------------------------


def test_first_matching_reason_wins_by_severity():
    # A natural 20 that is also a killing blow surfaces the higher-severity label.
    v = _verdict(raw_die=20, roll_type="attack", target_hp_remaining=2, damage_potential=9)
    assert v.dramatic is True
    assert v.context == "natural_20"


def test_evaluation_does_not_mutate_context():
    ctx = DramaticContext(raw_die=20, roll_type="attack")
    before = (ctx.raw_die, ctx.roll_type)
    evaluate_dramatic_context(ctx)
    assert (ctx.raw_die, ctx.roll_type) == before
