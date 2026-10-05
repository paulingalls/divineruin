"""A mock connection checks SQL construction, including partial-pool parameter indexing."""

import json
from unittest.mock import AsyncMock

import ability_persistence


class TestUpdatePlayerResources:
    async def test_stamina_only_writes_only_stamina_pool(self):
        conn = AsyncMock()
        await ability_persistence.update_player_resources("p1", stamina=7, conn=conn)
        sql, *params = conn.execute.call_args.args
        assert "UPDATE players" in sql
        assert "'{stamina,current}'" in sql
        assert "'{focus,current}'" not in sql  # uncosted pool never written
        assert sql.count("$2") == 1 and "$3" not in sql
        assert params[0] == "p1"
        assert json.loads(params[1]) == 7

    async def test_focus_only_binds_value_at_param_2(self):
        conn = AsyncMock()
        await ability_persistence.update_player_resources("p1", focus=4, conn=conn)
        sql, *params = conn.execute.call_args.args
        assert "'{focus,current}'" in sql
        assert "'{stamina,current}'" not in sql
        assert "$2::jsonb" in sql and "$3" not in sql
        assert params[0] == "p1"
        assert json.loads(params[1]) == 4

    async def test_both_pools_nest_jsonb_set_with_distinct_params(self):
        conn = AsyncMock()
        await ability_persistence.update_player_resources("p1", stamina=5, focus=6, conn=conn)
        sql, *params = conn.execute.call_args.args
        assert "'{stamina,current}'" in sql and "'{focus,current}'" in sql
        assert "$2::jsonb" in sql and "$3::jsonb" in sql
        assert params[0] == "p1"
        assert json.loads(params[1]) == 5
        assert json.loads(params[2]) == 6

    async def test_no_pools_is_a_noop(self):
        conn = AsyncMock()
        await ability_persistence.update_player_resources("p1", conn=conn)
        conn.execute.assert_not_awaited()


class TestSetElectiveEquipped:
    async def test_upserts_equipped_flag(self):
        conn = AsyncMock()
        await ability_persistence.set_elective_equipped("p1", "warrior_cleaving_blow", False, conn=conn)
        sql, *params = conn.execute.call_args.args
        assert "INSERT INTO character_abilities" in sql
        assert "ON CONFLICT (player_id, ability_id) DO UPDATE SET equipped" in sql
        assert params == ["p1", "warrior_cleaving_blow", False]


class TestSetActiveVariant:
    async def test_upserts_one_variant_per_technique(self):
        conn = AsyncMock()
        await ability_persistence.set_active_variant(
            "p1", "warrior_cleaving_blow", "warrior_cleaving_blow_drathian", conn=conn
        )
        sql, *params = conn.execute.call_args.args
        assert "INSERT INTO character_active_variants" in sql
        assert "ON CONFLICT (player_id, ability_id) DO UPDATE SET variant_id" in sql
        assert params == ["p1", "warrior_cleaving_blow", "warrior_cleaving_blow_drathian"]


class TestGetActiveVariant:
    async def test_returns_active_variant_id(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value="warrior_cleaving_blow_drathian")
        result = await ability_persistence.get_active_variant("p1", "warrior_cleaving_blow", conn=conn)
        sql, *params = conn.fetchval.call_args.args
        assert "SELECT variant_id FROM character_active_variants" in sql
        assert "WHERE player_id = $1 AND ability_id = $2" in sql
        assert params == ["p1", "warrior_cleaving_blow"]
        assert result == "warrior_cleaving_blow_drathian"

    async def test_returns_none_when_no_active_variant(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=None)
        result = await ability_persistence.get_active_variant("p1", "warrior_cleaving_blow", conn=conn)
        assert result is None


class TestOwnsElective:
    async def test_true_when_row_exists(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=True)
        result = await ability_persistence.owns_elective("p1", "warrior_cleaving_blow", conn=conn)
        sql, *params = conn.fetchval.call_args.args
        assert "SELECT EXISTS (SELECT 1 FROM character_abilities" in sql
        assert "WHERE player_id = $1 AND ability_id = $2" in sql
        assert params == ["p1", "warrior_cleaving_blow"]
        assert result is True

    async def test_false_when_absent(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=False)
        result = await ability_persistence.owns_elective("p1", "warrior_cleaving_blow", conn=conn)
        assert result is False


class TestGetCharacterAbilities:
    async def test_returns_mapped_rows(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(
            return_value=[
                {"ability_id": "warrior_cleaving_blow", "equipped": True},
                {"ability_id": "warrior_precision_strike", "equipped": False},
            ]
        )
        rows = await ability_persistence.get_character_abilities("p1", conn=conn)
        sql, *params = conn.fetch.call_args.args
        assert "SELECT ability_id, equipped FROM character_abilities WHERE player_id = $1" in sql
        assert params == ["p1"]
        assert rows == [
            {"ability_id": "warrior_cleaving_blow", "equipped": True},
            {"ability_id": "warrior_precision_strike", "equipped": False},
        ]
