"""Retreat through the registered combat tools and persisted phase state."""

from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance._enemy_opportunity_helpers import attack, declare, resolve_allies, strikes
from acceptance._enemy_opportunity_helpers import fight as fight
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_architect_fight import pos
from acceptance.test_opportunity_strike import participant, reconnect, stamina
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory

import db_queries
from combat_spatial import require_spatial
from combat_structures import add_wall

SINGLE = {"placements": {"bandit": pos(0)}}
CLERIC = {**SINGLE, "ally": {"class": "cleric"}}
ROGUE = {**SINGLE, "player": {"class": "rogue", "stamina": {"current": 2, "max": 10}}}


def retreat(actor: str, rider: str = "") -> dict:
    return {"kind": "retreat", "actor_id": actor, "rider": rider}


def receipt(packets: list[dict], actor: str) -> dict:
    (result,) = (packet for packet in packets if packet["actor_id"] == actor)
    assert result["declaration_type"] == "retreat"
    return result


@pytest.mark.parametrize("fight,drop", [(SINGLE, None), (CLERIC, False), (CLERIC, True)], indirect=["fight"])
async def test_withdrawal_provokes_once_and_finishes_from_reach_edge(fight: MawlingHarness, drop: bool | None) -> None:
    mover = fight.players[0]
    state = await fight.reload()
    starting_hp = 3 if drop else 100
    participant(state, mover).hp_current = starting_hp
    bandit_hp = participant(state, "bandit").hp_current
    starting_stamina = await stamina(mover)
    await fight.persist()
    await declare(fight, retreat(mover))
    packets = []
    with (
        patch("check_resolution.dice_roll", return_value=_d20(18)) as rolls,
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)) as damage,
    ):
        if drop is not None:
            held = await fight.command("resolve_phase", {})
            waiting = held["next"]["waiting_on"]
            assert waiting and waiting["stage"] == "pre_roll"
            packets.extend(held["packets"])
            paused = await fight.reload()
            assert require_spatial(paused)["positions"][mover] == pos(5)
            continuation = paused.ally_continuation
            assert continuation is not None
            route = continuation["steps"]["movement_route"]
            assert route["endpoint"] == pos(33)
            assert route["execution_id"] == paused.held_actions[0]["execution_id"]
            rolls.assert_not_called()
            await reconnect(fight)
        packets.extend(await resolve_allies(fight))
        rolls.assert_called_once()
        damage.assert_called_once()
    (strike,) = strikes(packets)
    assert (strike["actor_id"], strike["target_id"], strike["interrupt_position"]) == ("bandit", mover, pos(5))
    result = receipt(packets, mover)
    assert packets.index(strike) < packets.index(result)
    assert result["resolved"] is (not drop)
    assert result["moved_ft"] == result["movement_spent_ft"] == (2 if drop else 30)
    state = await fight.reload()
    positions = require_spatial(state)["positions"]
    assert positions[mover] == result["destination"] == pos(5 if drop else 33)
    assert positions["bandit"] == pos(0)
    assert positions[fight.players[1]] == pos(-30)
    assert participant(state, "bandit").hp_current == bandit_hp
    assert state.reactions_available["bandit"]["spent"]
    assert not state.ally_continuation and not any(head.get("opportunity_attack") for head in state.held_actions)
    assert participant(state, mover).is_fallen is bool(drop)
    player = await db_queries.get_player(mover)
    assert player is not None
    assert player["stamina"]["current"] == starting_stamina
    assert participant(state, mover).hp_current == player["hp"]["current"] == max(0, starting_hp - 4)
    if drop is False:
        assert not strikes(await fight.drain())
        assert participant(await fight.reload(), mover).hp_current == starting_hp - 4


