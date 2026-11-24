import json
from copy import deepcopy
from pathlib import Path

import pytest

import combat_recharge
from combat_participant import CombatParticipant
from combat_state import CombatState

CATALOG = Path(__file__).resolve().parents[4] / "content/creatures.json"


@pytest.mark.parametrize(
    "participant_overrides,action_overrides,upgrades",
    [
        pytest.param({}, {}, True, id="legacy"),
        pytest.param({"creature_id": "ashmark_sergeant"}, {}, False, id="other-creature"),
        pytest.param({}, {"name": "Other"}, False, id="other-name"),
        pytest.param({}, {"kind": "command"}, False, id="other-kind"),
        pytest.param({}, {"reach": None}, False, id="null"),
        pytest.param({}, {"reach": 0}, False, id="zero"),
        pytest.param({}, {"reach": 40}, False, id="explicit"),
    ],
)
def test_saved_rally_reach_upgrade(participant_overrides: dict, action_overrides: dict, upgrades: bool) -> None:
    captain_row = next(row for row in json.loads(CATALOG.read_text()) if row["id"] == "bandit_captain")
    rally = next(action for action in captain_row["actives"] if action["name"] == "Rally")
    authored_reach = rally.pop("reach")
    rally.update(action_overrides)
    captain = CombatParticipant("captain", "Captain", "enemy", 10, 12, 24, 15, creature_id="bandit_captain")
    captain.action_pool = [rally]
    snapshot = CombatState("fight", [captain], [captain.id]).to_dict()
    snapshot["participants"][0].update(participant_overrides)
    expected = deepcopy(snapshot)
    if upgrades:
        expected["participants"][0]["action_pool"][0]["reach"] = authored_reach
    reloaded = CombatState.from_dict(snapshot)
    assert reloaded.to_dict() == expected
    assert CombatState.from_dict(reloaded.to_dict()).to_dict() == expected
    if "reach" in action_overrides and action_overrides["reach"] in (None, 0):
        with pytest.raises(ValueError, match=r"captain\.Rally\.reach"):
            combat_recharge.initialize(reloaded.participants[0])
