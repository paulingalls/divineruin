"""Reposition through registered combat tools and persisted state."""

import json
from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20
from acceptance.test_architect_terrain import set_favor
from combat.test_marshal_orders import REPOSITION, enter
from combat.test_marshal_orders import marshal as marshal
from combat.test_marshal_orders import mock_combat_agent_factory as mock_combat_agent_factory
from livekit.agents.llm import ToolContext
from test_aelora_gift import _live_party
from test_patron_engine_nythera_tidewalker import area
from test_patron_engine_thyra_thornwall import SEGMENT, move
from voice_condition_fixtures import participant, spatial_record

import combat_structures
import combat_turn
import reaction_spend


def point(x: float, y: float = 0) -> dict[str, float]:
    return {"x": x, "y": y, "z": 0}


async def battlefield(marshal, *, patrons=(), encounter: str = ""):
    location = {
        "hollow_architect": "ashmark_architect_works",
        "hollow_veilrender_boss": "ashmark_corrupted_front",
    }.get(encounter, "greyvale_wilderness_north")
    harness = await marshal(2, location=location)
    for index, patron in enumerate(patrons):
        if patron is None:
            continue
        await harness.pool.execute(
            "UPDATE players SET data=jsonb_set(data, '{divine_favor}', $2::jsonb) WHERE player_id=$1",
            harness.players[index],
            json.dumps(dict(patron=patron, level=40, max=100)),
        )
    if encounter:
        harness.encounter_id = encounter
    await enter(harness)
    state = await harness.reload()
    actor, ally, other = harness.players
    spatial = spatial_record(state)
    spatial["positions"].update(
        {
            actor: point(0, 10),
            ally: point(0),
            other: point(30, 20),
            harness.enemies[0]: point(-3),
            **{foe: point(-30) for foe in harness.enemies[1:]},
        }
    )
    if not encounter:
        spatial.pop("movement_areas", None)
    participant(state, actor).initiative = 30
    await harness.persist()
    return harness


def order(harness, destination):
    actor, ally, _ = harness.players
    return dict(kind="reposition", actor_id=actor, target_id=ally, destination=destination)


async def declare(harness, *actions, error=False, omit=()):
    state = await harness.reload()
    selected = {action["actor_id"] for action in actions} | set(omit)
    defaults = [
        dict(kind="defend", actor_id=p.id, reshape=[])
        for p in state.participants
        if p.id not in selected and not p.is_structure
    ]
    return await harness.command("declare_phase", {"declarations": [*actions, *defaults]}, error=error)


@pytest.mark.parametrize(("provider", "key"), [("anthropic", "input_schema"), ("openai", "parameters")])
def test_strict_schema_requires_a_destination(provider, key):
    tool = ToolContext([combat_turn.declare_phase]).parse_function_tools(provider, strict=True)[0]
    schema = tool.get("function", tool)[key]
    items = schema["properties"]["declarations"]["items"]
    variants = items.get("anyOf") or items["oneOf"]
    branch = next(branch for branch in variants if branch["$ref"] == "#/$defs/RepositionDecl")
    variant = schema["$defs"][branch["$ref"].split("/")[-1]]
    assert set(variant["required"]) == {"kind", "actor_id", "target_id", "destination"}
    dest = schema["$defs"][variant["properties"]["destination"]["$ref"].split("/")[-1]]
    assert set(dest["required"]) == {"x", "y", "z"}
    assert all(prop["type"] == "number" for prop in dest["properties"].values())


async def test_legacy_declaration_names_the_recovery_recipe(marshal):
    harness = await battlefield(marshal)
    actor, ally, _ = harness.players
    before = await harness.snapshot()
    reason = await declare(
        harness, dict(kind="ability", actor_id=actor, action=REPOSITION, targets=[ally], argument_type=""), error=True
    )
    assert 'kind="reposition"' in reason and "destination" in reason
    assert await harness.snapshot() == before


