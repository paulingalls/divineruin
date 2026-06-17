"""Unit tests for the pure enhancer policy (M4.2, story-004).

combat_enhancers decides (1) how many/which attack actions one ATTACK declaration
expands into and (2) which narrated riders attach. Pure — no IO, no state.
"""

from combat_enhancers import (
    SHIELD_BASH_ACTION,
    attack_sequence,
    declaration_riders,
    enhancers_from_flags,
)
from declarations import Declaration, DeclarationType

_WEAPON = {"name": "Longsword", "damage": "1d8", "damage_type": "slashing", "properties": []}


def _attack(rider: str | None = None) -> Declaration:
    return Declaration(type=DeclarationType.ATTACK, action="Longsword", target_id="goblin_1", rider=rider)


class TestAttackSequence:
    def test_no_enhancer_resolves_one_attack(self) -> None:
        assert attack_sequence([], _WEAPON) == [_WEAPON]

    def test_extra_attack_resolves_the_swing_twice(self) -> None:
        assert attack_sequence(["extra_attack"], _WEAPON) == [_WEAPON, _WEAPON]

    def test_shield_bash_adds_a_bash_strike(self) -> None:
        assert attack_sequence(["shield_bash"], _WEAPON) == [_WEAPON, SHIELD_BASH_ACTION]

    def test_shield_bash_replaces_the_extra_attack_when_both(self) -> None:
        # gm_combat L120: Shield Bash "replaces one attack if multiattack" — total stays 2.
        assert attack_sequence(["extra_attack", "shield_bash"], _WEAPON) == [_WEAPON, SHIELD_BASH_ACTION]

    def test_non_attack_enhancers_do_not_expand_the_sequence(self) -> None:
        assert attack_sequence(["cunning_action", "hit_and_run"], _WEAPON) == [_WEAPON]


class TestDeclarationRiders:
    def test_no_enhancer_yields_no_riders(self) -> None:
        assert declaration_riders([], _attack()) == []

    def test_cunning_action_uses_chosen_rider(self) -> None:
        assert declaration_riders(["cunning_action"], _attack(rider="hide")) == ["cunning_action:hide"]

    def test_cunning_action_defaults_dash_when_unchosen_or_invalid(self) -> None:
        assert declaration_riders(["cunning_action"], _attack()) == ["cunning_action:dash"]
        assert declaration_riders(["cunning_action"], _attack(rider="teleport")) == ["cunning_action:dash"]

    def test_hit_and_run_and_command_lesser_riders(self) -> None:
        assert declaration_riders(["hit_and_run"], _attack()) == ["hit_and_run:reposition_15ft"]
        assert declaration_riders(["command_lesser"], _attack()) == ["command_lesser:directs_lesser_hollow"]

    def test_quick_change_rides_a_social_interact_not_an_attack(self) -> None:
        interact = Declaration(type=DeclarationType.INTERACT, action="charm the guard")
        assert declaration_riders(["quick_change"], interact) == ["quick_change:identity_swap"]
        # Quick Change does not fire on an ATTACK declaration (wrong host category).
        assert declaration_riders(["quick_change"], _attack()) == []

    def test_attack_riders_do_not_fire_on_non_attack(self) -> None:
        defend = Declaration(type=DeclarationType.DEFEND, ac_bonus=2)
        assert declaration_riders(["cunning_action", "hit_and_run", "command_lesser"], defend) == []

    def test_multiple_riders_aggregate_in_order(self) -> None:
        riders = declaration_riders(["cunning_action", "hit_and_run", "command_lesser"], _attack(rider="disengage"))
        assert riders == [
            "cunning_action:disengage",
            "hit_and_run:reposition_15ft",
            "command_lesser:directs_lesser_hollow",
        ]


class TestEnhancersFromFlags:
    def test_maps_truthy_known_flags_only(self) -> None:
        flags = {"extra_attack": True, "shield_bash": False, "not_an_enhancer": True}
        assert enhancers_from_flags(flags) == ["extra_attack"]

    def test_empty_or_missing_flags_yield_none(self) -> None:
        assert enhancers_from_flags({}) == []
        assert enhancers_from_flags(None) == []

    def test_order_is_deterministic_not_insertion_order(self) -> None:
        flags = {"quick_change": True, "extra_attack": True, "cunning_action": True}
        assert enhancers_from_flags(flags) == ["extra_attack", "cunning_action", "quick_change"]
