from acceptance.test_architect_fight import fight as fight
from acceptance.test_architect_fight import isolated_content_cache as isolated_content_cache
from acceptance.test_architect_fight import mock_combat_agent_factory as mock_combat_agent_factory


async def test_first_round_legendary_options(fight):
    state = await fight.reload()
    owner_id = state.architect_encounter["owner_id"]
    owner = state.get_participant(owner_id)
    assert (owner.role, state.round_number, owner.legendary_actions) == ("named", 1, 3)
    facts = (await fight.command("query_info", {"kind": "combat", "target_id": owner_id}))["architect"]
    assert {a["id"]: a["cost"] for a in facts["legendary"]["actions"]} == {
        "Geometry Strike": 2,
        "Shift Wall": 1,
        "Reshape": 2,
    }
