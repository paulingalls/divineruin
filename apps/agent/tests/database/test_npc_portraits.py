"""NPC portrait catalog validation and session payload derivation."""

from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from npcs_config_fixture import load_fixture_config

import db
import npcs


def test_parse_npc_row_rejects_a_non_string_portrait():
    npc_id, row = next(iter(load_fixture_config().items()))
    malformed = deepcopy(row)
    malformed["portrait"] = 42

    with pytest.raises(ValueError, match=rf"{npc_id}\.portrait"):
        npcs.parse_npc_row(npc_id, malformed)


def test_parse_npc_row_accepts_an_absent_portrait():
    npc_id, row = next(iter(load_fixture_config().items()))
    without_portrait = deepcopy(row)
    without_portrait.pop("portrait", None)

    assert "portrait" not in npcs.parse_npc_row(npc_id, without_portrait)


def test_all_npcs_fails_loud_when_the_catalog_is_empty():
    npcs.set_npcs({})

    with pytest.raises(RuntimeError, match="NPC catalog is not loaded"):
        npcs.all_npcs()


def test_set_npcs_rejects_duplicate_voice_ids():
    with pytest.raises(ValueError, match=r"duplicate voice_id 'SHARED_VOICE'.*first.*second"):
        npcs.set_npcs(
            {
                "first": {"voice_id": "SHARED_VOICE"},
                "second": {"voice_id": "SHARED_VOICE"},
            }
        )


@pytest.mark.asyncio
async def test_load_npcs_rejects_duplicate_voice_ids_before_replacing_the_catalog():
    rows = list(load_fixture_config().items())[:2]
    duplicate = deepcopy(rows[1][1])
    duplicate["voice_id"] = rows[0][1]["voice_id"]
    pool = MagicMock()
    pool.fetch = AsyncMock(
        return_value=[
            {"id": rows[0][0], "data": rows[0][1]},
            {"id": rows[1][0], "data": duplicate},
        ]
    )

    with (
        patch("db.get_pool", new_callable=AsyncMock, return_value=pool),
        pytest.raises(ValueError, match="duplicate voice_id"),
    ):
        await npcs.load_npcs()

    assert len(npcs.all_npcs()) == 17


def test_build_portraits_derives_only_portrait_bearing_catalog_rows():
    npcs.set_npcs(
        {
            "invented_face": {
                "name": "Invented Face",
                "voice_id": "INVENTED_FACE",
                "portrait": "npc_invented",
            },
            "invented_faceless": {
                "name": "Invented Faceless",
                "voice_id": "INVENTED_FACELESS",
            },
        }
    )

    assert db._build_portraits(None)["npcs"] == {
        "INVENTED_FACE": {
            "name": "Invented Face",
            "url": "/api/assets/images/npc_invented",
        }
    }
