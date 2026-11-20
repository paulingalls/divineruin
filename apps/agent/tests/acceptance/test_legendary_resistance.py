from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.seeds import seed_known_spells
from acceptance.test_architect_entomb import fight as fight
from acceptance.test_architect_entomb import spell
from acceptance.test_architect_fight import isolated_content_cache as isolated_content_cache
from acceptance.test_architect_fight import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_architect_fight import pos


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


async def prepare_cast(fight, spell_id, *, hp, class_="mage"):
    caster = fight.players[0]
    await fight.pool.execute(
        "UPDATE players SET data = jsonb_set(data, '{class}', to_jsonb($2::text)) WHERE player_id=$1",
        caster,
        class_,
    )
    await seed_known_spells(fight.pool, caster, (spell_id,))
    state = await fight.reload()
    owner = state.architect_encounter["owner_id"]
    state.architect_encounter["reaction_round"] = state.round_number
    state.get_participant(owner).hp_current = hp
    state.spatial["positions"][caster] = pos(30)
    await fight.persist()
    await fight.command("declare_phase", {"declarations": [spell(caster, spell_id, owner)]})
    return owner


def spell_damage(packets, caster, recipient):
    cast = next(packet["cast"] for packet in packets if packet["actor_id"] == caster)
    results = cast["damage_results"] if "damage_results" in cast else [cast["damage_result"]]
    return next(result for result in results if result["target_id"] == recipient)


@pytest.mark.parametrize(
    "spell_id,class_,hp,rolls,damage",
    [
        ("arcane_fireball", "mage", 100, [25], 12),
        ("divine_flame_strike", "cleric", 100, [9, 9], 12),
        ("divine_sacred_flame", "cleric", 50, [9], 0),
    ],
)
async def test_spell_conversion_uses_ordinary_success_damage(fight, spell_id, class_, hp, rolls, damage):
    owner = await prepare_cast(fight, spell_id, hp=hp, class_=class_)
    with (
        patch("check_resolution.dice_roll", return_value=_d20(1)) as saving_throw,
        patch("dice.roll", side_effect=[_damage_die(total) for total in rolls]) as rolled_damage,
    ):
        result = spell_damage(await fight.drain(), fight.players[0], owner)
    saving_throw.assert_called_once()
    assert rolled_damage.call_count == len(rolls)
    assert result["save"]["success"], result
    assert result["save"]["roll"] == 1
    assert result["save"]["success_override"] == "Legendary Resistance"
    assert result["damage"] == damage
    target = (await fight.reload()).get_participant(owner)
    assert target.hp_current == hp - damage
    assert target.action_ledger["legendary resistance"]["remaining"] == 2