@pytest.mark.parametrize(
    "fight,origin,expected",
    [
        ({"placements": {"bandit": pos(0, z=10)}}, pos(3), pos(33)),
        ({"placements": {"bandit": pos(-3), "lookout": pos(9)}}, pos(0), pos(-30)),
        ({"placements": {"bandit": pos(0, -3), "lookout": pos(0, 9)}}, pos(0), pos(0, -30)),
        ({"placements": {"bandit": pos(-3), "lookout": pos(9, 8)}}, pos(0), pos(-18, -24)),
        ({"placements": {"bandit": pos(5), "lookout": pos(-2), "third": pos(-3)}}, pos(0), pos(30)),
        ({"placements": {"bandit": pos(3), "lookout": pos(-3)}}, pos(0), pos(-30)),
        ({"placements": {"lookout": pos(-3), "bandit": pos(3)}}, pos(0), pos(-30)),
    ],
    indirect=["fight"],
)
async def test_withdrawal_direction(fight: MawlingHarness, origin: dict, expected: dict) -> None:
    mover = fight.players[0]
    require_spatial(await fight.reload())["positions"][mover] = origin
    await fight.persist()
    await declare(fight, retreat(mover))
    with patch("check_resolution.dice_roll", return_value=_d20(1)):
        result = receipt(await resolve_allies(fight), mover)
    assert result["resolved"]
    assert result["moved_ft"] == result["movement_spent_ft"] == pytest.approx(30)
    assert result["destination"] == pytest.approx(expected)
    assert require_spatial(await fight.reload())["positions"][mover] == result["destination"]


@pytest.mark.parametrize(
    "fight",
    [{**SINGLE, "placements": {**SINGLE["placements"], **{key: pos(20) for key in ("fallen", "dead", "down")}}}],
    indirect=True,
)
async def test_only_standing_foes_set_direction(fight: MawlingHarness) -> None:
    mover, ally = fight.players
    state = await fight.reload()
    require_spatial(state)["positions"][ally] = pos(30, 5)
    participant(state, "fallen").is_fallen = True
    participant(state, "dead").is_dead = True
    participant(state, "down").hp_current = 0
    add_wall(state, "wall", "Slate Wall", pos(20, 10), pos(20, 15))
    await fight.persist()
    await fight.command("declare_phase", {"declarations": [retreat(mover)]})
    with patch("check_resolution.dice_roll", return_value=_d20(1)):
        result = receipt(await resolve_allies(fight), mover)
    assert result["destination"] == pos(33)


@pytest.mark.parametrize("fight", [ROGUE], indirect=True)
@pytest.mark.parametrize("speed", [30, 0])
async def test_disengage_retreat_charges_only_for_movement(fight: MawlingHarness, speed: int) -> None:
    mover = fight.players[0]
    require_spatial(await fight.reload())["speeds"][mover] = speed
    await fight.persist()
    await declare(fight, retreat(mover, "disengage"))
    with patch("check_resolution.dice_roll") as rolls:
        packets = await resolve_allies(fight)
        rolls.assert_not_called()
    assert not strikes(packets)
    result = receipt(packets, mover)
    assert result["resolved"] and result["moved_ft"] == speed
    state = await fight.reload()
    assert not state.reactions_available["bandit"]["spent"]
    assert require_spatial(state)["positions"][mover] == result["destination"] == pos(3 + speed)
    assert await stamina(mover) == (0 if speed else 2)
    if speed:
        assert result["cunning_action"] == {"rider": "disengage"}


@pytest.mark.parametrize(
    "fight,rider,condition,reason",
    [
        (SINGLE, "disengage", None, "Cunning Action"),
        (
            {**ROGUE, "player": {**ROGUE["player"], "stamina": {"current": 1, "max": 10}}},
            "disengage",
            None,
            "stamina",
        ),
        (SINGLE, "", "grappled", "grappled"),
        (SINGLE, "", "restrained", "restrained"),
    ],
    indirect=["fight"],
)
async def test_retreat_refusal_leaves_state_untouched(
    fight: MawlingHarness, rider: str, condition: str | None, reason: str
) -> None:
    mover = fight.players[0]
    if condition:
        participant(await fight.reload(), mover).conditions = [{"type": condition, "source": "bandit"}]
        await fight.persist()
    before = await fight.snapshot()
    error = await fight.command("declare_phase", {"declarations": [retreat(mover, rider)]}, error=True)
    assert reason.lower() in error.lower()
    assert await fight.snapshot() == before


