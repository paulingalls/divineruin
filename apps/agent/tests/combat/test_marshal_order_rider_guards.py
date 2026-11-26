"""Reject corrupt order riders at the persisted combat loading boundary."""

from copy import deepcopy
from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.test_kaelen_iron_resolve_capstone import required_player
from combat.test_marshal_coordinated_assault import coordinate
from combat.test_marshal_direct_strike import arrange, attack, declare_round, order, pending, round_packets
from combat.test_marshal_orders import marshal as marshal
from combat.test_marshal_orders import mock_combat_agent_factory as mock_combat_agent_factory
from combat.test_marshal_sacrifice_play import arrange_sacrifice, sacrifice

import combat_attack_roll
import db_mutations


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("recipient", "unknown"),
        ("list", {}),
        ("duplicate", None),
        ("extra", 1),
        ("kind", "unknown"),
        ("order_id", "unknown"),
        ("source_id", "unknown"),
        ("target_id", "unknown"),
        ("expires_round", True),
    ],
    ids=[
        "recipient",
        "list",
        "duplicate",
        "extra",
        "kind",
        "order",
        "source",
        "target",
        "expiry-bool",
    ],
)
async def test_loader_rejects_malformed_order_riders(marshal, field, value) -> None:
    fight = await arrange(marshal)
    _, ally, _ = fight.players
    await round_packets(fight, order(fight, fight.enemies[0]))
    state = await fight.reload()
    original = state.to_dict()
    row = deepcopy(original)
    riders = row["order_riders"]
    [rider] = riders[ally]
    if field == "recipient":
        riders[value] = riders.pop(ally)
    elif field == "list":
        riders[ally] = value
    elif field == "duplicate":
        riders[ally].append(rider)
    else:
        rider[field] = value
    try:
        await db_mutations.save_combat_state(state.combat_id, row)
        with pytest.raises(ValueError, match="order_riders"):
            await db_mutations.load_combat_state(state.combat_id)
    finally:
        await db_mutations.save_combat_state(state.combat_id, original)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("target_id", "foe", id="scoped"),
        pytest.param("partner_id", "recipient", id="self-partner"),
        pytest.param("partner_id", "foreign", id="foreign-partner"),
        pytest.param("extra", None, id="extra-key"),
        pytest.param("order_id", "foreign", id="wrong-order"),
        pytest.param("first_hit", [], id="malformed-first-hit"),
        pytest.param("first_hit.extra", None, id="first-hit-extra-key"),
        pytest.param("first_hit.ally_id", None, id="first-hit-without-partner"),
        pytest.param("first_hit.ally_id", "foreign", id="foreign-first-ally"),
        pytest.param("first_hit.target_id", "foreign", id="foreign-first-target"),
        pytest.param("first_hit.damage_type", 1, id="wrong-type"),
        pytest.param("first_hit.magical", 1, id="non-boolean-magical"),
        pytest.param("first_hit.spell_source", 1, id="wrong-spell-source"),
    ],
)
async def test_loader_rejects_malformed_coordinated_rider(marshal, field, value) -> None:
    fight = await arrange(marshal)
    host, second, first = fight.players
    foe = fight.enemies[0]
    await round_packets(fight, coordinate(host, first, second), attack(first, foe), faces=(2, 16), damage=(("1d8", 4),))
    state = await fight.reload()
    original = state.to_dict()
    row = deepcopy(original)
    [rider] = row["order_riders"][second]
    if value == "foe":
        value = foe
    elif value == "recipient":
        value = second
    if field == "partner_id":
        rider["first_hit"] = None
    if field == "first_hit.ally_id" and value is None:
        rider["partner_id"] = None
    entry, separator, key = field.partition(".")
    if separator:
        rider[entry][key] = value
    else:
        rider[entry] = value
    try:
        await db_mutations.save_combat_state(state.combat_id, row)
        with pytest.raises(ValueError, match="order_riders"):
            await db_mutations.load_combat_state(state.combat_id)
    finally:
        await db_mutations.save_combat_state(state.combat_id, original)


async def test_first_hit_cannot_attach_to_a_rider_pointing_elsewhere(marshal) -> None:
    fight = await arrange(marshal, extra_ally=True)
    host, second, first, other = fight.players
    foe = fight.enemies[0]
    await round_packets(fight, coordinate(host, first, second))
    state = await fight.reload()
    [rider] = state.order_riders[second]
    assert rider["kind"] == "coordinated_assault"
    rider["partner_id"] = other
    await fight.persist()
    await declare_round(fight, attack(first, foe))
    with (
        patch("check_resolution.dice_roll", side_effect=map(_d20, (2, 16))),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        result = await fight.command("resolve_phase", {})
    assert any(packet["actor_id"] == first and packet["hit"] for packet in result["packets"])
    [retained] = (await pending(fight))[second]
    assert retained["partner_id"] == other and retained["first_hit"] is None


async def test_attack_roll_against_fallen_target_cannot_confirm_pincer(marshal) -> None:
    fight = await arrange(marshal)
    host, second, first = fight.players
    foe = fight.enemies[0]
    await round_packets(fight, coordinate(host, first, second), attack(first, foe), faces=(2, 16), damage=(("1d8", 4),))
    state = await fight.reload()
    attacker = required_player(state, second)
    target = required_player(state, foe)
    target.hp_current, target.is_fallen = 0, True
    with (
        patch("check_resolution.dice_roll", side_effect=map(_d20, (2, 16))),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)) as dice,
    ):
        action = attacker.action_pool[0]
        result, _ = combat_attack_roll.roll_attack(
            attacker, action, target, combat_state=state, weapon_profile=action, player={"class": "warrior"}
        )
    assert result.hit and result.roll == 16 and result.pincer_dice is None
    dice.assert_called_once()


async def test_loader_rejects_a_foe_scope_on_sacrifice_play(marshal) -> None:
    fight = await arrange_sacrifice(marshal)
    _, ally, _ = fight.players
    await round_packets(fight, sacrifice(fight))
    state = await fight.reload()
    original = state.to_dict()
    row = deepcopy(original)
    [rider] = row["order_riders"][ally]
    rider["target_id"] = fight.enemies[0]
    try:
        await db_mutations.save_combat_state(state.combat_id, row)
        with pytest.raises(ValueError, match="Malformed order_riders entry"):
            await db_mutations.load_combat_state(state.combat_id)
    finally:
        await db_mutations.save_combat_state(state.combat_id, original)
