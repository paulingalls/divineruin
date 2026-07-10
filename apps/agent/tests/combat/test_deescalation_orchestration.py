"""Tier-3 de-escalation orchestration: the multi-round GROUP loop that wires story-001's
pure per-round resolver into live combat (M15 story-002).

A Diplomat argues over 2-4 rounds against a GROUP of enemies; each enemy's disposition shifts
INDEPENDENTLY by its own resistance profile until the whole living group crosses +2, at which
point ``state.deescalated`` flips and the phase _wrap ends combat "deescalated". These drive the
packet resolver directly (mirroring test_combat_deescalation's _resolve_deescalation_packet
driver) with a MULTI-ENEMY state builder; the end-to-end phase-loop drive lives in the E2E class.
"""

import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from combat._helpers import _damage_resolver, _fake_db_mod
from sample_fixtures import FixedRng, make_context

import combat_resolution
import combat_turn
from combat_deescalation import MAX_DEESCALATION_ROUNDS, _gate_deescalation, _resolve_deescalation_packet
from declarations import DeclarationType
from session_data import CombatParticipant, CombatState
from tools._helpers import SAMPLE_PLAYER


def _d20(face: int):
    """A check_resolution.dice_roll stand-in forcing the persuasion d20 to `face` (reads .total)."""
    return SimpleNamespace(total=face)


# charisma 16 -> +3; persuasion untrained -> the round's argument_total is FixedRng(d20) + 3.
_DIPLOMAT = {**SAMPLE_PLAYER, "attributes": {**SAMPLE_PLAYER["attributes"], "charisma": 16}, "focus": {"current": 20}}


def _make_group_state(*, tags_a=("pragmatic",), tags_b=("suspicious",), enemy_a_fallen=False):
    """A CombatState with ONE Diplomat and TWO living enemies carrying (by default) DIFFERENT
    resistance profiles, so a single argument round shifts each enemy's disposition independently."""
    return CombatState(
        combat_id="combat_group_test",
        participants=[
            CombatParticipant(
                id="player_1", name="Kael", type="player", initiative=15, hp_current=25, hp_max=25, ac=14
            ),
            CombatParticipant(
                id="enemy_a",
                name="Mawling A",
                type="enemy",
                initiative=12,
                hp_current=18,
                hp_max=18,
                ac=13,
                attributes={"wisdom": 10},
                resistance_tags=list(tags_a),
                is_fallen=enemy_a_fallen,
            ),
            CombatParticipant(
                id="enemy_b",
                name="Mawling B",
                type="enemy",
                initiative=10,
                hp_current=18,
                hp_max=18,
                ac=13,
                attributes={"wisdom": 10},
                resistance_tags=list(tags_b),
            ),
        ],
        initiative_order=["player_1", "enemy_a", "enemy_b"],
        location_id="ruins",
    )


def _decl(argument_type="reason"):
    return SimpleNamespace(type=DeclarationType.ABILITY, action="de_escalate", argument_type=argument_type)


async def _resolve_round(state, player, rng, *, argument_type="reason"):
    session = MagicMock()
    session.room = None
    session.event_bus = MagicMock()
    session.record_event = MagicMock()
    persistence = MagicMock()
    persistence.update_player_resources = AsyncMock()
    attacker = state.get_participant("player_1")
    result = await _resolve_deescalation_packet(
        session,
        attacker,
        _decl(argument_type),
        state=state,
        conn=None,
        player=player,
        sink=None,
        persistence=persistence,
        rng=rng,
    )
    return result, persistence, session


