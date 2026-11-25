"""Core martial actions through the registered combat and discovery tools."""

from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_architect_fight import fight as fight
from acceptance.test_architect_fight import pos
from acceptance.test_still_anchors import fresh_session
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory

import combat_spatial
import combat_structures
import db_mutations
import db_queries
from activate_tools import activate

SECOND_WIND = "warrior_second_wind"
RALLY = "warrior_rallying_shout"


@pytest.fixture
async def warriors(reset_db_pool: str, request: pytest.FixtureRequest):
    harness = MawlingHarness()
    try:
        await harness.prepare((6, 10), companion=getattr(request, "param", None), tools=(activate,))
        yield harness
    finally:
        await harness.close()


async def enter(harness: MawlingHarness) -> None:
    await harness.command("enter_mode", {"mode": "combat", "encounter_id": harness.encounter_id})


async def declare(harness: MawlingHarness, ability: str, targets: list[str], *, error: bool = False):
    actor = harness.players[0]
    state = await harness.reload()
    return await harness.command(
        "declare_phase",
        {
            "declarations": [
                {
                    "kind": "ability",
                    "actor_id": actor,
                    "action": ability,
                    "targets": targets,
                    "argument_type": "",
                    "reshape": [],
                },
                *({"kind": "defend", "actor_id": pid, "reshape": []} for pid in state.initiative_order if pid != actor),
            ]
        },
        error=error,
    )


@pytest.mark.parametrize(("hp", "healed"), [(40, 13), (95, 5)])
async def test_second_wind_heals_and_spends_once(warriors: MawlingHarness, hp: int, healed: int) -> None:
    actor = warriors.players[0]
    await db_mutations.update_player_hp(actor, hp)
    await enter(warriors)
    await declare(warriors, SECOND_WIND, [])
    with patch("dice.roll", return_value=_damage_die(7)) as rolled:
        packets = await warriors.drain()
    rolled.assert_called_once_with("1d10")
    receipt = next(packet for packet in packets if packet["actor_id"] == actor)
    assert receipt["healed"] == healed
    row = await db_queries.get_player(actor)
    assert row is not None
    assert row["hp"]["current"] == hp + healed
    assert row["stamina"]["current"] == 6
    state = await warriors.reload()
    participant = state.get_participant(actor)
    assert participant is not None and participant.hp_current == hp + healed
    assert "Second Wind" in await declare(warriors, SECOND_WIND, [], error=True)
    assert await db_queries.get_player(actor) == row
    if hp == 40:
        await warriors.command("end_combat", {"outcome": "fled"})
        await fresh_session(warriors)
        await enter(warriors)
        await declare(warriors, SECOND_WIND, [])
        with patch("dice.roll", return_value=_damage_die(7)):
            await warriors.drain()
        row = await db_queries.get_player(actor)
        assert row is not None and row["hp"]["current"] == 66 and row["stamina"]["current"] == 2


async def test_rallying_shout_requires_an_ally_outside_combat(warriors: MawlingHarness) -> None:
    actor = warriors.players[0]
    before = await db_queries.get_player(actor)
    refusal = await warriors.command("activate", {"id": RALLY}, error=True)
    assert "standing ally" in refusal
    assert await db_queries.get_player(actor) == before


@pytest.mark.parametrize("warriors", [None, "companion_kael"], indirect=True)
async def test_rallying_shout_lands_on_the_ally(warriors: MawlingHarness) -> None:
    actor, ally = warriors.players
    if warriors.sd.companion is not None:
        ally = warriors.sd.companion.id
    await enter(warriors)
    await declare(warriors, RALLY, [ally])
    await warriors.drain()
    state = await warriors.reload()
    recipient = state.get_participant(ally)
    assert recipient is not None
    assert any(condition["type"] == "precise_strike" for condition in recipient.conditions)
    row = await db_queries.get_player(actor)
    assert row is not None and row["stamina"]["current"] == 8
    abilities = await warriors.command("query_info", {"kind": "abilities"})
    rows = {row["id"]: row for row in abilities["abilities"]}
    assert all(
        rows[ability].get("combat") is not False for ability in (SECOND_WIND, RALLY, "warrior_devastating_strike")
    )


