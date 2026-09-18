from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock


def txn_db():
    conn = AsyncMock()

    @asynccontextmanager
    async def transaction():
        yield conn

    module = MagicMock()
    module.transaction = transaction
    return module
