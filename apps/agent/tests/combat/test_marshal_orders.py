"""Marshal orders through the registered tools and persisted combat."""

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from acceptance.mawling_harness import MawlingHarness
from sample_fixtures import published_payloads
from voice_condition_fixtures import spatial_record

import abilities
import ability_persistence
import combat_structures
import db_queries
from activate_tools import activate
from session_data import CompanionState

DIRECT = "marshal_direct_strike"
REPOSITION = "marshal_reposition"
COORDINATED = "marshal_coordinated_assault"
MEDIC = "marshal_field_medic_order"
SACRIFICE = "marshal_sacrifice_play"
ORDERS = [
    (DIRECT, 2, (1, 3), 2, 0),
    (REPOSITION, 2, (1,), 0, 2),
    (COORDINATED, 2, (2, 1), 4, 0),
    (MEDIC, 4, (1,), 3, 0),
    (SACRIFICE, 8, (1,), 0, 4),
]


@pytest.fixture
def mock_combat_agent_factory() -> None:
    return None


@pytest.fixture
async def marshal(dev_db_pool):
    harness = MawlingHarness()

    async def prepare(
        level: int,
        *,
        focus: int = 8,
        extra_ally: bool = False,
        stamina: int = 8,
        owned: tuple[str, ...] = (),
        location: str = "greyvale_wilderness_north",
    ) -> MawlingHarness:
        levels = (level, 2, 2, 2) if extra_ally else (level, 2, 2)
        await harness.prepare(levels, companion=None, location=location, tools=(activate,))
        pid = harness.players[0]
        player = await db_queries.get_player(pid)
        assert player is not None
        player.update({"class": "marshal"})
        player["focus"]["current"] = focus
        player["stamina"]["current"] = stamina
        await harness.pool.execute("UPDATE players SET data=$2::jsonb WHERE player_id=$1", pid, json.dumps(player))
        for ability_id in owned:
            await harness.pool.execute(
                "INSERT INTO character_abilities (player_id, ability_id, equipped) VALUES ($1,$2,FALSE)",
                pid,
                ability_id,
            )
        return harness

    try:
        yield prepare
    finally:
        await harness.close()


async def enter(harness: MawlingHarness) -> None:
    with patch("combat_resolution.dice_roll", return_value=SimpleNamespace(total=12)):
        result = await harness.command("enter_mode", {"mode": "combat", "encounter_id": harness.encounter_id})
    harness.enemies = [p["id"] for p in result["participants"] if p["type"] == "enemy"]
    state = await harness.reload()
    for pid, initiative in zip(harness.players[:3], (20, 25, 15), strict=True):
        participant = state.get_participant(pid)
        assert participant is not None
        participant.initiative = initiative
    await harness.persist()


async def declare(harness: MawlingHarness, order: str, targets: list[str], *, error: bool = False, attack=None):
    state = await harness.reload()
    actor = harness.players[0]
    payload = dict(kind="ability", actor_id=actor, action=order, targets=targets, argument_type="")
    if order == REPOSITION:
        target = targets[0] if targets else ""
        positions = spatial_record(state)["positions"]
        origin = positions.get(target, positions[actor])
        payload = dict(
            kind="reposition", actor_id=actor, target_id=target, destination={**origin, "x": origin["x"] + 1}
        )
    return await harness.command(
        "declare_phase",
        {
            "declarations": [
                payload,
                *(
                    attack
                    if attack and participant.id == attack["actor_id"]
                    else dict(kind="defend", actor_id=participant.id, reshape=[])
                    for participant in state.participants
                    if participant.id != actor and not (participant.is_fallen or participant.is_structure)
                ),
            ]
        },
        error=error,
    )


def pools(player: dict) -> dict[str, int]:
    return {pool: player[pool]["current"] for pool in ("focus", "stamina")}


def target_facts(state, targets: list[str]) -> list[tuple]:
    return [
        (p.hp_current, p.conditions, state.spatial["positions"][pid])
        for pid in targets
        if (p := state.get_participant(pid)) is not None
    ]


