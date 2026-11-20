from types import SimpleNamespace
from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.mawling_harness import MawlingHarness
from acceptance.seeds import seed_known_spells
from acceptance.test_architect_fight import WORKS, declare_attack, pos, reload_held
from acceptance.test_architect_fight import isolated_content_cache as isolated_content_cache
from acceptance.test_architect_fight import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_still_anchors import fresh_session

from combat_participant import CombatParticipant
from conditions import apply_condition
from db_mutations_concentration import update_player_concentration
from mode_tools import enter_mode
from scene_tools import enter_location


@pytest.fixture
async def fight(reset_db_pool, request):
    harness = MawlingHarness()
    try:
        levels, companion = getattr(request, "param", ((20,), None))
        await harness.prepare(levels, companion=companion, location=WORKS)
        scene = await harness.command(enter_location.id, {"location_id": WORKS})
        entry = await harness.command(
            enter_mode.id, {"mode": "combat", "encounter_id": scene["architect"]["encounter_id"]}
        )
        harness.roster = entry["participants"]
        state = await harness.reload()
        assert state.spatial is not None and state.architect_encounter is not None
        for participant in state.participants:
            if participant.is_ally:
                state.spatial["positions"][participant.id] = pos(5)
        state.spatial["positions"][state.architect_encounter["owner_id"]] = pos(0)
        await harness.persist()
        yield harness
    finally:
        await harness.close()


def discover_entomb(fight):
    return next(
        (actor["id"], action["id"])
        for actor in fight.roster
        for action in actor["executable_actions"]
        if action["id"] == "Entomb" and action["available"]
    )


async def test_saved_entomb_spends_and_recharges_on_round_wrap(fight):
    owner, action = discover_entomb(fight)
    victim = fight.players[0]
    before, players = await fight.snapshot()
    await declare_attack(fight, owner, victim, action)
    with (
        patch("check_resolution.dice_roll", return_value=_d20(20)) as save,
        patch("combat_recharge.roll", return_value=SimpleNamespace(total=5)) as recharge,
    ):
        cast = next(packet for packet in await fight.drain() if packet["actor_id"] == owner)
    save.assert_called_once()
    recharge.assert_called_once()
    assert cast["save_success"]
    state = await fight.reload()
    assert not state.spatial.get("chambers")
    assert state.get_participant(victim).conditions == []
    assert (await fight.snapshot())[1][0]["hp"] == players[0]["hp"]
    assert state.get_participant(victim).hp_current == next(
        p["hp_current"] for p in before["participants"] if p["id"] == victim
    )
    assert state.get_participant(owner).action_ledger[action.casefold()]["remaining"] == 0
    spent = await fight.snapshot()
    assert "unavailable" in await fight.command(
        "declare_phase", {"declarations": [strike(owner, victim, action)]}, error=True
    )
    assert await fight.snapshot() == spent
    await fight.command(
        "declare_phase",
        {
            "declarations": [
                {"reshape": [], "actor_id": victim, "kind": "defend"},
                {"reshape": [], "actor_id": owner, "kind": "defend"},
            ]
        },
    )
    with patch("combat_recharge.roll", return_value=SimpleNamespace(total=6)) as recharge:
        await fight.drain()
    recharge.assert_called_once()
    assert (await fight.reload()).get_participant(owner).action_ledger[action.casefold()]["remaining"] == 1


async def seal(fight, victim=None):
    owner, action = discover_entomb(fight)
    victim = victim or fight.players[0]
    await declare_attack(fight, owner, victim, action)
    with patch("check_resolution.dice_roll", return_value=_d20(1)) as save:
        cast = next(packet for packet in await fight.drain() if packet["actor_id"] == owner)
    save.assert_called_once()
    assert (cast["save_type"], cast["save_dc"], cast["save_success"]) == ("strength", 20, False)
    return owner, victim, cast["chamber_id"]