class TestGroupIndependence:
    """AC1: each enemy's per-enemy disposition shifts INDEPENDENTLY by its OWN resistance profile."""

    @pytest.mark.asyncio
    async def test_vulnerable_enemy_shifts_more_than_resistant_in_one_round(self):
        # argument_total = 20 + 3 = 23. reason: enemy_a pragmatic -> vulnerable (-3), enemy_b
        # suspicious -> resistant (+3). Same roll, opposite DC swing -> different delta.
        state = _make_group_state(tags_a=("pragmatic",), tags_b=("suspicious",))
        result, _persistence, _session = await _resolve_round(state, _DIPLOMAT, FixedRng(20))

        scene = state.deescalation_scene
        # enemy_a (DC 15+6-3=18): margin 5 -> +1; enemy_b (DC 15+6+3=24): margin -1 -> 0.
        assert scene.cumulative_shift["enemy_a"] == 1
        assert scene.cumulative_shift["enemy_b"] == 0
        assert scene.cumulative_shift["enemy_a"] > scene.cumulative_shift["enemy_b"]
        # The vulnerable enemy's disposition softened; the resistant one stayed hostile.
        assert scene.enemy_dispositions["enemy_a"] == "unfriendly"
        assert scene.enemy_dispositions["enemy_b"] == "hostile"
        # The packet reports the per-enemy breakdown for the DM.
        by_id = {pe["id"]: pe for pe in result["deescalation"]["per_enemy"]}
        assert by_id["enemy_a"]["cumulative_shift"] == 1
        assert by_id["enemy_b"]["cumulative_shift"] == 0
        assert result["deescalation"]["ends_combat"] is False

    @pytest.mark.asyncio
    async def test_only_living_enemies_are_argued(self):
        # A fallen enemy is skipped entirely — no disposition/shift entry is written for it.
        state = _make_group_state(tags_a=("pragmatic",), enemy_a_fallen=True)
        result, _p, _s = await _resolve_round(state, _DIPLOMAT, FixedRng(20))
        assert "enemy_a" not in state.deescalation_scene.cumulative_shift
        assert [pe["id"] for pe in result["deescalation"]["per_enemy"]] == ["enemy_b"]


class TestCrossRoundPersistence:
    """AC2: orchestration persists DeEscalationState between rounds (round_counter + per-enemy maps)."""

    @pytest.mark.asyncio
    async def test_two_rounds_accumulate_and_increment_counter(self):
        # Both enemies vulnerable to reason so both progress; thread the SAME state across two calls.
        state = _make_group_state(tags_a=("pragmatic",), tags_b=("honorable",))
        await _resolve_round(state, _DIPLOMAT, FixedRng(20))
        assert state.deescalation_scene.round_counter == 1
        assert state.deescalation_scene.cumulative_shift["enemy_a"] == 1

        await _resolve_round(state, _DIPLOMAT, FixedRng(20))
        # Round 2 argues each enemy from its round-1 disposition (unfriendly), accumulating.
        assert state.deescalation_scene.round_counter == 2
        assert state.deescalation_scene.cumulative_shift["enemy_a"] == 2
        assert state.deescalation_scene.cumulative_shift["enemy_b"] == 2

    @pytest.mark.asyncio
    async def test_focus_is_spent_each_round(self):
        state = _make_group_state()
        _r, persistence, _s = await _resolve_round(state, _DIPLOMAT, FixedRng(20))
        # 20 Focus - 3 = 17 for the round.
        assert persistence.update_player_resources.await_args.kwargs["focus"] == 17


class TestRoundCap:
    """AC2: the scene enforces the round cap (MAX 4)."""

    def test_gate_raises_at_round_cap(self):
        state = _make_group_state()
        state.deescalation_scene.round_counter = MAX_DEESCALATION_ROUNDS
        with pytest.raises(Exception, match="stopped listening"):
            _gate_deescalation(_DIPLOMAT, state)

    def test_gate_passes_below_cap(self):
        state = _make_group_state()
        state.deescalation_scene.round_counter = MAX_DEESCALATION_ROUNDS - 1
        _gate_deescalation(_DIPLOMAT, state)  # no raise

    @pytest.mark.asyncio
    async def test_unknown_argument_type_fails_loud(self):
        state = _make_group_state()
        with pytest.raises(Exception, match="argument_type"):
            await _resolve_round(state, _DIPLOMAT, FixedRng(20), argument_type="nonsense")


class TestWholeGroupSurrender:
    """AC3: the WHOLE living group must cross +2 for combat to end; a partial group keeps it alive."""

    @pytest.mark.asyncio
    async def test_whole_group_crossing_threshold_flips_deescalated(self):
        # Both vulnerable to reason: +1 each round, so both cross +2 at round 2 -> deescalated.
        state = _make_group_state(tags_a=("pragmatic",), tags_b=("honorable",))
        r1, _p, _s = await _resolve_round(state, _DIPLOMAT, FixedRng(20))
        assert r1["deescalation"]["ends_combat"] is False  # both only at +1 after round 1
        assert state.deescalated is False

        r2, _p2, _s2 = await _resolve_round(state, _DIPLOMAT, FixedRng(20))
        assert r2["deescalation"]["ends_combat"] is True
        assert state.deescalated is True

    @pytest.mark.asyncio
    async def test_partial_group_keeps_combat_alive(self):
        # enemy_a vulnerable (reaches +2), enemy_b resistant (stuck at 0) -> deescalated stays False
        # even though one enemy has surrendered.
        state = _make_group_state(tags_a=("pragmatic",), tags_b=("suspicious",))
        await _resolve_round(state, _DIPLOMAT, FixedRng(20))
        await _resolve_round(state, _DIPLOMAT, FixedRng(20))

        scene = state.deescalation_scene
        assert scene.cumulative_shift["enemy_a"] >= combat_resolution.SURRENDER_THRESHOLD
        assert scene.cumulative_shift["enemy_b"] < combat_resolution.SURRENDER_THRESHOLD
        assert state.deescalated is False


