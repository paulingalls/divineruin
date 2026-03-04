"""Database error handling utilities."""

from __future__ import annotations

import logging
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

logger = logging.getLogger("divineruin.db_errors")

T = TypeVar("T")


class DatabaseError(Exception):
    """Base exception for database errors that should be communicated to the player."""

    def __init__(self, message: str, user_message: str, operation: str):
        super().__init__(message)
        self.user_message = user_message
        self.operation = operation


class DatabaseConnectionError(DatabaseError):
    """Database connection failed."""

    def __init__(self, operation: str, original_error: Exception):
        super().__init__(
            f"Database connection failed during {operation}: {original_error}",
            "I'm having trouble accessing the game data right now. Please try again in a moment.",
            operation,
        )
        self.original_error = original_error


class DatabaseTimeoutError(DatabaseError):
    """Database query timed out."""

    def __init__(self, operation: str, original_error: Exception):
        super().__init__(
            f"Database query timed out during {operation}: {original_error}",
            "That's taking longer than expected. Let me try again...",
            operation,
        )
        self.original_error = original_error


class DatabaseNotFoundError(DatabaseError):
    """Required data not found in database."""

    def __init__(self, operation: str, entity_type: str, entity_id: str):
        super().__init__(
            f"Required {entity_type} '{entity_id}' not found during {operation}",
            f"I can't find that {entity_type} in my records. Something may have gone wrong.",
            operation,
        )
        self.entity_type = entity_type
        self.entity_id = entity_id


class DatabaseIntegrityError(DatabaseError):
    """Database constraint violation or data integrity issue."""

    def __init__(self, operation: str, original_error: Exception):
        super().__init__(
            f"Database integrity error during {operation}: {original_error}",
            "Something unexpected happened with the game data. Let me help you recover from this.",
            operation,
        )
        self.original_error = original_error


async def with_db_error_handling(
    operation: str,
    db_call: Callable[[], Any],
    *,
    allow_none: bool = False,
    entity_type: str | None = None,
    entity_id: str | None = None,
) -> Any:
    """
    Execute a database call with comprehensive error handling.

    Args:
        operation: Human-readable operation name (e.g., "get_player", "update_inventory")
        db_call: Async callable that performs the database operation
        allow_none: If True, None return is acceptable; if False, raises DatabaseNotFoundError
        entity_type: Type of entity being queried (for error messages)
        entity_id: ID of entity being queried (for error messages)

    Returns:
        Result of db_call

    Raises:
        DatabaseError: One of the specific database error types
    """
    try:
        result = await db_call()

        # Check for None when it's not allowed
        if result is None and not allow_none:
            if entity_type and entity_id:
                raise DatabaseNotFoundError(operation, entity_type, entity_id)
            else:
                raise DatabaseNotFoundError(operation, "data", "unknown")

        return result

    except DatabaseError:
        # Re-raise our custom errors
        raise

    except TimeoutError as e:
        logger.error("Database timeout in %s: %s", operation, e, exc_info=True)
        raise DatabaseTimeoutError(operation, e) from e

    except ConnectionError as e:
        logger.error("Database connection error in %s: %s", operation, e, exc_info=True)
        raise DatabaseConnectionError(operation, e) from e

    except Exception as e:
        # Catch-all for unexpected errors
        logger.error("Unexpected database error in %s: %s", operation, e, exc_info=True)
        raise DatabaseIntegrityError(operation, e) from e


def db_tool(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Decorator for tool functions that handles database errors and returns error JSON.

    Wraps the tool function to catch DatabaseError exceptions and return
    a standardized error response that the LLM can communicate to the player.

    Usage:
        @db_tool
        async def my_tool(...) -> str:
            # database operations
            return json.dumps({"result": ...})
    """

    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> str:
        try:
            return await func(*args, **kwargs)
        except DatabaseError as e:
            logger.warning(
                "Database error in %s: %s (user message: %s)",
                func.__name__,
                e,
                e.user_message,
            )
            return _error_response(e.user_message, e.operation)
        except TimeoutError as e:
            logger.error("Database timeout in %s: %s", func.__name__, e, exc_info=True)
            err = DatabaseTimeoutError(func.__name__, e)
            return _error_response(err.user_message, err.operation)
        except ConnectionError as e:
            logger.error("Database connection error in %s: %s", func.__name__, e, exc_info=True)
            err = DatabaseConnectionError(func.__name__, e)
            return _error_response(err.user_message, err.operation)

    return wrapper


def _error_response(message: str, operation: str) -> str:
    """Create a standardized error response for the LLM."""
    import json

    return json.dumps(
        {
            "success": False,
            "error": message,
            "operation": operation,
            "guidance": "Communicate this error to the player naturally, in character. "
            "Do not expose technical details. Offer to try again or suggest an alternative.",
        }
    )
