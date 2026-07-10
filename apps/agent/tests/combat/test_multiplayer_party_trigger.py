"""E2E acceptance (M18 story-001): a live 2nd-player LiveKit join produces a >1-member party
that combat_init then builds into two player CombatParticipants, each carrying its own
per-member session state.

This is the story's declared acceptance path (AC4). It exercises the full seam the story ships:
the participant-join trigger (participant_lifecycle._setup_party_join) appends + hydrates a
PartyMember, and combat_init (_start_combat_impl) loops session.party.member_ids to build one
type="player" participant per member. The unit suites cover each half in isolation
(tests/session_lifecycle/test_party_join.py, tests/combat/test_combat_init_multiplayer.py); this
drives them end-to-end: player B joins, then both enter combat together.
"""

import asyncio
import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sample_fixtures import make_context

from combat_init import _start_combat_impl
from participant_lifecycle import _setup_party_join
from tests.combat.test_start_combat import SAMPLE_PLAYER, _make_start_combat_mocks


def _recording_room():
    """A room stub whose .on(event) records the decorated handler by event name, so the test can
    invoke the registered participant_connected callback directly (mirrors test_party_join.py)."""
    room = MagicMock()
    handlers: dict = {}

    def _on(event):
        def _register(fn):
            handlers[event] = fn
            return fn

        return _register

    room.on.side_effect = _on
    return room, handlers


def _joiner_row():
    """player_2's players.data row — carries BOTH what the join trigger reads (divine_favor.patron)
    and what combat_init reads (hp / equipment / attributes), so one row drives the whole flow."""
    row = copy.deepcopy(SAMPLE_PLAYER)
    row["player_id"] = "player_2"
    row["name"] = "Bren"
    row["hp"] = {"current": 18, "max": 18}
    row["equipment"] = {
        "main_hand": {"name": "Battleaxe", "damage": "1d8", "damage_type": "slashing", "properties": []}
    }
    row["divine_favor"] = {"patron": "syrath"}
    return row


def _join_mods(row):
    queries = MagicMock()
    queries.get_player = AsyncMock(return_value=row)
    res_mod = MagicMock()
    res_mod.read_player_resonance = AsyncMock(return_value={"current": 6, "flickering_bonus": 1, "state": "flickering"})
    conc_mod = MagicMock()
    conc_mod.read_player_concentration = AsyncMock(return_value={"spell_id": "spell_y"})
    return queries, res_mod, conc_mod


async def _drain():
    pending = asyncio.all_tasks() - {asyncio.current_task()}
    if pending:
        await asyncio.gather(*pending)


@pytest.mark.asyncio
async def test_second_player_joins_then_both_enter_combat_as_participants():
    # --- Arrange: a solo session for the primary, sitting in a corrupted room ---
    ctx = make_context()  # SessionData for player_1, solo party
    ctx.userdata.corruption_level = 4
    row2 = _joiner_row()
    join_queries, res_mod, conc_mod = _join_mods(row2)

    # --- Act 1: player_2 connects to the room -> the join trigger appends + hydrates them ---
    room, handlers = _recording_room()
    _setup_party_join(
        room,
        ctx.userdata,
        queries=join_queries,
        resonance_mod=res_mod,
        concentration_mod=conc_mod,
    )
    handlers["participant_connected"](SimpleNamespace(identity="player_2"))
    await _drain()

    # The party is now >1 member and player_2 carries its OWN per-member state (all five substates).
    assert ctx.userdata.party.member_ids == ["player_1", "player_2"]
    joined = ctx.userdata.party.member("player_2")
    assert joined is not None
    assert joined.resonance.current == 6
    assert joined.concentration.spell_id == "spell_y"
    assert joined.patron_id == "syrath"  # per-member, from player_2's own row
    assert joined.corruption_level == 4  # co-located with the party's location

    # --- Act 2: the 2-member party enters combat together ---
    mock_mutations, mock_queries, mock_content = _make_start_combat_mocks()
    mock_queries.get_players_for_update = AsyncMock(return_value={"player_2": row2})
    await _start_combat_impl(
        ctx,
        encounter_id="goblin_patrol",
        encounter_description="A goblin patrol.",
        mutations=mock_mutations,
        queries=mock_queries,
        content=mock_content,
    )

    # --- Assert: both members are player CombatParticipants ---
    mock_mutations.save_combat_state.assert_called_once()
    state_dict = mock_mutations.save_combat_state.call_args[0][1]
    players = [p for p in state_dict["participants"] if p["type"] == "player"]
    assert {p["id"] for p in players} == {"player_1", "player_2"}
    assert next(p for p in players if p["id"] == "player_2")["name"] == "Bren"
    # non-primary member row loaded via the ONE batched fetch, not a serial get_player
    mock_queries.get_players_for_update.assert_awaited_once()
