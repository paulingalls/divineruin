import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from sample_fixtures import make_context

from query_tools import _query_abilities_impl


@pytest.mark.asyncio
async def test_owned_charge_id_is_handed_to_the_dm():
    queries = MagicMock()
    queries.get_player = AsyncMock(return_value={"class": "warrior", "level": 8})
    persistence = MagicMock()
    persistence.get_character_abilities = AsyncMock(
        return_value=[{"ability_id": "warrior_unstoppable_charge", "equipped": True}]
    )
    persistence.get_active_variant = AsyncMock(return_value=None)
    library = MagicMock()
    library.get_known = AsyncMock(return_value=[])

    payload = json.loads(
        await _query_abilities_impl(
            make_context(), queries=queries, persistence=persistence, character_spells_mod=library
        )
    )

    assert "warrior_unstoppable_charge" in {row["id"] for row in payload["abilities"]}