@pytest.mark.parametrize("commanded", [False, True])
async def test_reposition_crosses_reach_without_an_opportunity(marshal, commanded):
    harness = await battlefield(marshal)
    actor, ally, _ = harness.players
    foe = harness.enemies[0]
    before_state, before_players = await harness.snapshot()
    endpoint = point(15)
    await declare(harness, order(harness, endpoint) if commanded else move(ally, 15))
    if commanded:
        assert (await harness.reload()).pending_declarations[actor]["destination"] == endpoint
    result = await harness.command("resolve_phase", {})
    state = await harness.reload()
    if not commanded:
        packets = result["packets"] + await harness.drain()
        assert any(p.get("opportunity_attack") and p["actor_id"] == foe for p in packets)
        return
    receipt = next(p for p in result["packets"] if p.get("action") == REPOSITION)
    assert receipt["resolved"] and receipt["effect_resolution"] == "engine"
    assert (receipt["actor_id"], receipt["target_ids"], receipt["name"]) == (actor, [ally], "Reposition")
    assert receipt["destination"] == state.spatial["positions"][ally] == endpoint
    assert state.spatial["positions"][actor] == before_state["spatial"]["positions"][actor]
    assert receipt["moved_ft"] == receipt["movement_spent_ft"] == 15
    assert receipt["deducted"] == {"focus": 0, "stamina": 2}
    assert not any(p.get("opportunity_attack") for p in state.held_actions)
    assert not state.open_window
    assert state.reactions_available[foe] == reaction_spend.unspent()
    packets = result["packets"] + await harness.drain()
    assert not any(p.get("opportunity_attack") for p in packets)
    _, players = await harness.snapshot()
    assert players[0]["stamina"]["current"] == before_players[0]["stamina"]["current"] - 2
    assert players[1]["hp"] == before_players[1]["hp"]


async def test_route_over_fifteen_feet_refuses_without_charge(marshal):
    harness = await battlefield(marshal)
    before = await harness.snapshot()
    assert "15 feet" in await declare(harness, order(harness, point(16)), error=True)
    assert await harness.snapshot() == before


def start_regenerating(recipient) -> int:
    recipient.hp_current -= 5
    recipient.conditions.append(
        dict(type="regenerating", source=recipient.id, duration=None, stacks=1, ticks_remaining=2)
    )
    return recipient.hp_current


async def test_later_move_is_cancelled_and_turn_start_still_runs(marshal):
    harness = await battlefield(marshal)
    _, ally, _ = harness.players
    state = await harness.reload()
    recipient = state.get_participant(ally)
    injured = start_regenerating(recipient)
    await harness.persist()
    await declare(harness, order(harness, point(15)), move(ally, 0, 12))
    packets = (await harness.command("resolve_phase", {}))["packets"]
    receipt = next(p for p in packets if p.get("action") == REPOSITION)
    assert receipt["cancelled_move"] == ally
    assert "cancel" in receipt["dm_cue"].lower()
    live = await harness.reload()
    assert ally not in live.pending_declarations
    assert live.spatial["positions"][ally] == point(15)
    assert participant(live, ally).hp_current == injured + 1
    _, players = await harness.snapshot()
    assert players[1]["hp"]["current"] == injured + 1
    packets += await harness.drain()
    effects = [e for p in packets for e in p.get("turn_start_effects", []) if e.get("target_id") == ally]
    assert [(e["name"], e["healed"]) for e in effects] == [("Regenerating", 1)]
    assert not any(p["actor_id"] == ally and "moved_ft" in p for p in packets)
    live = await harness.reload()
    assert ally not in live.pending_declarations and live.spatial["positions"][ally] == point(15)