class TestSurrenderLatch:
    """Finding #2: a surrendered enemy is LATCHED — left out of later argued rounds so a bad roll can
    never regress it below the threshold, which is what lets the whole-group gate actually coincide."""

    @pytest.mark.asyncio
    async def test_surrendered_enemy_is_not_re_argued_and_cannot_regress(self):
        # enemy_a has already crossed +2 (latched, neutral). A later terrible-roll round that WOULD
        # push a negative delta is simply never applied to it — it's excluded from the argued targets.
        state = _make_group_state(tags_a=("pragmatic",), tags_b=("suspicious",))
        state.deescalation_scene.cumulative_shift["enemy_a"] = combat_resolution.SURRENDER_THRESHOLD
        state.deescalation_scene.enemy_dispositions["enemy_a"] = "neutral"
        result, _p, _s = await _resolve_round(state, _DIPLOMAT, FixedRng(1))  # d20 1 + 3 = a failing 4

        scene = state.deescalation_scene
        assert scene.cumulative_shift["enemy_a"] == combat_resolution.SURRENDER_THRESHOLD  # never regressed
        argued = [pe["id"] for pe in result["deescalation"]["per_enemy"]]
        assert "enemy_a" not in argued  # latched enemy left untouched
        assert "enemy_b" in argued  # the holdout is still argued
        assert state.deescalated is False  # enemy_b hasn't crossed -> group hasn't yielded


class TestDeescalatedEarlyOut:
    """Finding #4: once an earlier de_escalate packet this phase ended the scene, a second Diplomat's
    packet is a no-op — no Focus spent, no roll, the round not advanced."""

    @pytest.mark.asyncio
    async def test_second_packet_after_group_stood_down_is_a_noop(self):
        state = _make_group_state()
        state.deescalated = True  # an earlier packet this phase already ended the scene
        result, persistence, _s = await _resolve_round(state, _DIPLOMAT, FixedRng(20))
        assert result["resolved"] is False
        persistence.update_player_resources.assert_not_awaited()  # no Focus spent
        assert state.deescalation_scene.round_counter == 0  # scene not advanced
        assert state.deescalation_scene.cumulative_shift == {}  # no roll applied


class TestRoundCounterAdvancesOncePerPhase:
    """Finding #3: the round_counter models SCENE rounds (phases), not de_escalate packets. Two
    Diplomats declaring in ONE phase argue the SAME round — the counter must advance at most once, or
    the pair would push it past the declare-time cap. ``session.combat_state`` is the pristine pre-phase
    copy during resolution (the working ``state`` is a deep copy), so the second packet — seeing the
    working counter already ahead of the pristine value — skips the increment."""

    @pytest.mark.asyncio
    async def test_two_packets_in_one_phase_advance_round_once(self):
        pristine = _make_group_state(tags_a=("suspicious",), tags_b=("suspicious",))  # neither surrenders
        working = copy.deepcopy(pristine)  # the phase's working next_state (deep copy, per resolve_phase)
        session = MagicMock()
        session.room = None
        session.event_bus = MagicMock()
        session.record_event = MagicMock()
        session.combat_state = pristine  # a REAL CombatState -> the pre-phase guard engages
        persistence = MagicMock()
        persistence.update_player_resources = AsyncMock()
        attacker = working.get_participant("player_1")
        assert attacker is not None

        for _ in range(2):  # two Diplomats' packets resolve against the SAME working state this phase
            await _resolve_deescalation_packet(
                session,
                attacker,
                _decl(),
                state=working,
                conn=None,
                player=_DIPLOMAT,
                sink=None,
                persistence=persistence,
                rng=FixedRng(1),
            )

        assert working.deescalation_scene.round_counter == 1  # advanced once, not twice -> cap intact
        assert persistence.update_player_resources.await_count == 2  # both still argued + spent Focus


