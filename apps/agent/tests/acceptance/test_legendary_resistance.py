from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.seeds import seed_known_spells
from acceptance.test_architect_entomb import favor, spell
from acceptance.test_architect_entomb import fight as fight
from acceptance.test_architect_fight import enter, pos, reopen
from acceptance.test_architect_fight import isolated_content_cache as isolated_content_cache
from acceptance.test_architect_fight import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_still_anchors import fresh_session

import db_queries


async def charge(fight, owner, *, face=1):
    await fight.command(
        "declare_phase", {"declarations": [spell(fight.players[0], "warrior_unstoppable_charge", owner)]}
    )
    with patch("check_resolution.dice_roll", return_value=_d20(face)) as saving_throw:
        packets = await fight.drain()
    saving_throw.assert_called_once()
    return next(packet for packet in packets if packet.get("action") == "warrior_unstoppable_charge")


async def equip_charge(fight):
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


async def test_charge_spends_three_uses_then_lands_prone(fight):
    owner = (await fight.reload()).architect_encounter["owner_id"]
    await equip_charge(fight)
    for remaining in (2, 1, 0):
        packet = await charge(fight, owner)
        assert packet.get("condition_resisted") == "prone", packet
        assert packet["save_success"] and packet["success_override"] == "Legendary Resistance"
        architect = (await fight.reload()).get_participant(owner)
        assert not architect.conditions
        assert architect.action_ledger["legendary resistance"]["remaining"] == remaining
    await fight.command("end_combat", {"outcome": "fled"})
    await reopen(fight)
    await enter(fight)
    packet = await charge(fight, owner)
    assert not packet["save_success"]
    assert packet["condition_inflicted"] == "prone"
    assert "success_override" not in packet
    architect = (await fight.reload()).get_participant(owner)
    assert architect.action_ledger["legendary resistance"]["remaining"] == 0
    assert [condition["type"] for condition in architect.conditions] == ["prone"]


async def prepare_cast(fight, spell_id, *, hp, class_="mage", caster_distance=30):
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
    state.spatial["positions"][caster] = pos(caster_distance)
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


@pytest.mark.parametrize("keep_original", [True, False])
async def test_fate_selects_damage_save_before_spending(fight, keep_original):
    owner = (await fight.reload()).architect_encounter["owner_id"]
    await equip_charge(fight)
    assert (await charge(fight, owner))["success_override"] == "Legendary Resistance"
    await favor(fight)
    await prepare_cast(fight, "arcane_fireball", hp=100)
    with (
        patch("check_resolution.dice_roll", side_effect=[_d20(1), _d20(20)]) as d20,
        patch("dice.roll", return_value=_damage_die(25)) as damage,
    ):
        held = await fight.command("resolve_phase", {})
        offer = held["fate_offer"]
        assert (offer["roller_id"], offer["roll_kind"], offer["die"]) == (owner, "save", 1)
        saved = await fight.reload()
        target = saved.get_participant(owner)
        assert target.hp_current == 100 and target.action_ledger["legendary resistance"]["remaining"] == 2
        damage.assert_not_called()
        if keep_original:
            await fresh_session(fight, saved)
            packets = await fight.drain()
        else:
            args = {"id": "zhael_fates_thread", "offer_id": offer["offer_id"]}
            assert (await fight.command("activate", args))["reroll"]["die"] == 20
            response = await fight.command("activate", {**args, "keep": "reroll"})
            packets = response["packets"]
            if (await fight.reload()).round_number == saved.round_number:
                packets += await fight.drain()
        result = spell_damage(packets, fight.players[0], owner)
    assert d20.call_count == (1 if keep_original else 2)
    damage.assert_called_once_with("5d6")
    assert result["save"]["success"] and result["damage"] == 12
    assert result["save"].get("success_override") == ("Legendary Resistance" if keep_original else None)
    target = (await fight.reload()).get_participant(owner)
    assert target.hp_current == 88
    assert target.action_ledger["legendary resistance"]["remaining"] == (1 if keep_original else 2)


async def test_later_recipient_hold_preserves_first_recipient_save_and_spend(fight):
    caster = fight.players[0]
    await fight.pool.execute(
        "UPDATE players SET data=data || $2::jsonb WHERE player_id=$1",
        caster,
        '{"divine_favor":{"patron":"zhael","level":40,"max":100},"patron_gifts":{"zhael_fates_thread":{"spent":true}}}',
    )
    owner = await prepare_cast(fight, "arcane_fireball", hp=100, caster_distance=5)
    with (
        patch("check_resolution.dice_roll", side_effect=[_d20(1), _d20(1)]) as d20,
        patch("dice.roll", side_effect=[_damage_die(25), _damage_die(9)]) as damage,
    ):
        held = await fight.command("resolve_phase", {})
        assert held["fate_offer"]["roller_id"] == caster, held
        saved = await fight.reload()
        architect = saved.get_participant(owner)
        assert architect.hp_current == 88 and architect.action_ledger["legendary resistance"]["remaining"] == 2
        receipt = saved.ally_continuation["steps"]["spell_damage"]["landed"][owner]
        assert receipt["save"]["success_override"] == "Legendary Resistance"
        player = await db_queries.get_player(caster)
        assert player is not None and player["hp"]["current"] == 100
        damage.assert_called_once_with("5d6")
        await fresh_session(fight, saved)
        packets = await fight.drain()
    assert d20.call_count == damage.call_count == 2
    first = spell_damage(packets, fight.players[0], owner)
    assert first["damage"] == 12 and first["save"]["success_override"] == "Legendary Resistance"
    second = spell_damage(packets, caster, caster)
    assert second["damage"] == 9 and not second["save"]["success"]
    after = (await fight.reload()).get_participant(owner)
    assert after.hp_current == 88 and after.action_ledger["legendary resistance"]["remaining"] == 2