@pytest.mark.parametrize(("tidewalker", "x", "allowed"), [(False, 10, False), (True, 15, True), (True, 16, False)])
async def test_water_cost_uses_the_recipients_tidewalker(marshal, tidewalker, x, allowed):
    harness = await battlefield(marshal, patrons=(None, "nythera") if tidewalker else ("nythera", None))
    actor, ally, _ = harness.players
    state = await harness.reload()
    assert participant(state, ally).tidewalker is tidewalker
    assert participant(state, actor).tidewalker is not tidewalker
    spatial_record(state)["movement_areas"] = {"crossing": area("water")}
    await harness.persist()
    before = await harness.snapshot()
    if not allowed:
        assert "15 feet" in await declare(harness, order(harness, point(x)), error=True)
        assert await harness.snapshot() == before
        return
    await declare(harness, order(harness, point(x)))
    [receipt] = [p for p in (await harness.command("resolve_phase", {}))["packets"] if p.get("action") == REPOSITION]
    assert receipt["movement_spent_ft"] == x
    assert receipt["destination"] == spatial_record(await harness.reload())["positions"][ally] == point(x)


@pytest.mark.parametrize("melody", ["condition", "round"])
async def test_choir_speed_exceptions_keep_the_fifteen_foot_cap(marshal, melody):
    harness = await battlefield(marshal)
    _, ally, _ = harness.players
    state = await harness.reload()
    recipient = participant(state, ally)
    if melody == "round":
        recipient.choir_movement_round = state.round_number
    else:
        recipient.conditions.append(dict(type="charmed", duration=1, source=harness.enemies[0], choir_melody=True))
    await harness.persist()
    before = await harness.snapshot()
    assert "15 feet" in await declare(harness, order(harness, point(16)), error=True)
    assert await harness.snapshot() == before
    await declare(harness, order(harness, point(15)), omit=(ally,))
    assert any(
        p.get("action") == REPOSITION and p["resolved"] for p in (await harness.command("resolve_phase", {}))["packets"]
    )
    assert spatial_record(await harness.reload())["positions"][ally] == point(15)


async def test_blocked_declaration_refuses_without_charge(marshal):
    harness = await battlefield(marshal)
    state = await harness.reload()
    combat_structures.add_wall(state, "route_wall", "Slate wall", point(10, -5), point(10, 5))
    await harness.persist()
    before = await harness.snapshot()
    assert "blocked by Slate wall" in await declare(harness, order(harness, point(15)), error=True)
    assert await harness.snapshot() == before


async def test_new_thornwall_fizzles_before_payment_or_cancellation(marshal):
    harness = await battlefield(marshal, patrons=("zhael", None, "thyra"))
    _, ally, wall_actor = harness.players
    lifecycle = _live_party(harness.sd, *harness.players)
    try:
        queued = move(ally, 0, -3)
        await declare(harness, order(harness, point(15)), queued)
        harness.model.commands.append(("activate", {"id": "thyra_thornwall", "destination": SEGMENT}))
        with harness.sd._bind_authenticated_actor(wall_actor, 1, lambda *_: None):
            await harness.session.run(user_input="Raise Thornwall.")
        activated = list(harness.model.receipts.values())[-1]
        assert activated.name == "activate" and not activated.is_error, activated.output
        wall = json.loads(activated.output)["wall"]["id"]
        _, before_players = await harness.snapshot()
        packets = (await harness.command("resolve_phase", {}))["packets"]
        [receipt] = [p for p in packets if p.get("action") == REPOSITION]
        assert not receipt["resolved"] and receipt["effect_resolution"] == "engine"
        assert "Thornwall" in receipt["reason"] and wall in receipt["reason"]
        assert receipt["deducted"] == {"focus": 0, "stamina": 0}
        assert "rally_grant" not in receipt and "cancelled_move" not in receipt
        live, players = await harness.snapshot()
        assert players[0] == before_players[0]
        assert live["spatial"]["positions"][ally] == queued["destination"]
        assert live["pending_declarations"][ally]["destination"] == queued["destination"]
        assert not live["encounter_facts"]["rally_pending"]
        assert all(p.get("action") != REPOSITION for p in await harness.drain())
        assert (await harness.snapshot())[1][0]["stamina"] == before_players[0]["stamina"]
    finally:
        await lifecycle.aclose()


