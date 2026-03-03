"""Tests for database error handling utilities."""

from __future__ import annotations

import json
import pytest

from db_errors import (
    DatabaseError,
    DatabaseConnectionError,
    DatabaseTimeoutError,
    DatabaseNotFoundError,
    DatabaseIntegrityError,
    with_db_error_handling,
    db_tool,
)


class TestDatabaseErrorTypes:
    def test_connection_error_attributes(self):
        original = ConnectionError("Connection refused")
        err = DatabaseConnectionError("get_player", original)
        assert err.operation == "get_player"
        assert err.original_error is original
        assert "trouble accessing" in err.user_message.lower()

    def test_timeout_error_attributes(self):
        original = TimeoutError("Query timeout")
        err = DatabaseTimeoutError("update_quest", original)
        assert err.operation == "update_quest"
        assert err.original_error is original
        assert "longer than expected" in err.user_message.lower()

    def test_not_found_error_attributes(self):
        err = DatabaseNotFoundError("get_npc", "NPC", "torin")
        assert err.operation == "get_npc"
        assert err.entity_type == "NPC"
        assert err.entity_id == "torin"
        assert "can't find" in err.user_message.lower()

    def test_integrity_error_attributes(self):
        original = ValueError("Constraint violation")
        err = DatabaseIntegrityError("add_item", original)
        assert err.operation == "add_item"
        assert err.original_error is original
        assert "unexpected" in err.user_message.lower()


class TestWithDbErrorHandling:
    @pytest.mark.asyncio
    async def test_successful_call(self):
        async def db_call():
            return {"id": "player1", "hp": 100}

        result = await with_db_error_handling("get_player", db_call)
        assert result == {"id": "player1", "hp": 100}

    @pytest.mark.asyncio
    async def test_none_allowed(self):
        async def db_call():
            return None

        result = await with_db_error_handling("get_optional", db_call, allow_none=True)
        assert result is None

    @pytest.mark.asyncio
    async def test_none_not_allowed_raises(self):
        async def db_call():
            return None

        with pytest.raises(DatabaseNotFoundError) as exc_info:
            await with_db_error_handling(
                "get_required",
                db_call,
                allow_none=False,
                entity_type="player",
                entity_id="missing_id",
            )

        err = exc_info.value
        assert err.entity_type == "player"
        assert err.entity_id == "missing_id"

    @pytest.mark.asyncio
    async def test_timeout_error_wrapped(self):
        async def db_call():
            raise TimeoutError("Query took too long")

        with pytest.raises(DatabaseTimeoutError) as exc_info:
            await with_db_error_handling("slow_query", db_call)

        err = exc_info.value
        assert err.operation == "slow_query"
        assert isinstance(err.original_error, TimeoutError)

    @pytest.mark.asyncio
    async def test_connection_error_wrapped(self):
        async def db_call():
            raise ConnectionError("Connection lost")

        with pytest.raises(DatabaseConnectionError) as exc_info:
            await with_db_error_handling("connect_db", db_call)

        err = exc_info.value
        assert err.operation == "connect_db"
        assert isinstance(err.original_error, ConnectionError)

    @pytest.mark.asyncio
    async def test_unexpected_error_wrapped(self):
        async def db_call():
            raise ValueError("Unexpected database state")

        with pytest.raises(DatabaseIntegrityError) as exc_info:
            await with_db_error_handling("update_data", db_call)

        err = exc_info.value
        assert err.operation == "update_data"
        assert isinstance(err.original_error, ValueError)

    @pytest.mark.asyncio
    async def test_database_error_passed_through(self):
        async def db_call():
            raise DatabaseNotFoundError("get_item", "item", "sword")

        with pytest.raises(DatabaseNotFoundError):
            await with_db_error_handling("get_item", db_call)


class TestDbToolDecorator:
    @pytest.mark.asyncio
    async def test_successful_tool_returns_json(self):
        @db_tool
        async def test_tool():
            return json.dumps({"success": True, "data": "result"})

        result = await test_tool()
        data = json.loads(result)
        assert data["success"] is True
        assert data["data"] == "result"

    @pytest.mark.asyncio
    async def test_database_error_caught_and_formatted(self):
        @db_tool
        async def failing_tool():
            raise DatabaseConnectionError(
                "get_player", ConnectionError("Connection refused")
            )

        result = await failing_tool()
        data = json.loads(result)

        assert data["success"] is False
        assert "error" in data
        assert "trouble accessing" in data["error"].lower()
        assert data["operation"] == "get_player"
        assert "guidance" in data

    @pytest.mark.asyncio
    async def test_not_found_error_formatted(self):
        @db_tool
        async def missing_data_tool():
            raise DatabaseNotFoundError("get_npc", "NPC", "ghost")

        result = await missing_data_tool()
        data = json.loads(result)

        assert data["success"] is False
        assert "can't find" in data["error"].lower()
        assert data["operation"] == "get_npc"

    @pytest.mark.asyncio
    async def test_timeout_error_formatted(self):
        @db_tool
        async def slow_tool():
            raise DatabaseTimeoutError("complex_query", TimeoutError("Too slow"))

        result = await slow_tool()
        data = json.loads(result)

        assert data["success"] is False
        assert "longer than expected" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_decorator_preserves_function_metadata(self):
        @db_tool
        async def documented_tool():
            """This tool has documentation."""
            return json.dumps({"result": "ok"})

        assert documented_tool.__name__ == "documented_tool"
        assert documented_tool.__doc__ == "This tool has documentation."

    @pytest.mark.asyncio
    async def test_non_database_errors_not_caught(self):
        """The decorator should only catch DatabaseError types."""

        @db_tool
        async def buggy_tool():
            # This is a programming error, not a database error
            raise KeyError("Oops")

        with pytest.raises(KeyError):
            await buggy_tool()