@pytest.mark.parametrize("order,level,slots,focus,stamina", [row for row in ORDERS if row[0] != SACRIFICE])
async def test_order_resolves_in_initiative_order(marshal, order, level, slots, focus, stamina) -> None:
    owned = (order,) if order == MEDIC else ()
    harness = await marshal(level, focus=focus or 8, stamina=stamina or 8, owned=owned)
    await enter(harness)
    actor = harness.players[0]
    roster = [*harness.players, *harness.enemies]
    targets = [roster[slot] for slot in slots]
    rows = (await harness.command("query_info", {"kind": "abilities"}))["abilities"]
    command_id = next(row["id"] for row in rows if row["id"] == order)
    before_targets = target_facts(await harness.reload(), targets)
    _, before_players = await harness.snapshot()
    if order == DIRECT:
        assert f"declare {command_id}" in await harness.command("activate", {"id": command_id}, error=True)
    result = await declare(harness, command_id, targets)
    assert result["beat"] == "resolution" and "packets" not in result
    assert (await harness.snapshot())[1] == before_players

    result = await harness.command("resolve_phase", {})
    packets = result["packets"]
    assert [packet["actor_id"] for packet in packets] == [harness.players[i] for i in (1, 0, 2)]
    receipt = packets[1]
    authored = abilities.get_ability(order)
    deducted = {"focus": focus, "stamina": stamina}
    expected = dict(
        actor_id=actor,
        resolved=True,
        declaration_type="ability",
        action=order,
        name=authored.name,
        target_ids=targets,
        effect_resolution="engine",
        effect=authored.effect,
        narration_cue=authored.narration_cue,
        deducted=deducted,
    )
    assert {key: receipt[key] for key in expected} == expected
    assert "rally_grant" not in receipt
    live = await harness.reload()
    if order == DIRECT:
        ally, foe = targets
        assert live.order_riders == {
            ally: [dict(kind="direct_strike", target_id=foe, expires_round=2, order_id=DIRECT, source_id=actor)]
        }
    if order == MEDIC:
        [ally] = targets
        rider = dict(kind="field_medic", expires_round=2, order_id=MEDIC, source_id=actor)
        assert live.order_riders == {ally: [rider]}
        assert receipt["order_rider_grant"] == {
            **rider,
            "recipient_id": ally,
            "name": "Field Medic Order",
            "declaration_kind": "attack_consume",
            "replaced": None,
        }
    if order == COORDINATED:
        grants = receipt["order_rider_grant"]["recipients"]
        assert [grant["recipient_id"] for grant in grants] == targets
        for grant, partner in zip(grants, reversed(targets), strict=True):
            [rider] = live.order_riders[grant["recipient_id"]]
            assert rider["partner_id"] == partner and rider["source_id"] == actor
    assert live.encounter_facts["rally_pending"] == {}
    assert "zhael_moment_to_rally" not in live.encounter_facts["once_spent"]
    if order == REPOSITION:
        [(hp, conditions, origin)] = before_targets
        assert target_facts(live, targets) == [(hp, conditions, {**origin, "x": origin["x"] + 1})]
    else:
        assert target_facts(live, targets) == before_targets
    _, after_players = await harness.snapshot()
    assert pools(after_players[0]) == {pool: value - deducted[pool] for pool, value in pools(before_players[0]).items()}
    assert list(map(pools, after_players[1:])) == list(map(pools, before_players[1:]))
    remaining = await harness.drain()
    assert all(packet.get("action") != order for packet in remaining)
    _, wrapped_players = await harness.snapshot()
    assert pools(wrapped_players[0]) == pools(after_players[0])


async def test_discovery_at_level_eight(marshal) -> None:
    harness = await marshal(8, owned=(MEDIC, SACRIFICE))
    await enter(harness)
    rows = {row["id"]: row for row in (await harness.command("query_info", {"kind": "abilities"}))["abilities"]}
    assert all(rows[order]["combat"] is True for order, *_ in ORDERS)