@pytest.mark.parametrize("closer", [False, True])
async def test_earlier_move_changes_origin_and_is_not_cancelled(marshal, closer):
    harness = await battlefield(marshal)
    _, ally, _ = harness.players
    state = await harness.reload()
    participant(state, ally).initiative = 40
    await harness.persist()
    earlier_move = move(ally, 5) if closer else move(ally, 0, 4)
    await declare(harness, order(harness, point(15)), earlier_move)
    packets = (await harness.command("resolve_phase", {}))["packets"]
    [receipt] = [p for p in packets if p.get("action") == REPOSITION]
    assert "cancelled_move" not in receipt
    actual = spatial_record(await harness.reload())["positions"][ally]
    if closer:
        assert receipt["resolved"] and receipt["moved_ft"] == 10 and actual == point(15)
    else:
        assert not receipt["resolved"] and "15 feet" in receipt["reason"]
        assert actual == earlier_move["destination"]
        assert receipt["deducted"] == {"stamina": 0, "focus": 0}


async def test_later_attack_stays_queued(marshal):
    harness = await battlefield(marshal)
    _, ally, _ = harness.players
    foe = harness.enemies[0]
    state = await harness.reload()
    spatial_record(state)["positions"][foe] = point(17)
    await harness.persist()
    attack = dict(
        kind="attack", actor_id=ally, action="Longsword", target_id=foe, held_item_id="", rider="", reshape=[]
    )
    await declare(harness, order(harness, point(15)), attack)
    packets = (await harness.command("resolve_phase", {}))["packets"] + await harness.drain()
    [receipt] = [p for p in packets if p.get("action") == REPOSITION]
    assert "cancelled_move" not in receipt
    assert any(p["actor_id"] == ally and p.get("action") == "Longsword" and p.get("attack_resolved") for p in packets)


async def test_reposition_climbs_out_and_reports_the_actual_stopping_point(marshal):
    harness = await battlefield(marshal, encounter="hollow_architect")
    _, ally, _ = harness.players
    boss = harness.enemies[0]
    state = await harness.reload()
    spatial_record(state)["positions"][boss] = point(-10)
    await harness.persist()
    floor = dict(kind="open_floor", min=point(-1, -2), max=point(2, 2))
    with patch("check_resolution.dice_roll", return_value=_d20(1)):
        await declare(harness, dict(kind="defend", actor_id=boss, reshape=[floor]))
        await harness.drain()
    state = await harness.reload()
    assert ally in state.architect_encounter["pits"]
    combat_structures.add_wall(state, "pit_wall", "Slate wall", point(-3, -5), point(-3, 5))
    await harness.persist()
    before = await harness.snapshot()
    assert "15 feet" in await declare(harness, order(harness, point(20)), error=True)
    assert "blocked by Slate wall" in await declare(harness, order(harness, point(-5)), error=True)
    assert await harness.snapshot() == before
    await declare(harness, order(harness, point(5)))
    [receipt] = [p for p in (await harness.command("resolve_phase", {}))["packets"] if p.get("action") == REPOSITION]
    assert receipt["resolved"] and receipt["left_pit"] and receipt["moved_ft"] == 0
    assert receipt["movement_spent_ft"] == 15 and receipt["deducted"] == {"stamina": 2, "focus": 0}
    assert "climbing out" in receipt["reason"]
    live = await harness.reload()
    assert ally not in live.architect_encounter["pits"]
    assert receipt["destination"] == spatial_record(live)["positions"][ally] == point(0)


async def arrange_field(marshal):
    harness = await battlefield(marshal, encounter="hollow_veilrender_boss")
    actor, ally, bystander = harness.players
    state = await harness.reload()
    source = participant(state, harness.enemies[0])
    assert source.hollow is not None
    source.hollow["corruption_aura"] = 3
    spatial_record(state)["positions"][source.id] = point(15, 2)
    await set_favor(harness, "zhael", 40)
    await harness.pool.execute(
        """UPDATE players SET data=data || '{"patron_gifts":{"zhael_lucky":{"spent":true}}}'::jsonb
        WHERE player_id=$1""",
        actor,
    )
    await harness.persist()
    return harness, actor, ally, bystander