async def test_entomb_surfaces_chamber_and_compresses_at_each_turn_start(fight):
    before = (await fight.snapshot())[1][0]["hp"]
    owner, victim, chamber_id = await seal(fight)
    state = await fight.reload()
    chamber = state.get_participant(chamber_id)
    assert (chamber.type, chamber.ac, chamber.hp_current, chamber.hp_max) == ("structure", 19, 30, 30)
    assert state.spatial["speeds"][chamber_id] == 0 and chamber_id not in state.initiative_order
    assert [(c["type"], c["duration"], c["source"]) for c in state.get_participant(victim).conditions] == [
        ("restrained", None, chamber_id)
    ]
    info = await fight.command("query_info", {"kind": "combat"})
    assert [(c["chamber_id"], c["target_id"]) for c in info["chambers"]] == [(chamber_id, victim)]
    assert any(chamber_id in line for line in info["spoken"])
    assert (await fight.snapshot())[1][0]["hp"] == before
    for turn, actor in enumerate((victim, owner), 1):
        await fight.command("declare_phase", {"declarations": [{"reshape": [], "actor_id": actor, "kind": "defend"}]})
        with patch("combat_turn_start.dice_roll", return_value=SimpleNamespace(total=4)) as damage:
            packets = await fight.drain()
        damage.assert_called_once_with("2d8")
        tick = next(packet for packet in packets if packet.get("source_id") == chamber_id)
        assert tick["target_id"] == victim and tick["damage"] == 4 and tick["damage_type"] == "bludgeoning"
        state = await fight.reload()
        expected = before["current"] - 4 * turn
        assert state.get_participant(victim).hp_current == expected
        assert (await fight.snapshot())[1][0]["hp"]["current"] == expected


def strike(actor, target, action):
    return {
        "reshape": [],
        "kind": "attack",
        "actor_id": actor,
        "target_id": target,
        "action": action,
        "held_item_id": "",
        "rider": "",
    }


async def test_entomb_range_refuses_65_and_accepts_60(fight):
    owner, action = discover_entomb(fight)
    victim = fight.players[0]
    state = await fight.reload()
    state.spatial["positions"][victim] = pos(65)
    await fight.persist()
    before = await fight.snapshot()
    declarations = {"declarations": [strike(owner, victim, action)]}
    with patch("check_resolution.dice_roll") as save:
        assert "65 feet" in await fight.command("declare_phase", declarations, error=True)
    save.assert_not_called()
    assert await fight.snapshot() == before
    state = await fight.reload()
    state.spatial["positions"][victim] = pos(60)
    await fight.persist()
    assert (await fight.command("declare_phase", declarations))["accepted_actors"] == [owner]


@pytest.mark.parametrize("fight", [((20, 20), None)], indirect=True)
async def test_chamber_blocks_incoming_and_outgoing_lines(fight):
    owner, victim, chamber = await seal(fight)
    outsider = fight.players[1]
    before = await fight.snapshot()
    for action in (
        strike(owner, victim, "Geometry Strike"),
        strike(owner, victim, "Construct Slam"),
        strike(victim, owner, "Longsword"),
    ):
        assert chamber in await fight.command("declare_phase", {"declarations": [action]}, error=True)
        assert await fight.snapshot() == before
    result = await fight.command("declare_phase", {"declarations": [strike(owner, outsider, "Geometry Strike")]})
    assert result["accepted_actors"] == [owner]


async def favor(fight):
    await fight.pool.execute(
        "UPDATE players SET data=data || $2::jsonb WHERE player_id=$1",
        fight.players[0],
        '{"divine_favor":{"patron":"zhael","level":40,"max":100}}',
    )


@pytest.mark.parametrize("face,success", [(2, False), (20, True)])
async def test_held_entomb_save_reloads_without_reroll_or_second_spend(fight, face, success):
    owner, action = discover_entomb(fight)
    victim = fight.players[0]
    await favor(fight)
    await declare_attack(fight, owner, victim, action)
    await fight.command("resolve_phase", {})
    with (
        patch("check_resolution.dice_roll", return_value=_d20(face)) as save,
        patch("combat_recharge.roll", return_value=SimpleNamespace(total=4)) as recharge,
    ):
        offer = (await fight.command("resolve_phase", {}))["fate_offer"]
        assert (offer["roll_kind"], offer["roller_id"]) == ("save", victim)
        state = await fight.reload()
        assert state.get_participant(owner).action_ledger["entomb"]["remaining"] == 0
        assert not state.spatial.get("chambers")
        await fresh_session(fight, state)
        cast = next(p for p in await fight.drain() if p["actor_id"] == owner)
        assert cast["save_success"] is success
    save.assert_called_once()
    recharge.assert_called_once()
    state = await fight.reload()
    assert len(state.spatial.get("chambers", {})) == int(not success)
    assert state.get_participant(victim).hp_current == 100