async def adjacent_foe(harness: MawlingHarness) -> str:
    state = await harness.reload()
    target = next(p for p in state.participants if p.type == "enemy")
    target.hp_current = target.hp_max = 100
    combat_spatial.place(state, target.id, combat_spatial.require_spatial(state)["positions"][harness.players[0]])
    await harness.persist()
    return target.id


@pytest.mark.parametrize(
    ("level", "face", "bonus"),
    [(1, 15, "1d8"), (9, 15, "1d8"), (10, 15, "2d8"), (16, 15, "2d8"), (17, 15, "3d8"), (20, 20, "6d8"), (6, 1, None)],
)
async def test_devastating_strike(warriors: MawlingHarness, level: int, face: int, bonus: str | None) -> None:
    actor = warriors.players[0]
    await warriors.pool.execute(
        "UPDATE players SET data=jsonb_set(data, '{level}', to_jsonb($2::int)) WHERE player_id=$1", actor, level
    )
    await enter(warriors)
    foe = await adjacent_foe(warriors)
    await declare(warriors, "warrior_devastating_strike", [foe])
    with (
        patch("check_resolution.dice_roll", return_value=_d20(face)),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)) as rolls,
    ):
        packets = await warriors.drain()
    damage_rolls = ["1d8"] * (1 + (face == 20))
    assert [call.args[0] for call in rolls.call_args_list] == ([*damage_rolls, bonus] if bonus is not None else [])
    receipt = next(packet for packet in packets if packet["actor_id"] == actor)
    expected = 4 * (len(damage_rolls) + 1) + 1 if bonus else 0
    assert receipt["damage"] == expected
    target = (await warriors.reload()).get_participant(foe)
    assert target is not None and target.hp_current == 100 - expected
    row = await db_queries.get_player(actor)
    assert row is not None and row["stamina"]["current"] == 7