async def test_cancelled_move_keeps_a_corruption_save_across_reload(marshal):
    harness, actor, ally, bystander = await arrange_field(marshal)
    state = await harness.reload()
    injured = start_regenerating(participant(state, ally))
    await harness.persist()
    lifecycle = _live_party(harness.sd, actor, ally, bystander)
    try:
        await declare(harness, order(harness, point(15)), move(ally, 0, 12))
        with patch("check_resolution.dice_roll", return_value=_d20(20)) as dice:
            first = await harness.command("resolve_phase", {})
            offer = first["fate_offer"]
            assert (offer["roll_kind"], offer["roller_id"]) == ("save", ally)
            live = await harness.reload()
            assert live.ally_continuation["turns"][0] == [ally, None]
            assert ally not in live.pending_declarations
            assert participant(live, ally).hp_current == injured + 1
            resumed = await harness.command(
                "activate", {"id": "zhael_fates_thread", "offer_id": offer["offer_id"], "keep": "original"}
            )
            assert dice.call_count == 1
        packets = first["packets"] + resumed["packets"] + await harness.drain()
        effects = [e for p in packets for e in p.get("turn_start_effects", []) if e.get("actor_id") == ally]
        assert [(e["effect"], e["save_success"]) for e in effects] == [("corruption_field", True)]
        live = await harness.reload()
        assert ally not in live.pending_declarations and spatial_record(live)["positions"][ally] == point(15)
        assert participant(live, ally).hp_current == injured + 1
    finally:
        await lifecycle.aclose()


async def test_undeclared_ally_still_makes_the_corruption_save(marshal):
    harness, actor, ally, bystander = await arrange_field(marshal)
    state = await harness.reload()
    spatial_record(state)["positions"][harness.enemies[0]] = point(0, 2)
    await harness.persist()
    lifecycle = _live_party(harness.sd, actor, ally, bystander)
    try:
        await declare(harness, omit=(ally,))
        with patch("check_resolution.dice_roll", return_value=_d20(20)):
            first = await harness.command("resolve_phase", {})
            offer = first["fate_offer"]
            assert (offer["roll_kind"], offer["roller_id"]) == ("save", ally)
            resumed = await harness.command(
                "activate", {"id": "zhael_fates_thread", "offer_id": offer["offer_id"], "keep": "original"}
            )
        packets = first["packets"] + resumed["packets"] + await harness.drain()
        effects = [e for p in packets for e in p.get("turn_start_effects", []) if e.get("actor_id") == ally]
        assert [(e["effect"], e["save_success"]) for e in effects] == [("corruption_field", True)]
    finally:
        await lifecycle.aclose()


async def test_cancelled_move_keeps_the_choir_turn_start_save(marshal):
    harness = await battlefield(marshal, encounter="hollow_choir")
    _, ally, _ = harness.players
    await declare(harness, order(harness, point(15)), move(ally, 0, 12))
    with patch("check_resolution.dice_roll", return_value=_d20(20)):
        await harness.command("resolve_phase", {})
    live = await harness.reload()
    assert live.choir_encounter is not None
    assert live.choir_encounter["aura_receipts"][ally] == live.round_number
    assert ally not in live.pending_declarations


@pytest.mark.parametrize("destination", [{"x": 0, "y": 0}, {"x": float("inf"), "y": 0, "z": 0}])
async def test_destination_must_be_a_finite_point(marshal, destination):
    harness = await battlefield(marshal)
    before = await harness.snapshot()
    reason = await declare(harness, order(harness, destination), error=True)
    assert "destination" in reason and ("Field required" in reason or "finite" in reason)
    assert await harness.snapshot() == before
