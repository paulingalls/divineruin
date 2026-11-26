"""Whether a participant can give or receive the Marshal's War Cry."""

from unittest.mock import patch

from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_marshal_war_cry import declare, kael, rallies, save_spy
from acceptance.test_marshal_war_cry import fight as fight
from acceptance.test_marshal_war_cry import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_martial_core_kit import weapon_attack
from acceptance.test_self_buff_electives import receipt, stamina
from acceptance.test_war_cry import bandits, point

import combat_spatial
import conditions


async def test_deafened_recipients_are_excluded(fight: MawlingHarness) -> None:
    marshal, ally = fight.players
    state = await fight.reload()
    first, second, far, _ = bandits(state)
    listener = state.get_participant(ally)
    assert listener is not None
    listener.conditions = conditions.apply_condition(listener.conditions, "deafened", source="test")
    await fight.persist()
    attack = weapon_attack(ally, far.id, "")
    companion = kael(state)
    hearing_attack = weapon_attack(companion.id, first.id, "")
    await declare(fight, attack, hearing_attack)
    with (
        patch("check_resolution.dice_roll", return_value=_d20(19)),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(3)),
        save_spy() as saves,
    ):
        packets = (await fight.command("resolve_phase", {}))["packets"]
        cry = receipt(packets, marshal)
        assert cry["resolved"] and cry["rally_targets"] == [kael(state).id]
        assert [row["target_id"] for row in cry["condition_results"]] == [first.id, second.id]
        assert [call.args[0].id for call in saves.call_args_list] == [first.id, second.id]
        assert set(rallies(await fight.reload())) == {kael(state).id}
        deafened = receipt(packets, ally)["attacks"]
        rallied = receipt(packets, companion.id)["attack_total"]
        await fight.drain()
        await declare(fight, attack, hearing_attack, cry=False)
        next_packets = (await fight.command("resolve_phase", {}))["packets"]
        plain = receipt(next_packets, ally)["attacks"]
        assert rallied == receipt(next_packets, companion.id)["attack_total"] + 1
    assert len(deafened) == len(plain) == 2
    assert [row["attack_total"] for row in deafened] == [row["attack_total"] for row in plain]


async def test_fallen_ally_is_excluded(fight: MawlingHarness) -> None:
    marshal, ally = fight.players
    state = await fight.reload()
    companion = kael(state)
    companion.hp_current, companion.is_fallen = 0, True
    await fight.persist()
    await declare(fight)
    with patch("check_resolution.dice_roll", return_value=_d20(20)):
        cry = receipt((await fight.command("resolve_phase", {}))["packets"], marshal)
    assert cry["rally_targets"] == [ally]
    assert set(rallies(await fight.reload())) == {ally}


async def test_silenced_marshal_refuses_then_legal_use_succeeds(fight: MawlingHarness) -> None:
    marshal, ally = fight.players
    state = await fight.reload()
    for foe in bandits(state):
        combat_spatial.place(state, foe.id, point(40))
    zones = combat_spatial.require_spatial(state)["zones"]
    zones["silence"] = {"kind": "silence", "center_id": marshal, "radius_ft": 1}
    await fight.persist()
    before = await fight.snapshot()
    stamina_before = await stamina(marshal)
    with save_spy() as saves:
        assert "silenced and cannot speak" in await declare(fight, error=True)
        assert await fight.snapshot() == before
        del combat_spatial.require_spatial(await fight.reload())["zones"]["silence"]
        await fight.persist()
        await declare(fight)
        cry = receipt((await fight.command("resolve_phase", {}))["packets"], marshal)
    assert cry["resolved"] and set(cry["rally_targets"]) == {ally, kael(state).id}
    assert await stamina(marshal) == stamina_before - 3
    saves.assert_not_called()
