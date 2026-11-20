from unittest.mock import patch

from acceptance._capstone_helpers import _d20
from acceptance.test_architect_entomb import fight as fight
from acceptance.test_architect_entomb import spell
from acceptance.test_architect_fight import isolated_content_cache as isolated_content_cache
from acceptance.test_architect_fight import mock_combat_agent_factory as mock_combat_agent_factory


async def charge(fight, owner):
    await fight.command(
        "declare_phase", {"declarations": [spell(fight.players[0], "warrior_unstoppable_charge", owner)]}
    )
    with patch("check_resolution.dice_roll", return_value=_d20(1)) as saving_throw:
        packets = await fight.drain()
    saving_throw.assert_called_once()
    return next(packet for packet in packets if packet.get("action") == "warrior_unstoppable_charge")


async def test_charge_spends_three_uses_then_lands_prone(fight):
    state = await fight.reload()
    owner = state.architect_encounter["owner_id"]
    await fight.pool.execute(
        "INSERT INTO character_abilities (player_id, ability_id, equipped) VALUES ($1,$2,true)",
        fight.players[0],
        "warrior_unstoppable_charge",
    )
    await fight.pool.execute(
        "UPDATE players SET data = jsonb_set(data, '{stamina}', $2::jsonb) WHERE player_id=$1",
        fight.players[0],
        '{"current":16,"max":16}',
    )
    for remaining in (2, 1, 0):
        packet = await charge(fight, owner)
        assert packet.get("condition_resisted") == "prone", packet
        assert packet["success_override"] == "Legendary Resistance"
        architect = (await fight.reload()).get_participant(owner)
        assert not architect.conditions
        assert architect.action_ledger["legendary resistance"]["remaining"] == remaining
    packet = await charge(fight, owner)
    assert packet["condition_inflicted"] == "prone"
    assert "success_override" not in packet
    architect = (await fight.reload()).get_participant(owner)
    assert architect.action_ledger["legendary resistance"]["remaining"] == 0
    assert [condition["type"] for condition in architect.conditions] == ["prone"]