async def test_direct_strike_activation_outside_combat(marshal) -> None:
    from _zhael_fate_fixtures import game_tools
    from acceptance.test_architect_terrain import set_favor
    from test_encounter_facts_damage import dice

    from check_tools import check

    harness = await marshal(2)
    await set_favor(harness, "zhael", 40)
    await harness.pool.execute(
        """UPDATE players SET data=data || '{"patron_gifts":{"zhael_fates_thread":{"spent":true},
        "zhael_lucky":{"spent":true}}}'::jsonb WHERE player_id=$1""",
        harness.players[0],
    )
    actor = harness.players[0]
    before = await db_queries.get_player(actor)
    assert before is not None
    ability = abilities.get_ability(DIRECT)
    assert await harness.command("activate", {"id": DIRECT}) == dict(
        effect=ability.effect,
        narration_cue=ability.narration_cue,
        deducted={"stamina": 0, "focus": 2},
        variable_cost=None,
    )
    after = await db_queries.get_player(actor)
    assert after is not None
    assert pools(after) == {"focus": pools(before)["focus"] - 2, "stamina": pools(before)["stamina"]}
    assert after.get("conditions") == before.get("conditions")
    assert harness.sd.combat_state is None
    with dice(10):
        rolled = await game_tools(harness.sd, check)(
            "check", roll={"kind": "save", "save_type": "wisdom", "dc": 11, "effect_on_fail": "shaken"}
        )
    assert "rally_bonuses" not in rolled


async def refuse(harness: MawlingHarness, order: str, targets: list[str], reason: str) -> None:
    before = await harness.snapshot()
    assert reason in await declare(harness, order, targets, error=True), (order, targets, reason)
    assert await harness.snapshot() == before, (order, targets, reason)


async def test_invalid_orders_leave_declaration_and_resources_unchanged(marshal) -> None:
    harness = await marshal(4)
    await enter(harness)
    actor, ally, _ = harness.players
    foe, other_foe = harness.enemies
    state = await harness.reload()
    combat_structures.add_wall(state, "wall", "Wall", {"x": 200, "y": 0, "z": 0}, {"x": 200, "y": 5, "z": 0})
    await harness.persist()
    for order, targets, reason in (
        (DIRECT, [ally], "one ally and one foe"),
        (DIRECT, [foe], "one ally and one foe"),
        (DIRECT, [ally, foe, other_foe], "one ally and one foe"),
        (DIRECT, [foe, other_foe], "requires an ally"),
        (DIRECT, [ally, ally], "requires a foe"),
        (DIRECT, [ally, "wall"], "requires a foe"),
        (DIRECT, [actor, foe], "cannot command themselves"),
        (DIRECT, [ally, "missing"], "Unknown order target"),
        (REPOSITION, [], "requires one ally"),
        (REPOSITION, [foe], "requires an ally"),
        (REPOSITION, [actor], "cannot command themselves"),
        (COORDINATED, [ally], "two distinct allies"),
        (COORDINATED, [ally, ally], "two distinct allies"),
        (COORDINATED, [ally, foe], "requires an ally"),
        (MEDIC, [ally], "hasn't learned Field Medic Order"),
    ):
        await refuse(harness, order, targets, reason)

    await ability_persistence.update_player_resources(actor, focus=1)
    await refuse(harness, DIRECT, [ally, foe], "Not enough Focus")
    await ability_persistence.update_player_resources(actor, stamina=1)
    await refuse(harness, REPOSITION, [ally], "Not enough Stamina")

    await ability_persistence.update_player_resources(actor, stamina=8)
    state = await harness.reload()
    participant = state.get_participant(ally)
    participant.is_fallen = True
    await harness.persist()
    await refuse(harness, REPOSITION, [ally], "standing ally")
    participant = (await harness.reload()).get_participant(ally)
    participant.is_fallen = False
    participant.hp_current = 0
    await harness.persist()
    await refuse(harness, REPOSITION, [ally], "standing ally")


async def test_field_medic_cannot_command_a_companion(marshal) -> None:
    harness = await marshal(4, owned=(MEDIC,))
    companion = "companion_kael"
    harness.sd.companion = CompanionState(id=companion, name="Kael")
    await enter(harness)
    assert (await harness.reload()).get_participant(companion).type == "companion"
    events = published_payloads(harness.sd.room)
    await refuse(harness, MEDIC, [companion], "player ally")
    assert published_payloads(harness.sd.room) == events


