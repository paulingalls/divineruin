"""Tests for start_combat: state creation, initiative, durability reset, handoff, errors."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from combat._helpers import _make_combat_state, _make_context, _make_mock_room
from livekit.agents.llm import ToolError

import event_types as E
from combat_init import _start_combat_impl

SAMPLE_PLAYER = {
    "player_id": "player_1",
    "name": "Kael",
    "class": "warrior",
    "level": 1,
    "attributes": {
        "strength": 14,
        "dexterity": 12,
        "constitution": 13,
        "intelligence": 10,
        "wisdom": 11,
        "charisma": 8,
    },
    "proficiencies": ["athletics", "stealth", "perception"],
    "saving_throw_proficiencies": ["strength", "constitution"],
    "equipment": {
        "main_hand": {
            "name": "Longsword",
            "damage": "1d8",
            "damage_type": "slashing",
            "properties": [],
        }
    },
    "hp": {"current": 25, "max": 25},
    "ac": 14,
}

SAMPLE_ENCOUNTER = {
    "id": "goblin_patrol",
    "name": "Goblin Patrol",
    "difficulty": "easy",
    "enemies": [
        {
            "id": "goblin_scout_1",
            "name": "Goblin Scout",
            "level": 1,
            "ac": 13,
            "hp": 7,
            "attributes": {
                "strength": 8,
                "dexterity": 14,
                "constitution": 10,
                "intelligence": 10,
                "wisdom": 8,
                "charisma": 8,
            },
            "action_pool": [
                {
                    "name": "Scimitar",
                    "damage": "1d6",
                    "damage_type": "slashing",
                    "properties": ["light"],
                },
                {
                    "name": "Shortbow",
                    "damage": "1d6",
                    "damage_type": "piercing",
                    "properties": [],
                    "ranged": True,
                },
            ],
            "xp_value": 50,
        },
    ],
}


def _make_start_combat_mocks():
    """Create mock modules for start_combat DI params."""
    mock_mutations = MagicMock()
    mock_mutations.save_combat_state = AsyncMock()

    mock_queries = MagicMock()
    mock_queries.get_player = AsyncMock(return_value=SAMPLE_PLAYER)

    mock_content = MagicMock()
    mock_content.get_encounter_template = AsyncMock(return_value=SAMPLE_ENCOUNTER)
    mock_content.get_npc = AsyncMock(return_value=None)

    return mock_mutations, mock_queries, mock_content


# Thornwatch reputation ladder (mirrors content/factions.json) for the stance-gate suite.
_THORNWATCH = {
    "id": "thornwatch",
    "name": "The Thornwatch",
    "reputation_tiers": {
        "hostile": {"threshold": -10},
        "unfriendly": {"threshold": -5},
        "neutral": {"threshold": 0},
        "friendly": {"threshold": 5},
        "trusted": {"threshold": 15},
        "honored": {"threshold": 25},
    },
}


def _gated_encounter():
    # The real Ashmark Patrol stance gate: allied iff Thornwatch reputation >= friendly (5).
    return {
        **SAMPLE_ENCOUNTER,
        "id": "ashmark_patrol",
        "name": "Ashmark Patrol",
        "stance_gate": {"faction": "thornwatch", "allied_at_or_above": "friendly"},
    }


def _stance_mocks(reputation, faction=_THORNWATCH):
    mock_mutations, mock_queries, mock_content = _make_start_combat_mocks()
    mock_content.get_encounter_template = AsyncMock(return_value=_gated_encounter())
    mock_content.get_faction = AsyncMock(return_value=faction)
    mock_queries.get_player_faction_reputation = AsyncMock(return_value=reputation)
    return mock_mutations, mock_queries, mock_content


class TestStartCombatStanceGate:
    """story-008: _start_combat_impl is resolve_encounter_stance's first production caller.
    A gated encounter resolves allied (avert combat, narration string) or hostile (combat)
    from the player's reputation with the gate faction."""

    @pytest.mark.asyncio
    async def test_allied_reputation_averts_combat(self):
        mock_mutations, mock_queries, mock_content = _stance_mocks(reputation=8)  # >= friendly(5)
        ctx = _make_context()
        result = await _start_combat_impl(
            ctx,
            encounter_id="ashmark_patrol",
            encounter_description="A patrol approaches.",
            mutations=mock_mutations,
            queries=mock_queries,
            content=mock_content,
        )
        assert isinstance(result, str)  # narration, no combat handoff
        assert "stands down" in result.lower()
        assert ctx.userdata.combat_state is None
        assert ctx.userdata.in_combat is False
        mock_mutations.save_combat_state.assert_not_called()
        mock_queries.get_player_faction_reputation.assert_awaited_once_with("player_1", "thornwatch")

    @pytest.mark.asyncio
    async def test_hostile_reputation_starts_combat(self):
        mock_mutations, mock_queries, mock_content = _stance_mocks(reputation=4)  # < friendly(5)
        ctx = _make_context()
        result = await _start_combat_impl(
            ctx,
            encounter_id="ashmark_patrol",
            encounter_description="A patrol blocks the road.",
            mutations=mock_mutations,
            queries=mock_queries,
            content=mock_content,
        )
        assert isinstance(result, tuple)  # combat handoff
        assert ctx.userdata.combat_state is not None
        mock_mutations.save_combat_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_missing_reputation_defaults_to_neutral_hostile(self):
        # No player_reputation row -> None -> neutral (0) -> below friendly -> hostile.
        mock_mutations, mock_queries, mock_content = _stance_mocks(reputation=None)
        ctx = _make_context()
        result = await _start_combat_impl(
            ctx,
            encounter_id="ashmark_patrol",
            encounter_description="A patrol approaches.",
            mutations=mock_mutations,
            queries=mock_queries,
            content=mock_content,
        )
        assert isinstance(result, tuple)
        assert ctx.userdata.combat_state is not None

    @pytest.mark.asyncio
    async def test_unknown_gate_faction_fails_loud(self):
        mock_mutations, mock_queries, mock_content = _stance_mocks(reputation=8)
        mock_content.get_faction = AsyncMock(return_value=None)
        ctx = _make_context()
        with pytest.raises(ToolError):
            await _start_combat_impl(
                ctx,
                encounter_id="ashmark_patrol",
                encounter_description="...",
                mutations=mock_mutations,
                queries=mock_queries,
                content=mock_content,
            )

    @pytest.mark.asyncio
    async def test_malformed_gate_missing_faction_fails_loud(self):
        # A stance gate without a 'faction' key must raise ToolError (fail-loud to LLM),
        # not an uncaught KeyError.
        mock_mutations, mock_queries, mock_content = _stance_mocks(reputation=8)
        encounter = _gated_encounter()
        encounter["stance_gate"] = {"allied_at_or_above": "friendly"}  # no faction
        mock_content.get_encounter_template = AsyncMock(return_value=encounter)
        ctx = _make_context()
        with pytest.raises(ToolError, match="malformed stance gate"):
            await _start_combat_impl(
                ctx,
                encounter_id="ashmark_patrol",
                encounter_description="...",
                mutations=mock_mutations,
                queries=mock_queries,
                content=mock_content,
            )
        mock_content.get_faction.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_gated_encounter_skips_stance_resolution(self):
        mock_mutations, mock_queries, mock_content = _make_start_combat_mocks()  # goblin_patrol, no gate
        mock_content.get_faction = AsyncMock()
        mock_queries.get_player_faction_reputation = AsyncMock()
        ctx = _make_context()
        result = await _start_combat_impl(
            ctx,
            encounter_id="goblin_patrol",
            encounter_description="Goblins ambush!",
            mutations=mock_mutations,
            queries=mock_queries,
            content=mock_content,
        )
        assert isinstance(result, tuple)
        mock_content.get_faction.assert_not_called()
        mock_queries.get_player_faction_reputation.assert_not_called()