async def test_compression_reuses_damage_receipt_across_concentration_hold(fight):
    _, victim, chamber = await seal(fight)
    await favor(fight)
    await update_player_concentration(victim, "divine_bless")
    fight.sd.concentration.spell_id = "divine_bless"
    defend = {"declarations": [{"reshape": [], "actor_id": victim, "kind": "defend"}]}
    await fight.command("declare_phase", defend)
    with (
        patch("combat_turn_start.dice_roll", return_value=SimpleNamespace(total=4)) as damage,
        patch("check_resolution.dice_roll", return_value=_d20(2)) as saves,
    ):
        offer = (await fight.command("resolve_phase", {}))["fate_offer"]
        assert (offer["roll_kind"], offer["roller_id"]) == ("save", victim)
        state = await fight.reload()
        assert state.get_participant(victim).hp_current == 96
        assert (await fight.snapshot())[1][0]["hp"]["current"] == 96
        await reload_held(fight, state)
        result = await fight.command("resolve_phase", {})
        tick = next(p for p in result["packets"] if p.get("source_id") == chamber)
        assert tick["concentration_broken"] == "divine_bless"
        assert (await fight.snapshot())[1][0]["hp"]["current"] == 96
        assert fight.sd.concentration.spell_id is None
        await fresh_session(fight, await fight.reload())
        await fight.drain()
        damage.assert_called_once_with("2d8")
        saves.assert_called_once()
        await fight.command("declare_phase", defend)
        await fight.drain()
    assert damage.call_count == 2
    assert (await fight.snapshot())[1][0]["hp"]["current"] == 92


def spell(actor, action, anchor):
    return {"kind": "ability", "actor_id": actor, "action": action, "targets": [anchor], "argument_type": ""}


@pytest.mark.parametrize("fight", [((20, 20), None)], indirect=True)
async def test_chamber_blocks_spells_and_keeps_its_own_wall_targetable(fight):
    owner, victim, chamber = await seal(fight)
    ally = fight.players[1]
    for actor in (victim, ally):
        await fight.pool.execute(
            "UPDATE players SET data=data || $2::jsonb WHERE player_id=$1", actor, '{"class":"cleric"}'
        )
        await seed_known_spells(fight.pool, actor, ("divine_flame_strike", "divine_heal_wounds", "divine_sacred_flame"))
    state = await fight.reload()
    state.spatial["positions"][ally] = pos(5, 0, 20)
    await fight.persist()
    for declaration in (
        spell(ally, "divine_heal_wounds", victim),
        spell(victim, "divine_sacred_flame", owner),
        spell(victim, "divine_flame_strike", owner),
        spell(ally, "divine_flame_strike", victim),
    ):
        assert chamber in await fight.command("declare_phase", {"declarations": [declaration]}, error=True)
    await fight.command("declare_phase", {"declarations": [spell(ally, "divine_flame_strike", chamber)]})
    with (
        patch("check_resolution.dice_roll", return_value=_d20(20)),
        patch("dice.roll", return_value=_damage_die(2)),
        patch("combat_turn_start.dice_roll", return_value=SimpleNamespace(total=4)),
    ):
        packets = await fight.drain()
    cast = next(p["cast"] for p in packets if p["actor_id"] == ally)
    assert ally in {r["target_id"] for r in cast["damage_results"]}
    assert chamber in {r["target_id"] for r in cast["damage_results"]}
    assert victim not in {r["target_id"] for r in cast["damage_results"]}
    await fight.command("declare_phase", {"declarations": [spell(victim, "divine_flame_strike", chamber)]})
    with (
        patch("check_resolution.dice_roll", return_value=_d20(20)),
        patch("dice.roll", return_value=_damage_die(2)),
        patch("combat_turn_start.dice_roll", return_value=SimpleNamespace(total=4)),
    ):
        packets = await fight.drain()
    cast = next(p["cast"] for p in packets if p["actor_id"] == victim)
    assert [r["target_id"] for r in cast["damage_results"]] == [chamber]
    result = await fight.command("declare_phase", {"declarations": [strike(victim, chamber, "Longsword")]})
    assert result["accepted_actors"] == [victim]


@pytest.mark.parametrize("fight", [((20,), "companion_kael")], indirect=True)
async def test_companion_compresses_when_unable_to_act(fight):
    state = await fight.reload()
    companion = next(p for p in state.participants if p.type == "companion")
    owner, victim, chamber = await seal(fight, companion.id)
    state = await fight.reload()
    target = state.get_participant(victim)
    target.conditions = apply_condition(target.conditions, "stunned", duration=1)
    await fight.persist()
    await fight.command("declare_phase", {"declarations": [{"reshape": [], "actor_id": owner, "kind": "defend"}]})
    with patch("combat_turn_start.dice_roll", return_value=SimpleNamespace(total=3)) as damage:
        packets = await fight.drain()
    damage.assert_called_once_with("2d8")
    assert next(p for p in packets if p.get("source_id") == chamber)["target_id"] == victim
    assert (await fight.reload()).get_participant(victim).hp_current == companion.hp_current - 3


