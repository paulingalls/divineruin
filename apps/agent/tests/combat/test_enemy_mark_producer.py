"""Enemy command metadata exposed to the DM."""

import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from sample_fixtures import make_context

from combat_init import _start_combat_impl
from combat_prompts import COMBAT_PROMPT
from tests.combat.test_start_combat import _THORNWATCH, SAMPLE_PLAYER

_CONTENT = Path(__file__).resolve().parents[4] / "content"
_ENCOUNTERS = json.loads((_CONTENT / "encounter_templates.json").read_text())


def _encounter(encounter_id: str) -> dict:
    return deepcopy(next(encounter for encounter in _ENCOUNTERS if encounter["id"] == encounter_id))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("encounter_id", "expected"),
    [
        ("bandit_ambush", {"bandit_captain": [{"name": "Press the Attack", "kind": "command"}]}),
        (
            "ashmark_patrol",
            {
                "ashmark_sergeant": [
                    {"name": "Rally", "kind": "command"},
                    {"name": "Accusation", "kind": "accusation"},
                ]
            },
        ),
        (
            "cult_cell",
            {
                "cult_fanatic_1": [{"name": "Bless", "kind": "command"}],
                "cult_fanatic_2": [{"name": "Bless", "kind": "command"}],
            },
        ),
        (
            "hollow_corrupted_settlement",
            {"hollowed_knight": [{"name": "Command Lesser", "kind": "command"}]},
        ),
    ],
)
async def test_start_combat_hands_each_command_to_the_dm_as_a_mark_action(
    mock_combat_agent_factory, encounter_id, expected
):
    encounter = _encounter(encounter_id)
    mutations = MagicMock(save_combat_state=AsyncMock())
    queries = MagicMock(
        get_player=AsyncMock(return_value=deepcopy(SAMPLE_PLAYER)),
        get_player_faction_reputation=AsyncMock(return_value=0),
        get_player_inventory=AsyncMock(return_value=[]),
    )
    content = MagicMock(
        get_encounter_template=AsyncMock(return_value=encounter),
        get_faction=AsyncMock(return_value=_THORNWATCH),
    )

    raw = await _start_combat_impl(
        make_context(), encounter_id, encounter["description"], mutations=mutations, queries=queries, content=content
    )
    assert isinstance(raw, tuple)
    roster = {participant["id"]: participant for participant in json.loads(raw[1])["participants"]}

    for enemy in encounter["enemies"]:
        assert roster[enemy["id"]]["actions"] == [action["name"] for action in enemy["action_pool"]]
        assert roster[enemy["id"]]["mark_actions"] == expected.get(enemy["id"], [])
    assert roster["player_1"]["mark_actions"] == []


def test_combat_prompt_explains_command_mark_targets():
    assert "Combatants[].mark_actions" in COMBAT_PROMPT
    assert "kind `command`" in COMBAT_PROMPT
    assert "target_id" in COMBAT_PROMPT and "focus" in COMBAT_PROMPT