@pytest.mark.parametrize(
    ("faces", "save", "stunned"),
    [([15], 1, True), ([15], 20, False), ([1], None, False), ([15, 15], 1, True)],
)
async def test_shield_bash_uses_weapon_then_con_save(
    warriors: MawlingHarness, faces: list[int], save: int | None, stunned: bool
) -> None:
    actor = warriors.players[0]
    if len(faces) == 2:
        await warriors.pool.execute(
            "UPDATE players SET data=jsonb_set(data, '{level}', '10'::jsonb) WHERE player_id=$1", actor
        )
        await db_mutations.set_player_flag(actor, "extra_attack", True)
    await enter(warriors)
    foe = await adjacent_foe(warriors)
    state = await warriors.reload()
    enemy = state.get_participant(foe)
    assert enemy is not None
    retaliation = {
        "kind": "attack",
        "actor_id": foe,
        "action": enemy.action_pool[0]["name"],
        "target_id": actor,
        "held_item_id": "",
        "rider": "",
        "reshape": [],
    }
    discovery = await warriors.command("query_info", {"kind": "abilities"})
    bash = next(row for row in discovery["abilities"] if row["id"] == "warrior_shield_bash")
    assert bash.get("combat") is not False
    await warriors.command(
        "declare_phase",
        {
            "declarations": [
                {
                    **bash["declaration"],
                    "actor_id": actor,
                    "action": "Longsword",
                    "target_id": foe,
                    "held_item_id": "",
                    "reshape": [],
                },
                *([retaliation] if stunned else []),
            ]
        },
    )
    with (
        patch(
            "check_resolution.dice_roll", side_effect=[_d20(n) for n in [*faces, *([save] if save else [])]]
        ) as rolls,
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        packets = await warriors.drain()
    assert rolls.call_count == len(faces) + (save is not None)
    receipt = next(packet for packet in packets if packet["actor_id"] == actor)
    assert receipt["damage"] == (5 * len(faces) if save is not None else 0)
    bash = receipt
    if len(faces) == 2:
        first, bash = receipt["attacks"]
        assert "save_success" not in first
    target = (await warriors.reload()).get_participant(foe)
    assert target is not None
    assert not any(c["type"] == "stunned" for c in target.conditions)
    if stunned:
        assert bash["condition_inflicted"] == "stunned"
        assert any(packet["actor_id"] == foe and "stunned" in packet.get("reason", "") for packet in packets)
        await warriors.command("declare_phase", {"declarations": [retaliation]})
        with patch("check_resolution.dice_roll", return_value=_d20(1)):
            next_round = await warriors.drain()
        assert any(packet["actor_id"] == foe and packet.get("hit") is False for packet in next_round)
    row = await db_queries.get_player(actor)
    assert row is not None and row["stamina"]["current"] == 8


async def test_rally_advantage_is_consumed_by_the_first_attack_roll(warriors: MawlingHarness) -> None:
    actor, ally = warriors.players
    await db_mutations.set_player_flag(ally, "extra_attack", True)
    await enter(warriors)
    foe = await adjacent_foe(warriors)
    state = await warriors.reload()
    combat_spatial.place(state, ally, combat_spatial.require_spatial(state)["positions"][actor])
    target = state.get_participant(foe)
    assert target is not None
    target.ac = 100
    await warriors.persist()
    await declare(warriors, RALLY, [ally])
    await warriors.drain()
    await warriors.command(
        "declare_phase",
        {
            "declarations": [
                {
                    "kind": "attack",
                    "actor_id": ally,
                    "action": "Longsword",
                    "target_id": foe,
                    "held_item_id": "",
                    "rider": "",
                    "reshape": [],
                }
            ]
        },
    )
    with patch("check_resolution.dice_roll", side_effect=[_d20(2), _d20(11), _d20(3)]) as rolls:
        packets = await warriors.drain()
    assert rolls.call_count == 3
    receipt = next(packet for packet in packets if packet["actor_id"] == ally)
    assert [(swing["roll"], swing["hit"]) for swing in receipt["attacks"]] == [(11, False), (3, False)]
    recipient = (await warriors.reload()).get_participant(ally)
    assert recipient is not None and not any(c["type"] == "precise_strike" for c in recipient.conditions)


@pytest.mark.parametrize(
    ("faces", "dice"),
    [
        ([1, 15], ["1d8", "2d8", "1d6"]),
        ([15, 15], ["1d8", "2d8", "1d6", "1d8", "1d6"]),
    ],
)
async def test_devastating_bonus_follows_the_first_hit(
    warriors: MawlingHarness, faces: list[int], dice: list[str]
) -> None:
    actor = warriors.players[0]
    await warriors.pool.execute(
        "UPDATE players SET data=jsonb_set(jsonb_set(data, '{level}', '10'::jsonb), "
        "'{equipment,main_hand,bonus_damage}', $2::jsonb) WHERE player_id=$1",
        actor,
        '{"dice":"1d6","damage_type":"fire"}',
    )
    await db_mutations.set_player_flag(actor, "extra_attack", True)
    await enter(warriors)
    foe = await adjacent_foe(warriors)
    await declare(warriors, "warrior_devastating_strike", [foe])
    with (
        patch("check_resolution.dice_roll", side_effect=[_d20(face) for face in faces]),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)) as rolls,
    ):
        packets = await warriors.drain()
    receipt = next(packet for packet in packets if packet["actor_id"] == actor)
    assert [attack["damage"] for attack in receipt["attacks"]] == ([0, 17] if faces[0] == 1 else [17, 13])
    assert [call.args[0] for call in rolls.call_args_list] == dice
    row = await db_queries.get_player(actor)
    assert row is not None and row["stamina"]["current"] == 7


