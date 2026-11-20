from types import SimpleNamespace
from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _damage_die, _resolve_round
from acceptance.test_architect_entomb import fight as fight
from acceptance.test_architect_fight import isolated_content_cache as isolated_content_cache
from acceptance.test_architect_fight import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_legendary_resistance import charge, equip_charge, prepare_cast, spell_damage

import db_mutations
from combat_enemy_active import apply_critical_save
from conditions import apply_condition


@pytest.mark.parametrize(
    "hp,rolled,affinities,face,auto_fail,damage,spent",
    [
        (40, 9, {}, 1, False, 9, False),
        (41, 10, {}, 1, False, 10, False),
        (41, 11, {}, 1, False, 5, True),
        (40, 18, {"resistant": ["fire"]}, 1, False, 9, False),
        (40, 28, {"immune": ["fire"]}, 1, False, 0, False),
        (40, 6, {"vulnerable": ["fire"]}, 1, False, 6, True),
        (40, 10, {}, 20, False, 5, False),
        (40, 10, {}, 1, True, 5, True),
    ],
)
async def test_damage_guard_uses_adjusted_failure_and_current_hp(
    fight, hp, rolled, affinities, face, auto_fail, damage, spent
):
    state = await fight.reload()
    target = state.get_participant(state.architect_encounter["owner_id"])
    assert target.hp_max == 154
    assert 0 < hp < target.hp_max
    target.damage_affinities.update(affinities)
    if auto_fail:
        target.conditions = apply_condition(target.conditions, "stunned", duration=2)
    await fight.persist()
    owner = await prepare_cast(fight, "arcane_fireball", hp=hp)
    with (
        patch("check_resolution.dice_roll", return_value=_d20(face)) as d20,
        patch("dice.roll", return_value=_damage_die(rolled)) as dice,
    ):
        result = spell_damage(await fight.drain(), fight.players[0], owner)
    assert d20.call_count == int(not auto_fail)
    dice.assert_called_once_with("5d6")
    assert result["save"]["success"] is (spent or face == 20)
    assert result["save"]["roll"] == (0 if auto_fail else face)
    assert result["save"].get("success_override") == ("Legendary Resistance" if spent else None)
    assert result["damage"] == damage
    target = (await fight.reload()).get_participant(owner)
    assert target.hp_current == hp - damage
    assert target.action_ledger["legendary resistance"]["remaining"] == 3 - spent


@pytest.mark.parametrize("immunity", ["item", "prone", None])
async def test_condition_immunity_keeps_the_failed_save(fight, immunity):
    await equip_charge(fight)
    state = await fight.reload()
    owner = state.architect_encounter["owner_id"]
    target = state.get_participant(owner)
    if immunity == "item":
        target.condition_immunities["prone"] = "Item"
    elif immunity == "prone":
        target.prone_immunity = "Stable footing"
    await fight.persist()
    result = await charge(fight, owner, face=1 if immunity else 20)
    assert result["save_success"] is (immunity is None)
    assert result["condition_immune" if immunity else "condition_resisted"] == "prone"
    assert "success_override" not in result
    target = (await fight.reload()).get_participant(owner)
    assert not target.conditions and target.action_ledger["legendary resistance"]["remaining"] == 3


async def test_save_override_and_spend_roll_back_with_the_phase(fight, monkeypatch):
    owner = await prepare_cast(fight, "arcane_fireball", hp=40)
    before = await fight.snapshot()
    publish = fight.sd.room.local_participant.publish_data
    publish.reset_mock()
    actual_write = db_mutations.save_combat_state
    observed = []

    async def fail_after_write(combat_id, data, *, conn=None):
        await actual_write(combat_id, data, conn=conn)
        written = await db_mutations.load_combat_state(combat_id, conn=conn)
        assert written is not None
        target = written.get_participant(owner)
        assert target is not None
        assert target.hp_current == 28 and target.action_ledger["legendary resistance"]["remaining"] == 2
        observed.append(True)
        raise RuntimeError("injected after saving the converted result")

    with (
        patch("check_resolution.dice_roll", return_value=_d20(1)),
        patch("dice.roll", return_value=_damage_die(25)),
    ):
        with monkeypatch.context() as fault:
            fault.setattr(db_mutations, "save_combat_state", fail_after_write)
            with pytest.raises(RuntimeError, match="injected after saving"):
                await _resolve_round(SimpleNamespace(userdata=fight.sd))
        assert observed == [True]
        assert await fight.snapshot() == before
        publish.assert_not_called()
        result = spell_damage(await fight.drain(), fight.players[0], owner)
    assert result["save"]["success_override"] == "Legendary Resistance"
    assert result["damage"] == 12
    target = (await fight.reload()).get_participant(owner)
    assert target.hp_current == 28 and target.action_ledger["legendary resistance"]["remaining"] == 2


@pytest.mark.parametrize("block", ["creature_id", "hp_current", "is_fallen", "is_dead", "already_hollowed"])
async def test_post_hit_rider_cannot_spend_on_an_ineligible_target(fight, block):
    state = await fight.reload()
    attacker = state.get_participant(fight.players[0])
    if block == "creature_id":
        target = attacker
    else:
        target = state.get_participant(state.architect_encounter["owner_id"])
        if block == "already_hollowed":
            target.conditions = apply_condition(target.conditions, "hollowed")
        else:
            setattr(target, block, 0 if block == "hp_current" else True)
    before = dict(target.action_ledger)
    action = {"name": "Critical rider", "critical_save": {"save": "wisdom", "dc": 40, "applies_condition": "hollowed"}}
    summary: dict = {"hit": True, "critical": True}
    with patch("check_resolution.dice_roll", return_value=_d20(1)):
        apply_critical_save(state, attacker, target, action, summary)
    assert not summary["critical_save"]["success"]
    assert target.action_ledger == before
    if block == "already_hollowed":
        assert target.conditions[0]["stage"] == 1


async def test_failed_save_for_a_condition_already_held_keeps_the_use(fight):
    await equip_charge(fight)
    state = await fight.reload()
    owner = state.architect_encounter["owner_id"]
    target = state.get_participant(owner)
    target.conditions = apply_condition(target.conditions, "prone")
    await fight.persist()
    result = await charge(fight, owner, face=1)
    assert result["save_success"] is False and "success_override" not in result
    target = (await fight.reload()).get_participant(owner)
    assert [c["type"] for c in target.conditions] == ["prone"]
    assert target.action_ledger["legendary resistance"]["remaining"] == 3
