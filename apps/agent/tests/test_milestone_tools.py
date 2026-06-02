"""Tests for resolve_milestone (milestone_tools.py).

Drives the tool's _impl directly with a mock RunContext + injected mock
queries/persistence/flags/events mods. The seed_milestones autouse fixture
(conftest) supplies the real milestone map from content/archetype_milestones.json,
so get_archetype_milestones resolves the L5 fork / L10-L20 auto-grants.

resolve_milestone derives the milestone from the player's archetype (player["class"])
and current level: L5 presents/persists the immutable specialization choice; L10/15/20
auto-grant, setting the grant's combat flag (e.g. extra_attack) when present. Mirrors
the request_ability_activation tool + transaction pattern.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import make_context, make_db_mod, make_mock_room

import event_types as E
from milestone_tools import _resolve_milestone_impl


def _player(*, class_: str = "warrior", level: int = 5, specialization: str | None = None) -> dict:
    p = {"player_id": "player_1", "name": "Kael", "class": class_, "level": level}
    if specialization is not None:
        p["specialization"] = specialization
    return p


async def _call(choice=None, *, player: dict | None = None, room=None):
    """Invoke the impl with mock db/queries/persistence/flags/events.

    Returns (parsed_result, mocks) where mocks exposes .queries/.persistence/
    .flags/.events and .conn (the connection transaction() yielded).
    """
    ctx = make_context(room=room)
    mock_db, conn = make_db_mod()
    queries = MagicMock()
    queries.get_player = AsyncMock(return_value=player if player is not None else _player())
    persistence = MagicMock()
    persistence.set_player_specialization = AsyncMock()
    flags = MagicMock()
    flags.set_player_flag = AsyncMock()
    events = MagicMock()
    events.publish_game_event = AsyncMock()
    raw = await _resolve_milestone_impl(
        ctx,
        choice,
        db_mod=mock_db,
        queries_mod=queries,
        persistence_mod=persistence,
        flags_mod=flags,
        events_mod=events,
    )
    mocks = MagicMock()
    mocks.queries = queries
    mocks.persistence = persistence
    mocks.flags = flags
    mocks.events = events
    mocks.conn = conn
    return json.loads(raw), mocks


class TestL5Fork:
    async def test_no_choice_presents_options_and_emits_event(self):
        room = make_mock_room()
        result, mocks = await _call(player=_player(class_="warrior", level=5), room=room)
        assert result["requires_choice"] is True
        assert len(result["options"]) == 2
        assert result["narration_cue"]
        # No persistence on the present-options path.
        mocks.persistence.set_player_specialization.assert_not_called()
        # SPECIALIZATION_CHOICE emitted for the HUD with the two options.
        mocks.events.publish_game_event.assert_awaited_once()
        args = mocks.events.publish_game_event.call_args.args
        assert args[1] == E.SPECIALIZATION_CHOICE
        assert len(args[2]["options"]) == 2

    async def test_valid_choice_persists_immutably(self):
        result, mocks = await _call("warrior_battle_master", player=_player(class_="warrior", level=5))
        assert result["chosen"] == "warrior_battle_master"
        assert result["narration_cue"]
        mocks.persistence.set_player_specialization.assert_awaited_once()
        args = mocks.persistence.set_player_specialization.call_args.args
        assert args[1] == "warrior_battle_master"
        # A locked-in choice is silent on the HUD — no SPECIALIZATION_CHOICE event.
        mocks.events.publish_game_event.assert_not_awaited()

    async def test_valid_choice_threads_locked_transaction_conn(self):
        # Atomicity guarantee (concern 598dceba2f3e): the FOR-UPDATE read and the
        # specialization write share the one transaction() conn, so the choice
        # commits with its lock. Pin the conn threading, not just the args.
        _, mocks = await _call("warrior_battle_master", player=_player(class_="warrior", level=5))
        assert mocks.queries.get_player.call_args.kwargs["conn"] is mocks.conn
        assert mocks.persistence.set_player_specialization.call_args.kwargs["conn"] is mocks.conn

    async def test_already_set_rejects_without_writing(self):
        with pytest.raises(ToolError, match="already"):
            await _call(
                "warrior_battle_master",
                player=_player(class_="warrior", level=5, specialization="warrior_berserker"),
            )

    async def test_already_set_does_not_persist(self):
        ctx = make_context()
        mock_db, _conn = make_db_mod()
        queries = MagicMock()
        queries.get_player = AsyncMock(
            return_value=_player(class_="warrior", level=5, specialization="warrior_berserker")
        )
        persistence = MagicMock()
        persistence.set_player_specialization = AsyncMock()
        flags = MagicMock()
        flags.set_player_flag = AsyncMock()
        events = MagicMock()
        events.publish_game_event = AsyncMock()
        with pytest.raises(ToolError):
            await _resolve_milestone_impl(
                ctx,
                "warrior_battle_master",
                db_mod=mock_db,
                queries_mod=queries,
                persistence_mod=persistence,
                flags_mod=flags,
                events_mod=events,
            )
        persistence.set_player_specialization.assert_not_called()

    async def test_invalid_choice_rejects(self):
        with pytest.raises(ToolError, match="Invalid"):
            await _call("not_a_real_option", player=_player(class_="warrior", level=5))

    async def test_patron_deferred_rejects(self):
        # Cleric L5 is patron-deferred (Phase 8 stub) — no concrete options.
        with pytest.raises(ToolError, match="patron"):
            await _call(player=_player(class_="cleric", level=5))


class TestAutoGrant:
    async def test_l10_warrior_sets_extra_attack_flag(self):
        result, mocks = await _call(player=_player(class_="warrior", level=10))
        assert result["flag"] == "extra_attack"
        assert result["grant"]["name"] == "Extra Attack"
        assert result["narration_cue"]
        mocks.flags.set_player_flag.assert_awaited_once()
        args = mocks.flags.set_player_flag.call_args.args
        assert args[1] == "extra_attack"
        assert args[2] is True
        # Auto-grants are silent on the HUD — no SPECIALIZATION_CHOICE event.
        mocks.events.publish_game_event.assert_not_awaited()
        # Flag write shares the FOR-UPDATE read's transaction conn (concern 598dceba2f3e).
        assert mocks.flags.set_player_flag.call_args.kwargs["conn"] is mocks.conn

    async def test_l10_guardian_narrative_grant_writes_no_flag(self):
        # Guardian L10 is Shield Mastery (flag=null) — narrative grant, Phase-4-deferred.
        result, mocks = await _call(player=_player(class_="guardian", level=10))
        assert result["flag"] is None
        assert result["grant"]["name"]
        assert result["narration_cue"]
        mocks.flags.set_player_flag.assert_not_called()
        # Narrative-only grants stay silent on the HUD too.
        mocks.events.publish_game_event.assert_not_awaited()

    async def test_l20_legend_emits_no_hud_event(self):
        _, mocks = await _call(player=_player(class_="warrior", level=20))
        mocks.events.publish_game_event.assert_not_awaited()

    async def test_l20_legend_returns_narration(self):
        result, _ = await _call(player=_player(class_="warrior", level=20))
        assert result["grant"]["name"] == "Legendary Action"
        assert result["narration_cue"]


class TestWriteFailure:
    async def test_persistence_failure_propagates_and_emits_no_event(self):
        # A failing specialization write must abort the resolution (the real
        # db.transaction() rolls back — concern 598dceba2f3e; true DB rollback is
        # proven by the story-006 capstone) and never emit the HUD event.
        ctx = make_context(room=make_mock_room())
        mock_db, _conn = make_db_mod()
        queries = MagicMock()
        queries.get_player = AsyncMock(return_value=_player(class_="warrior", level=5))
        persistence = MagicMock()
        persistence.set_player_specialization = AsyncMock(side_effect=RuntimeError("db down"))
        flags = MagicMock()
        flags.set_player_flag = AsyncMock()
        events = MagicMock()
        events.publish_game_event = AsyncMock()
        with pytest.raises(RuntimeError):
            await _resolve_milestone_impl(
                ctx,
                "warrior_battle_master",
                db_mod=mock_db,
                queries_mod=queries,
                persistence_mod=persistence,
                flags_mod=flags,
                events_mod=events,
            )
        events.publish_game_event.assert_not_awaited()


class TestNoMilestone:
    async def test_level_with_no_milestone_rejects(self):
        with pytest.raises(ToolError, match="milestone"):
            await _call(player=_player(class_="warrior", level=7))

    async def test_missing_class_derives_no_milestone_and_rejects(self):
        # player["class"] absent -> get_archetype_milestones(None) -> () -> ToolError.
        # The fail-loud derivation path, distinct from a valid class at an off-level.
        player = {"player_id": "player_1", "name": "Kael", "level": 5}
        with pytest.raises(ToolError, match="milestone"):
            await _call(player=player)
