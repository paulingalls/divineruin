"""Execute advertised next.verbs through resolve_phase and activate; reading descriptors alone certifies only the list."""

import pytest
from combat._helpers import _activate, _call, _ctx_at_resolution, _own_reaction, _resolve_deps
from combat._reaction_helpers import _guarded_ally_state

import abilities
import combat_hold
import reaction_gate
import reaction_spend
import reaction_windows

POST_ROLL_REACTION = "rogue_uncanny_dodge"
PRE_ROLL_REACTION = "skirmisher_sidestep"


def _ally_targeted_window(*, stage: str, triggers: tuple[str, ...]):
    state = _guarded_ally_state()
    state.open_window = reaction_windows.open_window_for(
        round_number=1,
        seq=0,
        stage=stage,
        actor_id="goblin_scout_1",
        target_id="player_2",
        action_kind="attack",
        triggers=triggers,
    )
    state.reactions_available = {"player_1": reaction_spend.unspent()}
    return state


class TestReactionTargetPolicy:
    def test_every_catalog_window_has_an_explicit_target_policy(self):
        assert frozenset({"on_hit", "on_targeted", "on_condition_imposed"}) == (
            reaction_gate.SELF_TARGETED_REACTION_WINDOWS
        )
        assert (
            frozenset(
                {
                    "on_ally_hit",
                    "on_ally_targeted",
                    "on_enemy_miss",
                    "on_enemy_move",
                    "on_spell_cast",
                    "on_enemy_action",
                }
            )
            == reaction_gate.UNBOUND_REACTION_WINDOWS
        )
        assert reaction_gate.SELF_TARGETED_REACTION_WINDOWS.isdisjoint(reaction_gate.UNBOUND_REACTION_WINDOWS)
        assert (
            reaction_gate.SELF_TARGETED_REACTION_WINDOWS | reaction_gate.UNBOUND_REACTION_WINDOWS
        ) == abilities.REACTION_WINDOWS

    @pytest.mark.parametrize(
        ("ability_id", "stage", "triggers"),
        [
            ("rogue_uncanny_dodge", reaction_windows.POST_ROLL, reaction_windows.post_roll_triggers({}, hit=True)),
            ("skirmisher_sidestep", reaction_windows.PRE_ROLL, reaction_windows.pre_roll_triggers({})),
            (
                "rogue_slippery",
                reaction_windows.POST_ROLL,
                reaction_windows.post_roll_triggers({"properties": ["grapple"]}, hit=True),
            ),
        ],
    )
    def test_self_targeted_reaction_refuses_an_ally_s_window(self, ability_id, stage, triggers):
        state = _ally_targeted_window(stage=stage, triggers=triggers)
        _own_reaction(state, ability_id)

        with pytest.raises(ValueError) as refused:
            reaction_gate.validate_reaction_activation(state, "player_1", ability_id)

        assert "player_2" in str(refused.value)
        assert "player_1" in str(refused.value)

    def test_unclassified_window_fails_loud_at_runtime(self, monkeypatch):
        state = _ally_targeted_window(
            stage=reaction_windows.POST_ROLL,
            triggers=reaction_windows.post_roll_triggers({}, hit=True),
        )
        _own_reaction(state, "guardian_intercept")
        monkeypatch.setattr(
            reaction_gate,
            "UNBOUND_REACTION_WINDOWS",
            reaction_gate.UNBOUND_REACTION_WINDOWS - {"on_ally_hit"},
        )

        with pytest.raises(ValueError, match=r"unclassified.*on_ally_hit"):
            reaction_gate.validate_reaction_activation(state, "player_1", "guardian_intercept")


class TestTheInterruptLoop:
    @pytest.mark.asyncio
    async def test_a_reaction_at_a_window_binds_to_the_held_action_and_closes_the_round(self):
        """Bind a spend to ability and held action; a bool cannot identify which blow to modify."""
        ctx = _ctx_at_resolution(reaction_ids=(PRE_ROLL_REACTION,))
        deps = _resolve_deps()

        await _call(ctx, deps)  # Beat 2: the ally band commits, the enemy blow is held
        paused = await _call(ctx, deps)  # Beat 3: the pre-roll window

        window = paused["next"]["waiting_on"]
        assert window["stage"] == "pre_roll"
        assert "on_targeted" in window["triggers"]

        await _activate(ctx, PRE_ROLL_REACTION, player_class="skirmisher")

        record = ctx.userdata.combat_state.reactions_available["player_1"]
        assert record == {
            "spent": True,
            "ability_id": PRE_ROLL_REACTION,
            "window_id": window["window_id"],
            "stage": "pre_roll",
            "held_seq": 0,
        }

        after = await _call(ctx, deps)
        assert after["next"]["waiting_on"] is None

    @pytest.mark.asyncio
    async def test_the_engine_accepts_a_reaction_at_the_open_window(self):
        ctx = _ctx_at_resolution(reaction_ids=(PRE_ROLL_REACTION,))
        deps = _resolve_deps()
        await _call(ctx, deps)
        r1 = await _call(ctx, deps)

        assert "on_targeted" in r1["next"]["waiting_on"]["triggers"]
        cs = ctx.userdata.combat_state
        assert reaction_gate.validate_reaction_activation(cs, "player_1", PRE_ROLL_REACTION) is None

    @pytest.mark.asyncio
    async def test_a_reaction_for_the_other_stage_is_refused_at_this_window(self):
        ctx = _ctx_at_resolution(reaction_ids=(PRE_ROLL_REACTION,))
        deps = _resolve_deps()
        await _call(ctx, deps)
        await _call(ctx, deps)
        _own_reaction(ctx.userdata.combat_state, POST_ROLL_REACTION)

        with pytest.raises(ValueError, match="on_hit"):
            reaction_gate.validate_reaction_activation(ctx.userdata.combat_state, "player_1", POST_ROLL_REACTION)

    @pytest.mark.asyncio
    async def test_activate_is_still_not_the_advance_verb(self):
        ctx = _ctx_at_resolution(reaction_ids=(PRE_ROLL_REACTION,))
        deps = _resolve_deps()
        await _call(ctx, deps)
        r1 = await _call(ctx, deps)

        assert r1["next"]["waiting_on"] is not None
        assert r1["next"]["verbs"] == ["resolve_phase"]


class TestTheSpendBindsToThePausedBlow:
    @pytest.mark.asyncio
    async def test_a_spend_off_a_pause_is_refused(self):
        ctx = _ctx_at_resolution()
        deps = _resolve_deps()
        await _call(ctx, deps)
        cs = ctx.userdata.combat_state
        cs.open_window = None

        before = cs.reactions_available["player_1"].copy()
        with pytest.raises(ValueError, match="not paused on a held action"):
            combat_hold.preflight_spend(cs, "player_1", PRE_ROLL_REACTION)

        assert cs.reactions_available["player_1"] == before

    @pytest.mark.asyncio
    async def test_a_window_that_answers_another_blow_is_refused(self):
        ctx = _ctx_at_resolution(reaction_ids=(PRE_ROLL_REACTION,))
        deps = _resolve_deps()
        await _call(ctx, deps)
        await _call(ctx, deps)
        cs = ctx.userdata.combat_state
        cs.open_window = {**cs.open_window, "actor_id": "goblin_scout_2"}

        before = cs.reactions_available["player_1"].copy()
        with pytest.raises(ValueError, match="queue head"):
            combat_hold.preflight_spend(cs, "player_1", PRE_ROLL_REACTION)

        assert cs.reactions_available["player_1"] == before
