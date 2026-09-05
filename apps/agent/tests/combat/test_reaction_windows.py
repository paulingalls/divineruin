"""The window derivation: a pure function from a held enemy action to the windows it opens
(M29, story-016, AC2/AC3).

Nothing in the tree mapped an enemy action to a member of abilities.REACTION_WINDOWS before this
card — the DM had to guess a window among nine (constraint 6). These are the claims the
derivation makes; test_reaction_window_census.py is the walk that proves the vocabulary is
honestly covered.
"""

import pytest

import abilities
import reaction_windows

# The three action shapes the 68 action_pool entries reduce to, for window purposes.
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
    """AC2 — every held enemy attack opens a pre-roll window and then a post-roll window."""

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
        """AC2's last clause. on_enemy_action is emitted at BOTH stages: its one applicable
        consumer (whisper_implant_doubt) fires when an enemy SUCCEEDS an attack, which only
        exists post-roll, and the AC carries no stage qualifier."""
        assert "on_enemy_action" in reaction_windows.pre_roll_triggers(action)
        assert "on_enemy_action" in reaction_windows.post_roll_triggers(action, hit=True)
        assert "on_enemy_action" in reaction_windows.post_roll_triggers(action, hit=False)

    @pytest.mark.parametrize("action", [_SWING, _GRAB, _SHRIEK])
    def test_every_derived_trigger_is_a_member_of_the_closed_vocabulary(self, action):
        """constraint 6: a window id the DM must guess is not shipped, and an INVENTED id is
        worse — nothing in the ability catalog can ever match it."""
        derived = {
            *reaction_windows.pre_roll_triggers(action),
            *reaction_windows.post_roll_triggers(action, hit=True),
            *reaction_windows.post_roll_triggers(action, hit=False),
        }
        assert derived <= abilities.REACTION_WINDOWS


class TestConditionImposedComesFromProperties:
    """AC3 — the `grapple` property is the producer; `applies_condition` deliberately is not."""

    def test_a_landed_grapple_opens_the_condition_window(self):
        assert "on_condition_imposed" in reaction_windows.post_roll_triggers(_GRAB, hit=True)

    def test_a_missed_grapple_imposes_nothing(self):
        assert "on_condition_imposed" not in reaction_windows.post_roll_triggers(_GRAB, hit=False)

    def test_the_condition_window_is_post_roll_only(self):
        """Both consumers escape a grapple that has LANDED (rogue_slippery "Reaction to a
        restrain/grapple effect", spy_slippery "Reaction when restrained/grappled")."""
        assert "on_condition_imposed" not in reaction_windows.pre_roll_triggers(_GRAB)

    @pytest.mark.parametrize("hit", [True, False])
    def test_applies_condition_alone_opens_no_condition_window(self, hit):
        """The vacuous route. Hollow Shriek is the ONLY action_pool entry carrying
        applies_condition, and it applies `frightened` — which neither on_condition_imposed
        consumer reads; both read grapple/restrain. Deriving off it would open a window nothing
        can use, and AC5 would go green while both consumers stayed unusable (constraint 1)."""
        assert "on_condition_imposed" not in reaction_windows.post_roll_triggers(_SHRIEK, hit=hit)
        assert "on_condition_imposed" not in reaction_windows.pre_roll_triggers(_SHRIEK)

    def test_hollow_shriek_still_reaches_its_real_consumers(self):
        """Fear IS consumed — by bard_countercharm and diplomat_countercharm on
        on_ally_targeted, which the pre-roll window already reaches. The narrow claim above is
        about on_condition_imposed only."""
        assert "on_ally_targeted" in reaction_windows.pre_roll_triggers(_SHRIEK)


class TestWindowDescriptor:
    """The producer's payload: what `next.waiting_on` carries to the DM."""

    def test_the_descriptor_names_its_actor_target_stage_and_triggers(self):
        window = reaction_windows.open_window_for(
            round_number=1,
            seq=0,
            stage="pre_roll",
            actor_id="goblin_scout_1",
            target_id="player_1",
            triggers=("on_targeted", "on_ally_targeted", "on_enemy_action"),
        )
        assert window == {
            "id": "r1-0-pre_roll",
            "stage": "pre_roll",
            "actor_id": "goblin_scout_1",
            "target_id": "player_1",
            "triggers": ["on_targeted", "on_ally_targeted", "on_enemy_action"],
        }

    def test_the_id_is_unique_per_round_action_and_stage(self):
        ids = {
            reaction_windows.open_window_for(
                round_number=r, seq=s, stage=stage, actor_id="e", target_id=None, triggers=()
            )["id"]
            for r in (1, 2)
            for s in (0, 1)
            for stage in ("pre_roll", "post_roll")
        }
        assert len(ids) == 8

    def test_an_unknown_stage_fails_loud(self):
        """constraint 4: a typo'd stage must raise, not ship a window id nothing matches."""
        with pytest.raises(ValueError, match="stage"):
            reaction_windows.open_window_for(
                round_number=1, seq=0, stage="mid_roll", actor_id="e", target_id=None, triggers=()
            )
