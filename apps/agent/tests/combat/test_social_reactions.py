"""Contested social reactions change the held enemy action exactly once."""

import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from sample_fixtures import make_context

from combat_init import _start_combat_impl
from encounter_actions import validate_encounter_actions
from tests.combat.test_start_combat import _THORNWATCH, SAMPLE_PLAYER

_CONTENT = Path(__file__).resolve().parents[4] / "content" / "encounter_templates.json"
_ENCOUNTERS = json.loads(_CONTENT.read_text())


def _ashmark_patrol():
    return deepcopy(next(encounter for encounter in _ENCOUNTERS if encounter["id"] == "ashmark_patrol"))


def test_the_sergeant_is_the_single_valid_accusation_producer():
    carriers = [
        (encounter["id"], enemy["id"], action)
        for encounter in _ENCOUNTERS
        for enemy in encounter["enemies"]
        for action in enemy["action_pool"]
        if action.get("kind") == "accusation"
    ]
    assert carriers == [
        (
            "ashmark_patrol",
            "ashmark_sergeant",
            {
                "name": "Accusation",
                "kind": "accusation",
                "properties": [],
                "description": "Names the accused and directs the patrol's focus fire",
            },
        )
    ]
    validate_encounter_actions(_ashmark_patrol()["enemies"])


@pytest.mark.asyncio
async def test_start_combat_surfaces_the_accusation_as_a_mark_action(mock_combat_agent_factory):
    encounter = _ashmark_patrol()
    mutations = MagicMock(save_combat_state=AsyncMock())
    queries = MagicMock(
        get_player=AsyncMock(return_value=deepcopy(SAMPLE_PLAYER)),
        get_player_faction_reputation=AsyncMock(return_value=0),
    )
    content = MagicMock(
        get_encounter_template=AsyncMock(return_value=encounter),
        get_faction=AsyncMock(return_value=_THORNWATCH),
    )

    raw = await _start_combat_impl(
        make_context(), encounter["id"], encounter["description"], mutations=mutations, queries=queries, content=content
    )
    assert isinstance(raw, tuple)
    roster = {row["id"]: row for row in json.loads(raw[1])["participants"]}
    assert roster["ashmark_sergeant"]["mark_actions"] == [
        {"name": "Rally", "kind": "command"},
        {"name": "Accusation", "kind": "accusation"},
    ]
