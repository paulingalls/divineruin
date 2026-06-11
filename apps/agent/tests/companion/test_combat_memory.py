"""Tests for companion participation in combat and memory recording from tools."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sample_fixtures import mock_txn

from session_data import CombatParticipant, CombatState, CompanionState, SessionData


def _make_context(player_id="player_1", location_id="accord_guild_hall", room=None):
    ctx = MagicMock()
    ctx.userdata = SessionData(player_id=player_id, location_id=location_id, room=room)
    return ctx


SAMPLE_PLAYER = {
    "player_id": "player_1",
    "name": "Hero",
    "level": 1,
    "attributes": {
        "strength": 14,
        "dexterity": 12,
        "constitution": 13,
        "intelligence": 10,
        "wisdom": 11,
        "charisma": 8,
    },
    "hp": {"current": 25, "max": 25},
    "ac": 14,
}

SAMPLE_ENCOUNTER = {
    "id": "goblin_patrol",
    "name": "Goblin Patrol",
    "enemies": [
        {
            "id": "goblin_1",
            "name": "Goblin Scout",
            "level": 1,
            "ac": 13,
            "hp": 7,
            "attributes": {"strength": 8, "dexterity": 14},
            "action_pool": [{"name": "Scimitar", "damage": "1d6", "damage_type": "slashing", "properties": []}],
            "xp_value": 50,
        }
    ],
}


class TestCompanionInCombat:
    @pytest.mark.asyncio
    async def test_start_combat_includes_companion(self):
        from combat_init import _start_combat_impl

        mock_mutations = MagicMock()
        mock_mutations.save_combat_state = AsyncMock()
        mock_queries = MagicMock()
        mock_queries.get_player = AsyncMock(return_value=SAMPLE_PLAYER)
        mock_content = MagicMock()
        mock_content.get_encounter_template = AsyncMock(return_value=SAMPLE_ENCOUNTER)

        ctx = _make_context()
        ctx.userdata.companion = CompanionState(id="companion_kael", name="Kael")

        raw = await _start_combat_impl(
            ctx,
            encounter_id="goblin_patrol",
            encounter_description="Fight!",
            mutations=mock_mutations,
            queries=mock_queries,
            content=mock_content,
        )
        _, json_str = raw
        result = json.loads(json_str)

        assert len(result["participants"]) == 3
        companion_p = next(p for p in result["participants"] if p["name"] == "Kael")
        assert companion_p["type"] == "companion"
        assert companion_p["ac"] == 15  # Kael profile AC at L1 (steps to 17 at L10)
        # Stats come from the companions.json profile scaler, not npcs.json: at the player's
        # level 1 / max HP 25, Kael's hp = floor(25 * 0.75 hp_factor) = 18.
        cs = ctx.userdata.combat_state
        kael_p = cs.get_participant("companion_kael")
        assert kael_p is not None
        assert kael_p.hp_current == 18
        assert kael_p.hp_max == 18

    @pytest.mark.asyncio
    async def test_start_combat_no_companion_when_absent(self):
        from combat_init import _start_combat_impl

        mock_mutations = MagicMock()
        mock_mutations.save_combat_state = AsyncMock()
        mock_queries = MagicMock()
        mock_queries.get_player = AsyncMock(return_value=SAMPLE_PLAYER)
        mock_content = MagicMock()
        mock_content.get_encounter_template = AsyncMock(return_value=SAMPLE_ENCOUNTER)

        ctx = _make_context()

        _, json_str = await _start_combat_impl(
            ctx,
            encounter_id="goblin_patrol",
            encounter_description="Fight!",
            mutations=mock_mutations,
            queries=mock_queries,
            content=mock_content,
        )
        result = json.loads(json_str)

        assert len(result["participants"]) == 2

    @pytest.mark.asyncio
    async def test_start_combat_no_companion_when_unconscious(self):
        from combat_init import _start_combat_impl

        mock_mutations = MagicMock()
        mock_mutations.save_combat_state = AsyncMock()
        mock_queries = MagicMock()
        mock_queries.get_player = AsyncMock(return_value=SAMPLE_PLAYER)
        mock_content = MagicMock()
        mock_content.get_encounter_template = AsyncMock(return_value=SAMPLE_ENCOUNTER)

        ctx = _make_context()
        ctx.userdata.companion = CompanionState(id="companion_kael", name="Kael", is_conscious=False)

        _, json_str = await _start_combat_impl(
            ctx,
            encounter_id="goblin_patrol",
            encounter_description="Fight!",
            mutations=mock_mutations,
            queries=mock_queries,
            content=mock_content,
        )
        result = json.loads(json_str)

        assert len(result["participants"]) == 2

    @pytest.mark.asyncio
    async def test_companion_ko_sets_unconscious(self):
        from combat_turn import _resolve_enemy_turn_impl

        mock_mutations = MagicMock()
        mock_mutations.save_combat_state = AsyncMock()

        ctx = _make_context()
        ctx.userdata.companion = CompanionState(id="companion_kael", name="Kael")

        # Build combat state with companion at 1 HP
        cs = CombatState(
            combat_id="combat_test",
            participants=[
                CombatParticipant(
                    id="player_1", name="Hero", type="player", initiative=15, hp_current=25, hp_max=25, ac=14
                ),
                CombatParticipant(
                    id="goblin_1",
                    name="Goblin",
                    type="enemy",
                    initiative=12,
                    hp_current=7,
                    hp_max=7,
                    ac=13,
                    action_pool=[{"name": "Scimitar", "damage": "1d6", "damage_type": "slashing", "properties": []}],
                ),
                CombatParticipant(
                    id="companion_kael",
                    name="Kael",
                    type="companion",
                    initiative=10,
                    hp_current=1,
                    hp_max=22,
                    ac=15,
                    action_pool=[{"name": "Longsword", "damage": "1d8", "damage_type": "slashing", "properties": []}],
                ),
            ],
            initiative_order=["player_1", "goblin_1", "companion_kael"],
        )
        ctx.userdata.combat_state = cs

        result = json.loads(
            await _resolve_enemy_turn_impl(
                ctx,
                enemy_id="goblin_1",
                action_name="Scimitar",
                target_id="companion_kael",
                mutations=mock_mutations,
            )
        )

        if result["hit"]:
            assert ctx.userdata.companion.is_conscious is False
            assert "knocked unconscious" in ctx.userdata.companion.session_memories[-1]


class TestCompanionMemoryInTools:
    @pytest.mark.asyncio
    async def test_move_player_records_memory(self):
        from movement_tools import _move_player_impl

        mock_db = MagicMock()
        mock_conn = MagicMock()
        mock_db.transaction = lambda: mock_txn(mock_conn)
        mock_db.extract_exit_connections = MagicMock(return_value=[])
        mock_mutations = MagicMock()
        mock_mutations.update_player_location = AsyncMock()
        mock_mutations.upsert_map_progress = AsyncMock()
        mock_queries = MagicMock()
        mock_queries.get_player = AsyncMock(return_value=SAMPLE_PLAYER)
        mock_queries.get_npcs_at_location = AsyncMock(return_value=[])
        mock_queries.get_npc_dispositions = AsyncMock(return_value={})
        mock_queries.get_targets_at_location = AsyncMock(return_value=[])
        mock_content = MagicMock()
        mock_content.get_location = AsyncMock(
            side_effect=[
                {"id": "guild", "name": "Guild Hall", "exits": {"south": {"destination": "market"}}},
                {
                    "id": "market",
                    "name": "Market Square",
                    "description": "Busy market",
                    "atmosphere": "lively",
                    "exits": {},
                },
                {
                    "id": "market",
                    "name": "Market Square",
                    "description": "Busy market",
                    "atmosphere": "lively",
                    "exits": {},
                },
            ]
        )

        ctx = _make_context()
        ctx.userdata.companion = CompanionState(id="companion_kael", name="Kael")

        with patch("movement_tools.publish_game_event", new_callable=AsyncMock):
            await _move_player_impl(
                ctx,
                destination_id="market",
                db_mod=mock_db,
                mutations=mock_mutations,
                queries=mock_queries,
                content=mock_content,
            )

        assert any("Market Square" in m for m in ctx.userdata.companion.session_memories)