async def test_live_chamber_blocks_an_already_declared_enemy_attack(fight):
    owner, action = discover_entomb(fight)
    victim = fight.players[0]
    state = await fight.reload()
    state.get_participant(owner).initiative = 30
    enemy = CombatParticipant(
        "archer",
        "Archer",
        "enemy",
        1,
        15,
        15,
        10,
        action_pool=[
            {"name": "Bow", "kind": "attack", "type": "ranged", "damage": "1d6", "damage_type": "piercing", "to_hit": 4}
        ],
    )
    state.participants.append(enemy)
    state.initiative_order.append(enemy.id)
    state.spatial["speeds"][enemy.id] = 30
    state.spatial["positions"][enemy.id] = pos(0, 0, 25)
    await fight.persist()
    await fight.command(
        "declare_phase", {"declarations": [strike(owner, victim, action), strike(enemy.id, victim, "Bow")]}
    )
    with patch("check_resolution.dice_roll", return_value=_d20(1)) as save:
        packets = await fight.drain()
    seal_packet, blocked = [p for p in packets if p["actor_id"] in (owner, enemy.id)]
    assert seal_packet["actor_id"] == owner and blocked["actor_id"] == enemy.id
    assert blocked["resolved"] is False and seal_packet["chamber_id"] in blocked["reason"]
    save.assert_called_once()
    assert (await fight.snapshot())[1][0]["hp"]["current"] == 100


async def test_immune_traveller_is_not_sealed(fight):
    owner, action = discover_entomb(fight)
    victim = fight.players[0]
    state = await fight.reload()
    state.get_participant(victim).condition_immunities = {"restrained": "test protection"}
    await fight.persist()
    await declare_attack(fight, owner, victim, action)
    with patch("check_resolution.dice_roll", return_value=_d20(1)):
        cast = next(p for p in await fight.drain() if p["actor_id"] == owner)
    assert not cast["save_success"] and cast["condition_immunity_source"] == "test protection"
    assert "chamber_id" not in cast and not (await fight.reload()).spatial.get("chambers")


async def test_grapple_and_chamber_keep_separate_turn_start_receipts(fight):
    _, victim, chamber = await seal(fight)
    state = await fight.reload()
    maw = CombatParticipant(
        "maw",
        "Mawling",
        "enemy",
        1,
        15,
        15,
        10,
        creature_id="hollow_mawling",
        turn_start_damage={"trigger": "grappled_by_source", "damage": "1d6", "damage_type": "necrotic"},
    )
    state.participants.append(maw)
    state.initiative_order.append(maw.id)
    state.spatial["speeds"][maw.id] = 30
    state.spatial["positions"][maw.id] = pos(5)
    target = state.get_participant(victim)
    target.conditions = apply_condition(target.conditions, "grappled", source=maw.id)
    await fight.persist()
    await favor(fight)
    await update_player_concentration(victim, "divine_bless")
    fight.sd.concentration.spell_id = "divine_bless"
    await fight.command("declare_phase", {"declarations": [{"reshape": [], "actor_id": victim, "kind": "defend"}]})
    with (
        patch(
            "combat_turn_start.dice_roll", side_effect=[SimpleNamespace(total=3), SimpleNamespace(total=4)]
        ) as damage,
        patch("check_resolution.dice_roll", side_effect=[_d20(19), _d20(2)]) as saves,
    ):
        for hp in (97, 93):
            assert (await fight.command("resolve_phase", {}))["fate_offer"]["roller_id"] == victim
            assert (await fight.snapshot())[1][0]["hp"]["current"] == hp
            await reload_held(fight, await fight.reload())
        result = await fight.command("resolve_phase", {})
        tick = next(p for p in result["packets"] if p.get("source_id") == maw.id)
        (compression,) = tick["turn_start_effects"]
        assert tick["damage"] == 3 and tick["concentration_broken"] is None
        assert (compression["source_id"], compression["damage"], compression["concentration_broken"]) == (
            chamber,
            4,
            "divine_bless",
        )
    assert saves.call_count == 2
    assert [call.args for call in damage.call_args_list] == [("1d6",), ("2d8",)]
    assert (await fight.snapshot())[1][0]["hp"]["current"] == 93