@pytest.mark.parametrize("fight", [SINGLE], indirect=True)
@pytest.mark.parametrize("wall_x", [4, 12, None])
async def test_retreat_stops_for_walls_and_terrain(fight: MawlingHarness, wall_x: int | None) -> None:
    mover = fight.players[0]
    state = await fight.reload()
    if wall_x is not None:
        add_wall(state, "wall", "Slate Wall", pos(wall_x, -5), pos(wall_x, 5))
    else:
        require_spatial(state).setdefault("movement_areas", {})["mud"] = {
            "shape": "rectangle",
            "kind": "mud",
            "min": pos(2, -5),
            "max": pos(34, 5),
            "excluded_actor_ids": [],
        }
    await fight.persist()
    await declare(fight, retreat(mover))
    with patch("check_resolution.dice_roll", return_value=_d20(1)):
        packets = await resolve_allies(fight)
    result = receipt(packets, mover)
    state = await fight.reload()
    assert result["resolved"]
    assert result["destination"] == require_spatial(state)["positions"][mover]
    assert result["moved_ft"] == pytest.approx((wall_x - 3) if wall_x else 15)
    if wall_x:
        assert 3 < result["destination"]["x"] < wall_x
    else:
        assert result["movement_spent_ft"] == 30
    assert [strike["interrupt_position"] for strike in strikes(packets)] == ([] if wall_x == 4 else [pos(5)])
    assert state.reactions_available["bandit"]["spent"] is (wall_x != 4)


@pytest.mark.parametrize("fight", [SINGLE], indirect=True)
async def test_choir_pull_consumes_the_retreat(fight: MawlingHarness) -> None:
    mover = fight.players[0]
    participant(await fight.reload(), mover).conditions = [
        {"type": "charmed", "choir_melody": True, "source": "bandit"}
    ]
    await fight.persist()
    await declare(fight, retreat(mover))
    (result,) = (packet for packet in await resolve_allies(fight) if packet["actor_id"] == mover)
    assert result["forced_movement"]
    assert require_spatial(await fight.reload())["positions"][mover] == result["destination"] == pos(0)


@pytest.mark.parametrize("fight", [SINGLE], indirect=True)
async def test_retreat_after_the_last_foe_falls(fight: MawlingHarness) -> None:
    first, mover = fight.players
    state = await fight.reload()
    participant(state, first).initiative = 30
    participant(state, "bandit").hp_current = 1
    await fight.persist()
    await declare(fight, attack(first, "bandit", "Longsword"), retreat(mover))
    with (
        patch("check_resolution.dice_roll", return_value=_d20(18)),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        result = receipt(await resolve_allies(fight), mover)
    assert not result["resolved"]
    assert result["reason"] == "no standing foe to retreat from"
    assert require_spatial(await fight.reload())["positions"][mover] == result["destination"] == pos(-30)


@pytest.mark.parametrize("fight", [{**SINGLE, "companion": "companion_kael"}], indirect=True)
async def test_companion_retreat(fight: MawlingHarness) -> None:
    companion = "companion_kael"
    state = await fight.reload()
    origin = require_spatial(state)["positions"][companion]
    speed = require_spatial(state)["speeds"][companion]
    await declare(fight, retreat(companion))
    result = receipt(await resolve_allies(fight), companion)
    assert result["resolved"]
    assert (
        require_spatial(await fight.reload())["positions"][companion]
        == result["destination"]
        == pos(origin["x"] + speed, origin["y"], origin["z"])
    )


async def test_enemy_retreat_leaves_enemy_position_unchanged(fight: MawlingHarness) -> None:
    await declare(fight, retreat("bandit"))
    result = receipt(await fight.drain(), "bandit")
    assert not result["resolved"]
    assert require_spatial(await fight.reload())["positions"]["bandit"] == pos(0)
