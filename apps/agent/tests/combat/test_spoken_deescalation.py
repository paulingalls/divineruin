from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import FixedRng, make_context
from voice_condition_fixtures import _DIPLOMAT, _decl, _make_group_state, participant, spatial_record

import combat_resolution
from combat_deescalation import MAX_DEESCALATION_ROUNDS, _resolve_deescalation_packet
from combat_phase import advance_combat_phase
from conditions import apply_condition
from session_data import CombatState


@pytest.mark.asyncio
@pytest.mark.parametrize("restriction", ["deafened", "silence"])
async def test_partial_hearing_group_cannot_end_combat(restriction):
    state = _make_group_state(tags_a=(), tags_b=())
    if restriction == "deafened":
        participant(state, "enemy_b").conditions = apply_condition([], "deafened", source="test")
    else:
        spatial_record(state)["positions"]["enemy_b"]["x"] = 100
        spatial_record(state)["zones"]["quiet"] = {"kind": "silence", "center_id": "enemy_b", "radius_ft": 5}
    state.deescalation_scene.enemy_dispositions["enemy_a"] = "unfriendly"
    state.deescalation_scene.cumulative_shift["enemy_a"] = combat_resolution.SURRENDER_THRESHOLD - 1
    state = CombatState.from_dict(state.to_dict())
    session = make_context().userdata
    session.combat_state = state
    persistence = MagicMock(update_player_resources=AsyncMock())
    result = await _resolve_deescalation_packet(
        session,
        participant(state, "player_1"),
        _decl(),
        state=state,
        conn=None,
        player=_DIPLOMAT,
        persistence=persistence,
        rng=FixedRng(20),
    )
    assert state.deescalated is False
    assert set(state.deescalation_scene.cumulative_shift) == {"enemy_a"}
    assert state.deescalation_scene.cumulative_shift["enemy_a"] >= combat_resolution.SURRENDER_THRESHOLD
    assert [row["id"] for row in result["deescalation"]["per_enemy"]] == ["enemy_a"]
    assert result["deescalation"]["per_enemy"][0]["surrendered"] is True
    assert result["deescalation"]["ends_combat"] is False
    persistence.update_player_resources.assert_awaited_once()


@pytest.mark.parametrize("entry", ["declaration", "resolution"])
@pytest.mark.parametrize("restriction", ["deafened", "source", "silence", "placement"])
@pytest.mark.asyncio
async def test_all_ineligible_refuses_before_cost_roll_or_scene(entry, restriction):
    state = _make_group_state()
    if restriction == "deafened":
        for enemy in state.participants[1:]:
            enemy.conditions = apply_condition([], "deafened", source="test")
    elif restriction == "source":
        spatial_record(state)["positions"]["player_1"]["x"] = 100
        spatial_record(state)["zones"]["quiet"] = {"kind": "silence", "center_id": "player_1", "radius_ft": 5}
    elif restriction == "silence":
        spatial_record(state)["positions"]["player_1"]["x"] = 100
        spatial_record(state)["zones"]["quiet"] = {"kind": "silence", "center_id": "enemy_a", "radius_ft": 5}
    else:
        del spatial_record(state)["positions"]["enemy_a"]
    before = state.to_dict()
    session = make_context().userdata
    session.combat_state = state
    persistence = MagicMock(update_player_resources=AsyncMock())
    with patch(
        "combat_deescalation.check_resolution.resolve_skill_check_dc", side_effect=AssertionError("rolled")
    ) as roll:
        with pytest.raises((ValueError, ToolError), match=r"hear|eligible|speak|spatial"):
            if entry == "declaration":
                advance_combat_phase(state, declarations={"player_1": {"type": "ability", "action": "de_escalate"}})
            else:
                await _resolve_deescalation_packet(
                    session,
                    participant(state, "player_1"),
                    _decl(),
                    state=state,
                    conn=None,
                    player=_DIPLOMAT,
                    persistence=persistence,
                    rng=FixedRng(20),
                )
    assert state.to_dict() == before
    persistence.update_player_resources.assert_not_awaited()
    roll.assert_not_called()


@pytest.mark.asyncio
async def test_two_packets_at_last_permitted_round_share_phase_cap():
    pristine = _make_group_state()
    pristine.deescalation_scene.round_counter = MAX_DEESCALATION_ROUNDS - 1
    state = CombatState.from_dict(pristine.to_dict())
    session = make_context().userdata
    session.combat_state = pristine
    persistence = MagicMock(update_player_resources=AsyncMock())
    for _ in range(2):
        result = await _resolve_deescalation_packet(
            session,
            participant(state, "player_1"),
            _decl(),
            state=state,
            conn=None,
            player=_DIPLOMAT,
            persistence=persistence,
            rng=FixedRng(1),
        )
        assert result["resolved"] is True
    assert persistence.update_player_resources.await_count == 2
    assert state.deescalation_scene.round_counter == MAX_DEESCALATION_ROUNDS
    assert pristine.deescalation_scene.round_counter == MAX_DEESCALATION_ROUNDS - 1
