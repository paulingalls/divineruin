import copy
from unittest.mock import AsyncMock, patch

import pytest
from combat._helpers import _ctx_at_resolution, _make_combat_state, _resolve_deps, _resolve_round
from livekit.agents.llm import ToolError

import combat_prompts
import combat_turn
import conditions
from combat_support import _participant_summary
from combat_wrap import next_envelope
from declaration_payloads import ManeuverDecl
from session_data import CombatParticipant, CombatState


def _prone(source="test"):
    return conditions.apply_condition([], "prone", source=source)


def _packet(result, actor_id):
    return next(packet for packet in result["packets"] if packet["actor_id"] == actor_id)


def _participant(state: CombatState, participant_id: str) -> CombatParticipant:
    participant = state.get_participant(participant_id)
    assert participant is not None
    return participant


def _maneuver_state(actor_id, target_id):
    state = _make_combat_state(player_hp=25, enemy_hp=20)
    state.beat = "resolution"
    other_id = "goblin_scout_1" if actor_id == "player_1" else "player_1"
    state.pending_declarations = {
        actor_id: {"type": "maneuver", "target_id": target_id},
        other_id: {"type": "defend"},
    }
    return state


@pytest.mark.asyncio
@pytest.mark.parametrize("actor_id", ["player_1", "goblin_scout_1"])
async def test_prone_actor_stands_as_their_whole_declaration(actor_id):
    state = _maneuver_state(actor_id, actor_id)
    actor = _participant(state, actor_id)
    actor.conditions = _prone()
    ctx = _ctx_at_resolution(state=state)

    result = await _resolve_round(ctx, **_resolve_deps())

    assert _packet(result, actor_id) == {
        "actor_id": actor_id,
        "resolved": True,
        "declaration_type": "maneuver",
        "stood_up": True,
    }
    final_state = ctx.userdata.combat_state
    assert final_state is not None
    assert not conditions.has_condition(_participant(final_state, actor_id).conditions, "prone")
    assert ctx.userdata.combat_state.open_window is None


@pytest.mark.asyncio
async def test_non_prone_self_maneuver_is_refused_at_declaration():
    state = _make_combat_state()
    ctx = _ctx_at_resolution(state=state)
    state.beat = "declaration"
    mutations = AsyncMock()

    with pytest.raises(ToolError, match="Kael"):
        await combat_turn._declare_phase_impl(
            ctx,
            {"player_1": {"type": "maneuver", "target_id": "player_1"}},
            mutations=mutations,
        )

    mutations.save_combat_state.assert_not_awaited()


@pytest.mark.asyncio
async def test_stale_self_maneuver_fails_loud_if_prone_vanished_before_resolution():
    state = _maneuver_state("player_1", "player_1")
    ctx = _ctx_at_resolution(state=state)

    with pytest.raises(ValueError, match="Kael"):
        await _resolve_round(ctx, **_resolve_deps())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("rolls", "expected"),
    [([18, 3], "knocked_prone"), ([11, 10], "resisted"), ([3, 18], "resisted")],
)
async def test_shove_contest_ties_to_target_and_only_a_win_lands_prone(rolls, expected):
    state = _maneuver_state("player_1", "goblin_scout_1")
    actor = _participant(state, "player_1")
    target = _participant(state, "goblin_scout_1")
    actor.attributes = {"strength": 14, "dexterity": 10}
    target.attributes = {"strength": 10, "dexterity": 16}
    ctx = _ctx_at_resolution(state=state)

    with patch("random.randint", side_effect=rolls) as randint:
        result = await _resolve_round(ctx, **_resolve_deps())

    packet = _packet(result, actor.id)
    assert packet["shove"] == expected
    assert packet["target"] == target.name
    assert packet["actor_total"] == rolls[0] + 2
    assert packet["target_total"] == rolls[1] + 3
    final_state = ctx.userdata.combat_state
    assert final_state is not None
    final_target = _participant(final_state, target.id)
    assert conditions.has_condition(final_target.conditions, "prone") is (expected == "knocked_prone")
    assert randint.call_count == 2


@pytest.mark.asyncio
async def test_shoving_an_already_prone_target_rolls_nothing_and_carries_no_totals():
    state = _maneuver_state("player_1", "goblin_scout_1")
    target = _participant(state, "goblin_scout_1")
    target.conditions = _prone()
    ctx = _ctx_at_resolution(state=state)

    with patch("random.randint") as randint:
        result = await _resolve_round(ctx, **_resolve_deps())

    packet = _packet(result, "player_1")
    assert packet["shove"] == "already_prone"
    assert "actor_total" not in packet
    assert "target_total" not in packet
    assert [condition["type"] for condition in target.conditions].count("prone") == 1
    randint.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("target_state", ["missing", "fallen"])
async def test_shove_refuses_a_target_that_cannot_be_contested(target_state):
    state = _maneuver_state("player_1", "goblin_scout_1")
    target = _participant(state, "goblin_scout_1")
    if target_state == "missing":
        state.participants.remove(target)
    else:
        target.is_fallen = True
        other = copy.deepcopy(target)
        other.id = "goblin_scout_2"
        other.name = "Other Goblin"
        other.is_fallen = False
        state.participants.append(other)
        state.initiative_order.append(other.id)
    ctx = _ctx_at_resolution(state=state)

    with patch("random.randint") as randint:
        result = await _resolve_round(ctx, **_resolve_deps())

    packet = _packet(result, "player_1")
    assert packet["resolved"] is False
    assert "target" in packet["reason"] or "fell" in packet["reason"]
    randint.assert_not_called()


def test_prone_state_and_maneuver_vocabulary_reach_the_dm():
    state = _make_combat_state()
    player = _participant(state, "player_1")
    player.conditions = _prone()

    assert _participant_summary(player)["prone"] is True
    assert next_envelope(state)["prone"] == [{"actor_id": player.id, "name": player.name}]
    description = ManeuverDecl.model_json_schema()["properties"]["target_id"]["description"]
    assert description == (
        "Shove a target (contested Strength; a win knocks them prone), or target yourself to stand up from prone."
    )
    prompt = combat_prompts.COMBAT_PROMPT
    assert "stands by declaring maneuver" in prompt
    assert "maneuver on anyone else is a shove" in prompt
    assert all(key in prompt for key in ("stood_up", "shove", "prone_immunity"))
    assert "resisted a knockdown.\n\nnext.verbs" in prompt


def test_a_fallen_prone_combatant_is_not_offered_a_stand():
    state = _make_combat_state(enemy_fallen=True)
    _participant(state, "goblin_scout_1").conditions = _prone()

    assert next_envelope(state)["prone"] == []