class TestStartCombat:
    @pytest.mark.asyncio
    async def test_creates_combat_state(self):
        mock_mutations, mock_queries, mock_content = _make_start_combat_mocks()
        ctx = _make_context()

        raw = await _start_combat_impl(
            ctx,
            encounter_id="goblin_patrol",
            encounter_description="Goblins ambush!",
            mutations=mock_mutations,
            queries=mock_queries,
            content=mock_content,
        )
        assert isinstance(raw, tuple), "start_combat success should return (CombatAgent, json_str)"
        _, json_str = raw
        result = json.loads(json_str)

        assert "combat_id" in result
        assert result["encounter_name"] == "Goblin Patrol"
        assert len(result["initiative_order"]) == 2
        assert len(result["participants"]) == 2
        assert ctx.userdata.in_combat is True
        assert ctx.userdata.combat_state is not None
        mock_mutations.save_combat_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_agent_tuple(self):
        mock_mutations, mock_queries, mock_content = _make_start_combat_mocks()
        ctx = _make_context()

        raw = await _start_combat_impl(
            ctx,
            encounter_id="goblin_patrol",
            encounter_description="Ambush!",
            mutations=mock_mutations,
            queries=mock_queries,
            content=mock_content,
        )
        assert isinstance(raw, tuple)
        assert len(raw) == 2

    @pytest.mark.asyncio
    async def test_rolls_initiative(self):
        mock_mutations, mock_queries, mock_content = _make_start_combat_mocks()
        ctx = _make_context()

        _, json_str = await _start_combat_impl(
            ctx,
            encounter_id="goblin_patrol",
            encounter_description="Ambush!",
            mutations=mock_mutations,
            queries=mock_queries,
            content=mock_content,
        )
        result = json.loads(json_str)

        for entry in result["initiative_order"]:
            assert "roll" in entry
            assert "total" in entry
            assert entry["roll"] >= 1 and entry["roll"] <= 20

    @pytest.mark.asyncio
    async def test_resets_stale_weapon_durability_flags(self):
        # A weapon swing outside combat must not leak into this encounter's
        # end-of-combat durability accrual (concern c3c95fd3af40).
        mock_mutations, mock_queries, mock_content = _make_start_combat_mocks()
        ctx = _make_context()
        ctx.userdata.weapon_used_this_encounter = True
        ctx.userdata.weapon_crit_vs_heavy = True

        await _start_combat_impl(
            ctx,
            encounter_id="goblin_patrol",
            encounter_description="Ambush!",
            mutations=mock_mutations,
            queries=mock_queries,
            content=mock_content,
        )

        assert ctx.userdata.weapon_used_this_encounter is False
        assert ctx.userdata.weapon_crit_vs_heavy is False

    @pytest.mark.asyncio
    async def test_publishes_events(self):
        mock_mutations, mock_queries, mock_content = _make_start_combat_mocks()
        room = _make_mock_room()
        ctx = _make_context(room=room)

        await _start_combat_impl(
            ctx,
            encounter_id="goblin_patrol",
            encounter_description="Ambush!",
            mutations=mock_mutations,
            queries=mock_queries,
            content=mock_content,
        )

        # Should publish combat_started and play_sound events
        assert room.local_participant.publish_data.call_count == 2
        calls = [json.loads(c[0][0]) for c in room.local_participant.publish_data.call_args_list]
        types = [c["type"] for c in calls]
        assert E.COMBAT_STARTED in types
        assert E.PLAY_SOUND in types

    @pytest.mark.asyncio
    async def test_error_if_already_in_combat(self):
        ctx = _make_context()
        ctx.userdata.combat_state = _make_combat_state()

        with pytest.raises(ToolError, match="Already in combat"):
            await _start_combat_impl(ctx, encounter_id="goblin_patrol", encounter_description="Another fight!")

    @pytest.mark.asyncio
    async def test_error_missing_encounter(self):
        mock_content = MagicMock()
        mock_content.get_encounter_template = AsyncMock(return_value=None)
        ctx = _make_context()

        with pytest.raises(ToolError, match="not found"):
            await _start_combat_impl(
                ctx, encounter_id="nonexistent", encounter_description="Nothing", content=mock_content
            )