def _e2e_group_state(combat_id, player_id, enemy_ids_tags):
    """A DECLARATION-beat 2-enemy CombatState for the end-to-end drive. The player carries no
    action_pool (it only de-escalates); each enemy has a Grasping Maw attack + its resistance_tags."""
    parts = [
        CombatParticipant(id=player_id, name="Kael", type="player", initiative=15, hp_current=200, hp_max=200, ac=14)
    ]
    init = 12
    for eid, tags in enemy_ids_tags:
        parts.append(
            CombatParticipant(
                id=eid,
                name=eid,
                type="enemy",
                initiative=init,
                hp_current=18,
                hp_max=18,
                ac=13,
                attributes={"wisdom": 10},
                action_pool=[{"name": "Grasping Maw", "damage": "1d8", "damage_type": "necrotic", "properties": []}],
                resistance_tags=list(tags),
            )
        )
        init -= 1
    return CombatState(
        combat_id=combat_id,
        participants=parts,
        initiative_order=[player_id] + [eid for eid, _ in enemy_ids_tags],
        location_id="ruins",
    )


class TestDeescalationE2EPhaseLoop:
    """AC4: drive the REAL phase loop (declare_phase -> resolve_phase -> wrap) over multiple rounds
    with a 2-enemy hostile group until both surrender -> combat ends with outcome "deescalated"."""

    def _deps(self):
        # A high-charisma untrained-persuasion player -> argument_total = 20 (forced d20) + 6 = 26,
        # which clears both enemies over 2 rounds regardless of enemy attack noise.
        queries = MagicMock()
        queries.get_player_inventory = AsyncMock(return_value=[])
        queries.get_player = AsyncMock(
            return_value={
                "player_id": "deesc_e2e_player",
                "focus": {"current": 12, "max": 12},
                "attributes": {"charisma": 22},
                "level": 1,
            }
        )
        mutations = MagicMock()
        mutations.save_combat_state = AsyncMock()
        mutations.update_player_hp = AsyncMock()
        mutations.delete_combat_state = AsyncMock()
        break_mod = MagicMock()
        break_mod.break_concentration_on_damage = AsyncMock(return_value=None)
        return {
            "mutations": mutations,
            "queries": queries,
            "resolver": _damage_resolver(2),
            "concentration_break_mod": break_mod,
            "db_mod": _fake_db_mod(),
        }

    @pytest.mark.asyncio
    async def test_two_enemy_group_argued_down_over_rounds_ends_deescalated(self):
        player_id = "deesc_e2e_player"
        combat_id = "combat_deesc_e2e"
        ctx = make_context(player_id, location_id="ruins")
        ctx.userdata.combat_state = _e2e_group_state(
            combat_id, player_id, [("enemy_a", ("cowardly",)), ("enemy_b", ("pragmatic",))]
        )
        deps = self._deps()

        decls = {
            player_id: {"type": "ability", "action": "de_escalate", "argument_type": "reason"},
            "enemy_a": {"type": "attack", "action": "Grasping Maw", "target_id": player_id},
            "enemy_b": {"type": "attack", "action": "Grasping Maw", "target_id": player_id},
        }

        with (
            patch("check_resolution.dice_roll", return_value=_d20(20)),
            patch("ability_persistence.update_player_resources", AsyncMock()),
        ):
            # Round 1: both enemies only reach +1 -> combat continues (a JSON response, not a handoff).
            await combat_turn._declare_phase_impl(ctx, decls, mutations=deps["mutations"])
            raw1 = await combat_turn._resolve_phase_impl(ctx, **deps)
            assert isinstance(raw1, str), "round 1 does not end combat"
            assert ctx.userdata.combat_state.deescalated is False
            assert ctx.userdata.combat_state.deescalation_scene.round_counter == 1

            # Round 2: both cross +2 -> the wrap ends combat with outcome "deescalated" (a handoff tuple).
            await combat_turn._declare_phase_impl(ctx, decls, mutations=deps["mutations"])
            raw2 = await combat_turn._resolve_phase_impl(ctx, **deps)

        assert isinstance(raw2, tuple), "round 2 ends combat -> (agent, json) handoff"
        _agent, json_str = raw2
        assert json.loads(json_str)["outcome"] == "deescalated"
        assert ctx.userdata.combat_state is None
        deps["mutations"].delete_combat_state.assert_awaited_once()
