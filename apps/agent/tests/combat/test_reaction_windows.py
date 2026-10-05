"""Window ids must come from action producers rather than DM guesses."""

import inspect

import pytest

import abilities
import reaction_windows

# The three attack shapes the action_pool reduces to for trigger derivation.
_SWING = {"name": "Scimitar", "damage": "1d6", "damage_type": "slashing", "properties": []}
_GRAB = {
    "name": "Seizing Grab",
    "damage": "1d4",
    "damage_type": "bludgeoning",
    "properties": ["grapple"],
}
_SHRIEK = {
    "name": "Hollow Shriek",
    "damage": "0",
    "damage_type": "psychic",
    "properties": ["control"],
    "applies_condition": "frightened",
    "save": "wisdom",
    "dc": 12,
}


class TestAttackWindows:
    def test_pre_roll_opens_the_targeting_windows_and_the_catch_all(self):
        assert reaction_windows.pre_roll_triggers(_SWING) == (
            "on_targeted",
            "on_ally_targeted",
            "on_enemy_action",
        )

    def test_post_roll_on_a_hit_opens_the_hit_windows_and_the_catch_all(self):
        assert reaction_windows.post_roll_triggers(_SWING, hit=True) == (
            "on_hit",
            "on_ally_hit",
            "on_enemy_action",
        )

    def test_post_roll_on_a_miss_opens_the_miss_window_and_the_catch_all(self):
        assert reaction_windows.post_roll_triggers(_SWING, hit=False) == (
            "on_enemy_miss",
            "on_enemy_action",
        )

    @pytest.mark.parametrize("action", [_SWING, _GRAB, _SHRIEK])
    def test_the_catch_all_is_open_for_every_held_enemy_action(self, action):
        """Implant Doubt consumes successful attacks post-roll, so the catch-all must remain open at both stages."""
        assert "on_enemy_action" in reaction_windows.pre_roll_triggers(action)
        assert "on_enemy_action" in reaction_windows.post_roll_triggers(action, hit=True)
        assert "on_enemy_action" in reaction_windows.post_roll_triggers(action, hit=False)

    @pytest.mark.parametrize("action", [_SWING, _GRAB, _SHRIEK])
    def test_every_derived_trigger_is_a_member_of_the_closed_vocabulary(self, action):
        derived = {
            *reaction_windows.pre_roll_triggers(action),
            *reaction_windows.post_roll_triggers(action, hit=True),
            *reaction_windows.post_roll_triggers(action, hit=False),
        }
        assert derived <= abilities.REACTION_WINDOWS


class TestConditionImposedComesFromProperties:
    """Grapple properties produce the escape window; applies_condition alone does not."""

    def test_a_landed_grapple_opens_the_condition_window(self):
        assert "on_condition_imposed" in reaction_windows.post_roll_triggers(_GRAB, hit=True)

    def test_a_missed_grapple_imposes_nothing(self):
        assert "on_condition_imposed" not in reaction_windows.post_roll_triggers(_GRAB, hit=False)

    def test_the_condition_window_is_post_roll_only(self):
        assert "on_condition_imposed" not in reaction_windows.pre_roll_triggers(_GRAB)

    @pytest.mark.parametrize("hit", [True, False])
    def test_applies_condition_alone_opens_no_condition_window(self, hit):
        """Fear and paralysis are not grapple/restrain; opening escape windows for them would advertise unusable reactions."""
        assert "on_condition_imposed" not in reaction_windows.post_roll_triggers(_SHRIEK, hit=hit)
        assert "on_condition_imposed" not in reaction_windows.pre_roll_triggers(_SHRIEK)

    def test_hollow_shriek_still_reaches_its_real_consumers(self):
        assert "on_ally_targeted" in reaction_windows.pre_roll_triggers(_SHRIEK)


class TestWindowDescriptor:
    def test_the_descriptor_names_its_actor_target_stage_and_triggers(self):
        window = reaction_windows.open_window_for(
            round_number=1,
            seq=0,
            stage="pre_roll",
            actor_id="goblin_scout_1",
            target_id="player_1",
            action_kind="attack",
            triggers=("on_targeted", "on_ally_targeted", "on_enemy_action"),
        )
        assert window == {
            "id": "r1-0-pre_roll",
            "stage": "pre_roll",
            "actor_id": "goblin_scout_1",
            "target_id": "player_1",
            "action_kind": "attack",
            "triggers": ["on_targeted", "on_ally_targeted", "on_enemy_action"],
        }

    def test_the_id_is_unique_per_round_action_and_stage(self):
        ids = {
            reaction_windows.open_window_for(
                round_number=r, seq=s, stage=stage, actor_id="e", target_id=None, action_kind="attack", triggers=()
            )["id"]
            for r in (1, 2)
            for s in (0, 1)
            for stage in ("pre_roll", "post_roll")
        }
        assert len(ids) == 8

    def test_an_unknown_stage_fails_loud(self):
        with pytest.raises(ValueError, match="stage"):
            reaction_windows.open_window_for(
                round_number=1,
                seq=0,
                stage="mid_roll",
                actor_id="e",
                target_id=None,
                action_kind="attack",
                triggers=(),
            )

    def test_action_kind_is_required(self):
        parameter = inspect.signature(reaction_windows.open_window_for).parameters["action_kind"]
        assert parameter.default is inspect.Parameter.empty
