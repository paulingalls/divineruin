"""Integration coverage: combat init builds one CombatParticipant PER party member (M14
story-003). Today combat_init always builds a single type="player" participant from
session.player_id; this suite locks in the multiplayer loop over session.party.member_ids
while guaranteeing a solo (1-member) party still produces a byte-identical single-player
build. Models test_combat_init_roles.py — mock mutations/queries/content DI, no real DB.
"""

import copy
from unittest.mock import AsyncMock

import pytest
from sample_fixtures import make_context

from caster_state import ConcentrationState, ResonanceTrack
from combat_init import _start_combat_impl
from party_state import PartyMember
from tests.combat.test_start_combat import SAMPLE_PLAYER, _make_start_combat_mocks


def _second_member_row():
    row = copy.deepcopy(SAMPLE_PLAYER)
    row["player_id"] = "player_2"
    row["name"] = "Bren"
    row["hp"] = {"current": 18, "max": 18}
    row["equipment"] = {
        "main_hand": {
            "name": "Battleaxe",
            "damage": "1d8",
            "damage_type": "slashing",
            "properties": [],
        }
    }
    return row


def _add_second_member(ctx, player_id="player_2"):
    ctx.userdata.party.members.append(
        PartyMember(
            player_id=player_id,
            resonance=ResonanceTrack(),
            concentration=ConcentrationState(),
        )
    )


def _mock_non_primary_batch(mock_queries, rows_by_id):
    """Mock the batched non-primary fetch: combat_init loads every non-primary member in ONE
    get_players_for_update(non_primary_ids) call returning {player_id: row}, not N serial
    get_player round-trips. The primary still rides the already-fetched get_player row."""
    mock_queries.get_players_for_update = AsyncMock(return_value=rows_by_id)


async def _run(ctx, mock_mutations, mock_queries, mock_content):
    await _start_combat_impl(
        ctx,
        encounter_id="goblin_patrol",
        encounter_description="A goblin patrol.",
        mutations=mock_mutations,
        queries=mock_queries,
        content=mock_content,
    )
    mock_mutations.save_combat_state.assert_called_once()
    _combat_id, state_dict = mock_mutations.save_combat_state.call_args[0]
    return state_dict


@pytest.mark.asyncio
async def test_two_member_party_builds_two_player_participants():
    mock_mutations, mock_queries, mock_content = _make_start_combat_mocks()
    ctx = make_context()
    _add_second_member(ctx)
    row2 = _second_member_row()
    _mock_non_primary_batch(mock_queries, {"player_2": row2})

    state_dict = await _run(ctx, mock_mutations, mock_queries, mock_content)
    players = [p for p in state_dict["participants"] if p["type"] == "player"]
    assert {p["id"] for p in players} == {"player_1", "player_2"}
    assert len({p["initiative"] for p in players}) <= 2  # each rolled its own initiative
    p1 = next(p for p in players if p["id"] == "player_1")
    p2 = next(p for p in players if p["id"] == "player_2")
    assert p2["name"] == "Bren"
    assert p2["hp_max"] == 18
    assert p1["hp_max"] == SAMPLE_PLAYER["hp"]["max"]


@pytest.mark.asyncio
async def test_non_primary_members_fetched_in_one_batched_call():
    """The non-primary rows load via a SINGLE get_players_for_update(non_primary_ids) call,
    not a serial get_player per member — and the primary is never re-fetched through the batch."""
    mock_mutations, mock_queries, mock_content = _make_start_combat_mocks()
    ctx = make_context()
    _add_second_member(ctx)
    _mock_non_primary_batch(mock_queries, {"player_2": _second_member_row()})

    await _run(ctx, mock_mutations, mock_queries, mock_content)

    mock_queries.get_players_for_update.assert_called_once_with(["player_2"])
    # player_2 rides the batch; only the primary is fetched via get_player (no serial 2nd query).
    fetched_ids = [call.args[0] for call in mock_queries.get_player.call_args_list]
    assert "player_2" not in fetched_ids
    assert fetched_ids == ["player_1"]


@pytest.mark.asyncio
async def test_solo_party_builds_exactly_one_player_participant():
    mock_mutations, mock_queries, mock_content = _make_start_combat_mocks()
    ctx = make_context()

    state_dict = await _run(ctx, mock_mutations, mock_queries, mock_content)
    players = [p for p in state_dict["participants"] if p["type"] == "player"]
    assert len(players) == 1
    assert players[0]["id"] == "player_1"
    assert "player_1" in state_dict["initiative_order"]
    # Byte-identical solo path: an empty non-primary set skips the batch query entirely.
    mock_queries.get_players_for_update.assert_not_called()


@pytest.mark.asyncio
async def test_only_member_with_exhausted_stack_carries_capped_condition():
    mock_mutations, mock_queries, mock_content = _make_start_combat_mocks()
    ctx = make_context()
    _add_second_member(ctx)
    row2 = _second_member_row()
    row2["conditions"] = [{"type": "exhausted", "stacks": 9}]
    _mock_non_primary_batch(mock_queries, {"player_2": row2})

    state_dict = await _run(ctx, mock_mutations, mock_queries, mock_content)
    players = {p["id"]: p for p in state_dict["participants"] if p["type"] == "player"}
    assert players["player_1"]["conditions"] == []
    p2_conditions = players["player_2"]["conditions"]
    assert len(p2_conditions) == 1
    assert p2_conditions[0]["type"] == "exhausted"
    assert p2_conditions[0]["stacks"] < 9  # capped, not the raw stored value


@pytest.mark.asyncio
async def test_combat_started_event_lists_both_players():
    mock_mutations, mock_queries, mock_content = _make_start_combat_mocks()
    ctx = make_context()
    _add_second_member(ctx)
    _mock_non_primary_batch(mock_queries, {"player_2": _second_member_row()})

    state_dict = await _run(ctx, mock_mutations, mock_queries, mock_content)
    assert set(state_dict["initiative_order"]) >= {"player_1", "player_2"}


@pytest.mark.asyncio
async def test_combat_init_resets_weapon_flags_for_every_member():
    # M18 story-003: the per-encounter weapon-flag reset loops EVERY member, so a non-primary
    # member's stale swing from a prior encounter can't leak into this encounter's accrual.
    mock_mutations, mock_queries, mock_content = _make_start_combat_mocks()
    ctx = make_context()
    _add_second_member(ctx)
    _mock_non_primary_batch(mock_queries, {"player_2": _second_member_row()})

    ctx.userdata.party.primary.weapon_used = True
    p2 = ctx.userdata.party.member("player_2")
    p2.weapon_used = True
    p2.weapon_crit_vs_heavy = True

    await _run(ctx, mock_mutations, mock_queries, mock_content)

    assert ctx.userdata.party.primary.weapon_used is False
    assert p2.weapon_used is False
    assert p2.weapon_crit_vs_heavy is False