@pytest.mark.parametrize("immune", [False, True])
async def test_shield_bash_respects_legendary_resistance_and_stun_immunity(fight: MawlingHarness, immune: bool) -> None:
    actor = fight.players[0]
    state = await fight.reload()
    assert state.architect_encounter is not None
    foe = state.architect_encounter["owner_id"]
    target = state.get_participant(foe)
    assert target is not None
    if immune:
        target.condition_immunities["stunned"] = "test worn protection"
    state.architect_encounter["reaction_round"] = state.round_number
    combat_spatial.place(state, foe, pos(5))
    combat_spatial.place(state, actor, pos(0))
    await fight.persist()
    await fight.command(
        "declare_phase",
        {
            "declarations": [
                {
                    "kind": "attack",
                    "actor_id": actor,
                    "action": "Longsword",
                    "target_id": foe,
                    "held_item_id": "",
                    "rider": "shield_bash",
                    "reshape": [],
                },
            ]
        },
    )
    with (
        patch("check_resolution.dice_roll", side_effect=[_d20(19), _d20(1)]),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        packets = await fight.drain()
    receipt = next(packet for packet in packets if packet["actor_id"] == actor)
    assert receipt["damage"] > 0
    assert receipt["save_success"] is not immune
    assert receipt.get("success_override") == (None if immune else "Legendary Resistance")
    assert receipt["condition_immune" if immune else "condition_resisted"] == "stunned"
    target = (await fight.reload()).get_participant(foe)
    assert target is not None and not target.conditions
    assert target.action_ledger["legendary resistance"]["remaining"] == (3 if immune else 2)


async def test_shield_bash_does_not_roll_a_save_for_a_fallen_foe(warriors: MawlingHarness) -> None:
    actor = warriors.players[0]
    await enter(warriors)
    foe = await adjacent_foe(warriors)
    state = await warriors.reload()
    target = state.get_participant(foe)
    assert target is not None
    target.hp_current = 1
    await warriors.persist()
    await warriors.command(
        "declare_phase",
        {
            "declarations": [
                {
                    "kind": "attack",
                    "actor_id": actor,
                    "action": "Longsword",
                    "target_id": foe,
                    "held_item_id": "",
                    "rider": "shield_bash",
                    "reshape": [],
                },
            ]
        },
    )
    with (
        patch("check_resolution.dice_roll", return_value=_d20(15)) as rolls,
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        packets = await warriors.drain()
    rolls.assert_called_once()
    receipt = next(packet for packet in packets if packet["actor_id"] == actor)
    assert receipt["target_fallen"] and "save_success" not in receipt


@pytest.fixture
async def rogue(warriors: MawlingHarness) -> MawlingHarness:
    await warriors.pool.execute(
        """UPDATE players SET data = (data - 'player_id') || '{"class":"rogue"}'
        WHERE player_id = $1""",
        warriors.players[0],
    )
    return warriors


def weapon_attack(actor: str, foe: str, rider: str) -> dict:
    return {
        "kind": "attack",
        "actor_id": actor,
        "target_id": foe,
        "action": "Longsword",
        "held_item_id": "",
        "rider": rider,
        "reshape": [],
    }


@pytest.mark.parametrize(("rider", "face"), [("dash", 15), ("hide", 18), ("hide", 2), ("", 15)])
async def test_cunning_action(rogue: MawlingHarness, rider: str, face: int) -> None:
    actor = rogue.players[0]
    await enter(rogue)
    foe = await adjacent_foe(rogue)
    state = await rogue.reload()
    spatial = combat_spatial.require_spatial(state)
    origin = combat_spatial.position(spatial, actor)
    speed = spatial["speeds"][actor]
    target = state.get_participant(foe)
    assert target is not None
    target.attributes["wisdom"] = 18
    if rider == "dash":
        combat_spatial.place(state, foe, {**origin, "x": origin["x"] + speed + 15})
    await rogue.persist()
    await rogue.command("declare_phase", {"declarations": [weapon_attack(actor, foe, rider)]})
    with (
        patch("check_resolution.dice_roll", side_effect=[_d20(15), _d20(face)] if rider == "hide" else [_d20(face)]),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        packets = await rogue.drain()
    packet = next(packet for packet in packets if packet["actor_id"] == actor)
    assert packet["hit"]
    player = await db_queries.get_player(actor)
    assert player is not None and player["stamina"]["current"] == (8 if rider else 10)
    if rider == "dash":
        assert packet["moved_ft"] == speed + 10
        live = combat_spatial.require_spatial(await rogue.reload())
        assert combat_spatial.position(live, actor)["x"] == origin["x"] + speed + 10
    if rider == "hide":
        assert packet["cunning_action"]["dc"] == 14
        assert packet["cunning_action"]["roll"] == face
        assert player["flags"]["concealed"] == (face == 18)
        await rogue.command("declare_phase", {"declarations": [weapon_attack(actor, foe, "")]})
        with patch("check_resolution.dice_roll", return_value=_d20(1)):
            await rogue.drain()
        player = await db_queries.get_player(actor)
        assert player is not None and not player["flags"]["concealed"]
        assert player["stamina"]["current"] == 8


async def test_cunning_action_discovery(rogue: MawlingHarness) -> None:
    await enter(rogue)
    result = await rogue.command("query_info", {"kind": "abilities"})
    row = next(row for row in result["abilities"] if row["id"] == "rogue_cunning_action")
    assert row.get("combat") is not False
    assert row["declaration"] == {"kind": "attack", "riders": ["dash", "hide", "disengage"]}
    refusal = await rogue.command("activate", {"id": row["id"]}, error=True)
    assert "weapon attack" in refusal
    for rider in row["declaration"]["riders"]:
        assert f'rider="{rider}"' in refusal


async def test_cunning_action_refusals(rogue: MawlingHarness) -> None:
    actor = rogue.players[0]
    await enter(rogue)
    foe = await adjacent_foe(rogue)
    unknown = weapon_attack(actor, foe, "teleport")
    assert "rider" in await rogue.command("declare_phase", {"declarations": [unknown]}, error=True)
    attack = weapon_attack(actor, foe, "dash")
    refusal = await rogue.command("declare_phase", {"declarations": [attack, attack]}, error=True)
    assert actor in refusal
    await rogue.pool.execute(
        "UPDATE players SET data=jsonb_set(data, '{stamina,current}', '1') WHERE player_id=$1", actor
    )
    before = (await rogue.reload()).to_dict()
    before_player = await db_queries.get_player(actor)
    assert before_player is not None and before_player["stamina"]["current"] == 1
    disengage = weapon_attack(actor, foe, "disengage")
    refusal = await rogue.command("declare_phase", {"declarations": [disengage]}, error=True)
    assert "Stamina" in refusal
    assert await db_queries.get_player(actor) == before_player
    assert (await rogue.reload()).to_dict() == before


async def test_devastating_strike_refuses_a_foe_behind_a_wall(fight: MawlingHarness) -> None:
    actor = fight.players[0]
    state = await fight.reload()
    assert state.architect_encounter is not None
    foe = state.architect_encounter["owner_id"]
    combat_spatial.place(state, actor, pos(0))
    combat_spatial.place(state, foe, pos(5))
    combat_structures.add_wall(state, "test_wall", "Test Wall", pos(2.5, -5), pos(2.5, 5))
    await fight.persist()
    row = await db_queries.get_player(actor)
    assert row is not None
    refused = await declare(fight, "warrior_devastating_strike", [foe], error=True)
    assert "Line blocked by Test Wall" in refused
    after = await db_queries.get_player(actor)
    assert after is not None and after["stamina"]["current"] == row["stamina"]["current"]
