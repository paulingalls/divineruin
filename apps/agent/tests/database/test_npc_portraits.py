"""NPC portrait catalog validation and session payload derivation."""

from copy import deepcopy

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
