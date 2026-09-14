"""The interrupt loop, end to end: pause -> activate -> the binding story-018 reads (story-017).

Split out of test_beat3_hold.py, which holds the Beat-3 QUEUE (pauses, rolls, the two-commit
wrap) and hit the 500-line cap. What lives here is the other half of the same window — what the
DM may do while the machine is paused, and what the engine records when they do it.

Every assertion drives the real ``resolve_phase`` / ``activate`` implementations rather than
reading a descriptor: ``next.verbs`` is a CLAIM about what the engine accepts, and a test that
only read the list combat_wrap builds would certify the list, not the engine (constraint 6).
"""

import pytest
from combat._helpers import _activate, _call, _ctx_at_resolution, _resolve_deps
from combat._reaction_helpers import _guarded_ally_state

import abilities
import combat_hold
import combat_phase
import reaction_spend
import reaction_windows

# rogue_uncanny_dodge fires on on_hit — the POST-ROLL window, the pre-damage pause story-018
# needs. skirmisher_sidestep fires on on_targeted, which only the PRE-ROLL window offers.
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
        triggers=triggers,
    )
    state.reactions_available = {"player_1": reaction_spend.unspent()}
    return state


class TestReactionTargetPolicy:
    def test_every_catalog_window_has_an_explicit_target_policy(self):
        assert frozenset({"on_hit", "on_targeted", "on_condition_imposed"}) == (
            combat_phase.SELF_TARGETED_REACTION_WINDOWS
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
            == combat_phase.UNBOUND_REACTION_WINDOWS
        )
        assert combat_phase.SELF_TARGETED_REACTION_WINDOWS.isdisjoint(combat_phase.UNBOUND_REACTION_WINDOWS)
        assert (
            combat_phase.SELF_TARGETED_REACTION_WINDOWS | combat_phase.UNBOUND_REACTION_WINDOWS
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

        with pytest.raises(ValueError) as refused:
            combat_phase.validate_reaction_activation(state, "player_1", ability_id)

        assert "player_2" in str(refused.value)
        assert "player_1" in str(refused.value)

    def test_unclassified_window_fails_loud_at_runtime(self, monkeypatch):
        state = _ally_targeted_window(
            stage=reaction_windows.POST_ROLL,
            triggers=reaction_windows.post_roll_triggers({}, hit=True),
        )
        monkeypatch.setattr(
            combat_phase,
            "UNBOUND_REACTION_WINDOWS",
            combat_phase.UNBOUND_REACTION_WINDOWS - {"on_ally_hit"},
        )

        with pytest.raises(ValueError, match=r"unclassified.*on_ally_hit"):
            combat_phase.validate_reaction_activation(state, "player_1", "guardian_intercept")


class TestTheInterruptLoop:
    @pytest.mark.asyncio
    async def test_a_reaction_at_a_window_binds_to_the_held_action_and_closes_the_round(self):
        """AC1 end to end, through the verbs the DM actually calls.

        No declaration was ever made — the pause IS the permission. What the spend records is the
        ability id AND the held action it answers, because story-018's two wired outcomes both
        need it ("halve THIS damage", "+2 AC against THIS attack"). A bare bool would say a
        reaction fired and leave 018 unable to name the blow.

        The second half is the truthiness trap: having spent, the player opens NO further window
        for the rest of the round, so the post-roll pause does not come back around.
        """
        ctx = _ctx_at_resolution()
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

        # The round runs on: the reaction is spent, so the post-roll window never opens.
        after = await _call(ctx, deps)
        assert after["next"]["waiting_on"] is None

    @pytest.mark.asyncio
    async def test_the_engine_accepts_a_reaction_at_the_open_window(self):
        """The acceptance half of `next.verbs`, EXECUTED. story-016 could only assert the engine
        REFUSED here (the gate was pinned to the RESOLUTION beat); story-017 rebound it, so this
        is the assertion that had to move with it."""
        ctx = _ctx_at_resolution()
        deps = _resolve_deps()
        await _call(ctx, deps)
        r1 = await _call(ctx, deps)

        assert "on_targeted" in r1["next"]["waiting_on"]["triggers"]
        cs = ctx.userdata.combat_state
        assert combat_phase.validate_reaction_activation(cs, "player_1", PRE_ROLL_REACTION) is None

    @pytest.mark.asyncio
    async def test_a_reaction_for_the_other_stage_is_refused_at_this_window(self):
        """AC3 on the live loop: on_hit is not on offer before the roll, so Uncanny Dodge cannot
        be spent at the pre-roll pause — the outcome it answers does not exist yet."""
        ctx = _ctx_at_resolution()
        deps = _resolve_deps()
        await _call(ctx, deps)
        await _call(ctx, deps)

        with pytest.raises(ValueError, match="on_hit"):
            combat_phase.validate_reaction_activation(ctx.userdata.combat_state, "player_1", POST_ROLL_REACTION)

    @pytest.mark.asyncio
    async def test_activate_is_still_not_the_advance_verb(self):
        """D5: `verbs` names the move that ADVANCES the beat, and only resolve_phase does. The
        producer for activation is the prompt plus this window's own `triggers` — listing a
        non-advancing verb would contradict the "not a whitelist" reading in the same payload."""
        ctx = _ctx_at_resolution()
        deps = _resolve_deps()
        await _call(ctx, deps)
        r1 = await _call(ctx, deps)

        assert r1["next"]["waiting_on"] is not None
        assert r1["next"]["verbs"] == ["resolve_phase"]


class TestTheSpendBindsToThePausedBlow:
    """Spend preflight preserves the binding invariants without mutating the round budget."""

    @pytest.mark.asyncio
    async def test_a_spend_off_a_pause_is_refused(self):
        """The engine's own invariant, not the DM's: with no window and no queue there is no blow
        to bind to, and a record written anyway would name a held action that never existed."""
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
        """The binding is to the QUEUE HEAD, and that is checked rather than assumed — a window
        naming a different actor means the pump popped past the blow this spend answers, and
        story-018 would halve the damage of the wrong one."""
        ctx = _ctx_at_resolution()
        deps = _resolve_deps()
        await _call(ctx, deps)
        await _call(ctx, deps)
        cs = ctx.userdata.combat_state
        cs.open_window = {**cs.open_window, "actor_id": "goblin_scout_2"}

        before = cs.reactions_available["player_1"].copy()
        with pytest.raises(ValueError, match="queue head"):
            combat_hold.preflight_spend(cs, "player_1", PRE_ROLL_REACTION)

        assert cs.reactions_available["player_1"] == before