async def test_late_resource_loss_reopens_declaration(marshal) -> None:
    harness = await marshal(2, focus=2)
    await enter(harness)
    actor, ally, _ = harness.players
    targets = [ally, harness.enemies[0]]
    before_state = await harness.reload()
    await declare(harness, DIRECT, targets)
    await ability_persistence.update_player_resources(actor, focus=1)
    _, before_players = await harness.snapshot()
    assert "Not enough Focus" in await harness.command("resolve_phase", {}, error=True)
    state, after_players = await harness.snapshot()
    assert state["beat"] == "declaration" and not state["pending_declarations"]
    assert after_players == before_players
    assert target_facts(await harness.reload(), targets) == target_facts(before_state, targets)


async def test_direct_strike_is_wasted_if_earlier_ally_kills_foe(marshal) -> None:
    from acceptance.test_architect_terrain import set_favor

    harness = await marshal(2)
    await set_favor(harness, "zhael", 40)
    actor_id = harness.players[0]
    await harness.pool.execute(
        """UPDATE players SET data=data || '{"patron_gifts":{"zhael_fates_thread":{"spent":true},
        "zhael_lucky":{"spent":true}}}'::jsonb WHERE player_id=$1""",
        actor_id,
    )
    await enter(harness)
    actor, ally, _ = harness.players
    foe = harness.enemies[0]
    state = await harness.reload()
    state.get_participant(foe).hp_current = 1
    state.spatial["positions"][ally] = {"x": 0, "y": 0, "z": 0}
    state.spatial["positions"][foe] = {"x": 5, "y": 0, "z": 0}
    await harness.persist()
    before = await db_queries.get_player(actor)
    await declare(
        harness,
        DIRECT,
        [ally, foe],
        attack=dict(
            kind="attack",
            actor_id=ally,
            action="Longsword",
            target_id=foe,
            held_item_id="",
            rider="",
            reshape=[],
            quick_fingers_mode="",
            quick_fingers_item="",
        ),
    )
    with (
        patch("check_resolution.dice_roll", return_value=SimpleNamespace(total=16)),
        patch("check_resolution_attack.dice_roll", return_value=SimpleNamespace(total=4)),
    ):
        packets = (await harness.command("resolve_phase", {}))["packets"]
    assert packets[0]["actor_id"] == ally and packets[0]["hit"]
    assert (await harness.reload()).get_participant(foe).is_fallen
    receipt = packets[1]
    assert receipt["actor_id"] == actor and receipt["resolved"] is False and "standing foe" in receipt["reason"]
    assert await db_queries.get_player(actor) == before
    facts = (await harness.reload()).encounter_facts
    assert facts["rally_pending"] == {} and "zhael_moment_to_rally" not in facts["once_spent"]


async def test_direct_strike_speaks_to_ally_and_checks_hostility_against_foe(marshal) -> None:
    harness = await marshal(2)
    await enter(harness)
    actor, ally, _ = harness.players
    foe = harness.enemies[0]
    state = await harness.reload()
    state.get_participant(ally).conditions = [{"type": "deafened", "source": foe, "duration": None}]
    await harness.persist()
    await refuse(harness, DIRECT, [ally, foe], "cannot hear")

    state = await harness.reload()
    state.get_participant(ally).conditions = []
    state.get_participant(actor).conditions = [{"type": "charmed", "source": foe, "duration": None}]
    await harness.persist()
    await refuse(harness, DIRECT, [ally, foe], "cannot act hostilely")

    state = await harness.reload()
    state.get_participant(actor).conditions = []
    state.get_participant(foe).conditions = [{"type": "deafened", "source": actor, "duration": None}]
    await harness.persist()
    await declare(harness, DIRECT, [ally, foe])
    packets = (await harness.command("resolve_phase", {}))["packets"]
    assert packets[1]["actor_id"] == actor and packets[1]["resolved"] is True
