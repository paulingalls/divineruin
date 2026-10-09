"""Catalog field damage through typed, roomless CombatAgent commands."""

import copy
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_mawling_multiattack import catalog

import db_queries
from creature_schema import validate_creature_stat_block

FIELD = {"trigger": "grappled_by_source", "damage": "1d6", "damage_type": "necrotic"}
INVALID = [
    None,
    [],
    1,
    True,
    {},
    {**FIELD, "extra": True},
    *[
        {**FIELD, key: value}
        for key, value in [
            ("trigger", "turn"),
            ("damage", "2d6"),
            ("damage_type", "fire"),
            ("damage", 6),
            ("trigger", True),
        ]
    ],
    *[{key: value for key, value in FIELD.items() if key != missing} for missing in FIELD],
]


@pytest.mark.parametrize("effect", INVALID)
def test_field_contract(effect):
    row = copy.deepcopy(next(r for r in catalog() if r["id"] == "hollow_mawling"))
    row["passives"][0]["turn_start_damage"] = effect
    assert validate_creature_stat_block(row)


@pytest.fixture
def mock_combat_agent_factory():
    return None


@pytest.fixture
async def maw(reset_db_pool, request):
    harness = MawlingHarness()
    try:
        options = getattr(request, "param", False)
        await harness.start(**(options if isinstance(options, dict) else {"companion": options}))
        yield harness
    finally:
        if hasattr(harness, "session"):
            await harness.close()


async def drain(maw):
    packets = []
    round_number = maw.sd.combat_state.round_number
    for _ in range(12):
        result = await maw.command("resolve_phase", {})
        packets.extend(result["packets"])
        state = await maw.reload()
        if state.round_number != round_number:
            return packets
    pytest.fail("round did not finish")


async def grapple(maw, target=None):
    target = target or maw.players[0]
    await maw.command(
        "declare_phase",
        {
            "declarations": [
                {
                    "kind": "attack",
                    "actor_id": maw.enemies[0],
                    "action": "Lunge",
                    "held_item_id": "",
                    "rider": "",
                    "target_id": target,
                },
                {"kind": "defend", "actor_id": maw.players[1]},
            ]
        },
    )
    packets = await drain(maw)
    assert not any(p.get("automatic") for p in packets)
    victim = maw.sd.combat_state.get_participant(target)
    assert any(c.get("source") == maw.enemies[0] and c["type"] == "grappled" for c in victim.conditions)
    return victim


@pytest.mark.parametrize("omitted", [False, True])
async def test_lunge_field_rounds(maw, omitted):
    with (
        patch("check_resolution.dice_roll", return_value=SimpleNamespace(total=15)),
        patch("check_resolution_attack.dice_roll", return_value=SimpleNamespace(total=4)),
        patch("combat_turn_start.dice_roll", return_value=SimpleNamespace(total=4)) as field,
    ):
        victim = await grapple(maw)
        hp = victim.hp_current
        for round_index in range(2):
            declarations = [{"kind": "defend", "actor_id": maw.players[1]}]
            if not omitted:
                declarations.append({"kind": "defend", "actor_id": victim.id})
            await maw.command("declare_phase", {"declarations": declarations})
            packets = await drain(maw)
            ticks = [p for p in packets if p.get("automatic")]
            field.assert_called_once_with("1d6")
            field.reset_mock()
            assert len(ticks) == 1 and ticks[0]["damage"] == 4
            assert ticks[0]["damage_type"] == "necrotic"
            assert ticks[0]["target_id"] == victim.id
            state = await maw.reload()
            assert state.get_participant(victim.id).hp_current == hp - 4 * (round_index + 1)
            row = await db_queries.get_player(victim.id)
            assert row is not None
            assert row["hp"]["current"] == hp - 4 * (round_index + 1)


async def persist(maw):
    import db_mutations

    state = maw.sd.combat_state
    await db_mutations.save_combat_state(state.combat_id, state.to_dict())
    for p in state.participants:
        if p.type == "player":
            await db_mutations.update_player_hp(p.id, p.hp_current)
    return await maw.reload()


@pytest.mark.parametrize("status", ["omitted", "stunned", "fallen"])
async def test_omitted_victim_continues(maw, status):
    with (
        patch("check_resolution.dice_roll", return_value=SimpleNamespace(total=15)),
        patch("check_resolution_attack.dice_roll", return_value=SimpleNamespace(total=4)),
        patch("combat_turn_start.dice_roll", return_value=SimpleNamespace(total=4)),
    ):
        victim = await grapple(maw)
        if status == "stunned":
            victim.conditions.append({"type": "stunned", "duration": 10})
        if status == "fallen":
            victim.hp_current = 0
            victim.is_fallen = True
            victim.death_save_successes = 3
        await persist(maw)
        hp = victim.hp_current
        for round_index in range(2):
            await maw.command("declare_phase", {"declarations": [{"kind": "defend", "actor_id": maw.players[1]}]})
            ticks = [p for p in await drain(maw) if p.get("automatic")]
            assert len(ticks) == 1
            victim = maw.sd.combat_state.get_participant(victim.id)
            if status == "fallen":
                assert victim.death_save_failures == round_index + 1
            else:
                assert victim.hp_current == hp - 4 * (round_index + 1)


@pytest.fixture
def field_dice():
    with (
        patch("check_resolution.dice_roll", return_value=SimpleNamespace(total=15)) as d20,
        patch("check_resolution_attack.dice_roll", return_value=SimpleNamespace(total=4)),
        patch("combat_turn_start.dice_roll", return_value=SimpleNamespace(total=4)) as field,
    ):
        yield field, d20


async def next_round(maw, declaration=None):
    await maw.command(
        "declare_phase",
        {"declarations": [{"kind": "defend", "actor_id": maw.players[1]}, *([declaration] if declaration else [])]},
    )
    return await drain(maw)


async def test_snapshot_field_and_deferred_inventory(maw):
    state = await maw.reload()
    for source in (p for p in state.participants if p.id in maw.enemies):
        assert source.turn_start_damage == FIELD
        names = {e["name"] for e in source.deferred_effects}
        assert "Dissolution Field" not in names
        assert {"Scatter", "Unsettling Silence", "Adaptive Learning"} <= names
    from creature_combat import translate_creature

    row = next(r for r in catalog() if r["id"] == "hollow_mawling")
    assert next(p for p in row["passives"] if p["name"] == "Dissolution Field")["turn_start_damage"] == FIELD
    assert validate_creature_stat_block(row) == []
    assert (
        translate_creature(row, encounter_id="minion", enemy_id="minion", role="minion")["turn_start_damage"] == FIELD
    )


@pytest.mark.parametrize(
    "case", ["source_dead", "source_fallen", "source_stunned", "other_owner", "victim_dead", "terminal", "sourceless"]
)
async def test_field_ineligible(maw, field_dice, case):
    victim = await grapple(maw)
    owner = maw.sd.combat_state.get_participant(maw.enemies[0])
    if case == "source_dead":
        owner.is_dead = True
    elif case == "source_fallen":
        owner.hp_current = 0
        owner.is_fallen = True
    elif case == "source_stunned":
        owner.conditions.append({"type": "stunned", "duration": 10})
    elif case == "other_owner":
        owner.creature_id = "hollow_shadeling"
    elif case == "victim_dead":
        victim.is_dead = True
    elif case == "terminal":
        victim.death_save_failures = 3
        victim.is_fallen = True
        victim.hp_current = 0
    else:
        next(c for c in victim.conditions if c["type"] == "grappled").pop("source")
    await persist(maw)
    hp = victim.hp_current
    assert not any(p.get("automatic") for p in await next_round(maw))
    assert field_dice[0].call_count == 0
    assert maw.sd.combat_state.get_participant(victim.id).hp_current == hp


async def test_missing_source_rolls_back(maw, field_dice):
    victim = await grapple(maw)
    next(c for c in victim.conditions if c["type"] == "grappled")["source"] = "absent"
    await persist(maw)
    await maw.command("declare_phase", {"declarations": [{"kind": "defend", "actor_id": maw.players[1]}]})
    before = await maw.snapshot()
    error = await maw.command("resolve_phase", {}, error=True)
    assert victim.id in error and "absent" in error
    assert await maw.snapshot() == before
    assert field_dice[0].call_count == 0


async def test_public_escape_stops_following_tick(maw, field_dice):
    victim = await grapple(maw)
    field_dice[1].return_value = SimpleNamespace(total=20)
    with patch("combat_maneuver.random.randint", return_value=20):
        packets = await next_round(maw, {"kind": "maneuver", "actor_id": victim.id, "target_id": maw.enemies[0]})
    assert sum(p.get("automatic", False) for p in packets) == 1
    victim = maw.sd.combat_state.get_participant(victim.id)
    assert not any(c["type"] == "grappled" for c in victim.conditions)
    assert not any(p.get("automatic") for p in await next_round(maw))


@pytest.mark.parametrize("maw", [{"gear": True}, {"gear": True, "companion": True}], indirect=True)
async def test_tick_fall_cancels_queued_action(maw, field_dice):
    target = maw.sd.companion.id if maw.sd.companion else maw.players[0]
    victim = await grapple(maw, target)
    victim.hp_current = 1
    await persist(maw)
    inventory_before = [await db_queries.get_player_inventory(pid) for pid in maw.players]
    position = copy.deepcopy(maw.sd.combat_state.spatial["positions"][target])
    attack_name = maw.sd.combat_state.get_participant(target).action_pool[0]["name"]
    packets = await next_round(
        maw,
        {
            "kind": "attack",
            "actor_id": target,
            "action": attack_name,
            "target_id": maw.enemies[1],
            "held_item_id": "",
            "rider": "",
        },
    )
    tick = next(p for p in packets if p.get("automatic"))
    action = next(p for p in packets if p.get("actor_id") == target)
    assert tick["target_fallen"] and not action["resolved"]
    assert packets.index(tick) < packets.index(action)
    assert not any(p.get("action") == attack_name and p.get("damage") for p in packets)
    victim = maw.sd.combat_state.get_participant(target)
    assert victim.hp_current == 0 and victim.is_fallen and not victim.is_dead
    assert maw.sd.combat_state.spatial["positions"][target] == position
    if maw.sd.companion:
        assert not maw.sd.companion.is_conscious
        assert maw.sd.companion.session_memories
        assert tick["durability"] == {}
        assert [await db_queries.get_player_inventory(pid) for pid in maw.players] == inventory_before
    else:
        row = await db_queries.get_player(target)
        assert row is not None and row["hp"]["current"] == 0


@pytest.mark.parametrize("maw", [True], indirect=True)
async def test_fallen_companion_clamps_and_keeps_ticking(maw, field_dice):
    target = maw.sd.companion.id
    victim = await grapple(maw, target)
    victim.hp_current = 0
    victim.is_fallen = True
    victim.death_save_successes = 3
    victim.death_save_failures = 2
    await persist(maw)
    for _ in range(2):
        packets = await next_round(maw)
        tick = next(p for p in packets if p.get("automatic"))
        assert tick["death_save_failures"] == 3
        victim = maw.sd.combat_state.get_participant(target)
        assert victim.death_save_failures == 2 and victim.death_save_successes == 3
        assert not victim.is_dead


async def test_fallen_player_dies_and_stops(maw, field_dice):
    victim = await grapple(maw)
    victim.hp_current = 0
    victim.is_fallen = True
    victim.death_save_successes = 3
    await persist(maw)
    for failures in range(1, 4):
        packets = await next_round(maw)
        tick = next(p for p in packets if p.get("automatic"))
        assert tick["death_save_failures"] == failures
    assert not any(p.get("automatic") for p in await next_round(maw))
    assert field_dice[0].call_count == 3


@pytest.mark.parametrize("holds", [False, True])
async def test_concentration_tick_and_queued_cast(maw, field_dice, holds):
    victim = await grapple(maw)
    # Persist a real concentrating spell and linked condition before the damage boundary.
    import db_mutations_concentration

    member = maw.sd.member_state(victim.id)
    member.concentration.spell_id = "divine_bless"
    await db_mutations_concentration.update_player_concentration(victim.id, "divine_bless")
    state = await maw.reload()
    state.get_participant(victim.id).conditions.append({"type": "blessed", "duration": None, "source": "divine_bless"})
    await persist(maw)
    field_dice[1].return_value = SimpleNamespace(total=20 if holds else 1)
    packets = await next_round(
        maw,
        {
            "kind": "ability",
            "actor_id": victim.id,
            "action": "arcane_bolt",
            "targets": [maw.enemies[1]],
            "argument_type": "",
        },
    )
    tick = next(p for p in packets if p.get("automatic"))
    assert tick["concentration_broken"] == (None if holds else "divine_bless")
    row = await db_queries.get_player(victim.id)
    assert row is not None
    assert row.get("concentration", {}).get("spell_id") == ("divine_bless" if holds else None)
    assert any(c["type"] == "blessed" for c in maw.sd.combat_state.get_participant(victim.id).conditions) is holds


async def test_stunned_declaration_refused_but_boundary_runs(maw, field_dice):
    victim = await grapple(maw)
    victim.conditions.append({"type": "stunned", "duration": 10})
    await persist(maw)
    before = await maw.snapshot()
    await maw.command("declare_phase", {"declarations": [{"kind": "defend", "actor_id": victim.id}]}, error=True)
    assert await maw.snapshot() == before
    assert sum(p.get("automatic", False) for p in await next_round(maw)) == 1


@pytest.mark.parametrize("maw", [True], indirect=True)
async def test_public_source_kill_releases_grapple(maw, field_dice):
    victim = await grapple(maw)
    owner = maw.sd.combat_state.get_participant(maw.enemies[0])
    owner.hp_current = 1
    victim.initiative = 100
    maw.sd.combat_state.get_participant(maw.sd.companion.id).initiative = -100
    await persist(maw)
    packets = await next_round(
        maw,
        {
            "kind": "attack",
            "actor_id": maw.sd.companion.id,
            "action": maw.sd.combat_state.get_participant(maw.sd.companion.id).action_pool[0]["name"],
            "target_id": owner.id,
            "held_item_id": "",
            "rider": "",
        },
    )
    assert sum(p.get("automatic", False) for p in packets) == 1
    state = await maw.reload()
    assert state.get_participant(owner.id).is_fallen, packets
    assert not any(c["type"] == "grappled" for c in state.get_participant(victim.id).conditions)
    assert not any(p.get("automatic") for p in await next_round(maw))


async def test_tick_fall_voids_declared_defend_bonus(maw, field_dice):
    victim = await grapple(maw)
    victim.hp_current = 1
    await persist(maw)
    await maw.command("declare_phase", {"declarations": [{"kind": "defend", "actor_id": victim.id}]})
    first = await maw.command("resolve_phase", {})
    assert any(p.get("automatic") for p in first["packets"])
    state = await maw.reload()
    assert state.get_participant(victim.id).is_fallen
    assert victim.id not in state.ac_modifiers  # held enemy strikes must not see the fallen defender's +AC


@pytest.mark.parametrize("maw", [{"gear": True}], indirect=True)
@pytest.mark.parametrize("kind", ["attack", "defend"])
async def test_hollowed_rise_cancels_living_ally_intent(maw, field_dice, kind):
    victim = await grapple(maw)
    victim.hp_current = 1
    victim.conditions.append({"type": "hollowed", "stage": 2, "duration": None})
    await persist(maw)
    target_id = maw.enemies[1]
    target_hp = maw.sd.combat_state.get_participant(target_id).hp_current
    declaration = {"kind": kind, "actor_id": victim.id}
    if kind == "attack":
        declaration.update(action="Shortsword", target_id=target_id, held_item_id="", rider="")
    await maw.command("declare_phase", {"declarations": [declaration]})
    first = await maw.command("resolve_phase", {})
    tick = next(p for p in first["packets"] if p.get("automatic"))
    assert tick["target_rose_hollowed"]
    action = next(p for p in first["packets"] if p.get("actor_id") == victim.id)
    assert not action["resolved"] and action["reason"] == "actor became hostile"
    state = await maw.reload()
    assert state.get_participant(victim.id).type == "temporary_hollowed"
    assert state.get_participant(target_id).hp_current == target_hp
    assert victim.id not in state.ac_modifiers
    await drain(maw)
    packets = await next_round(maw, {"kind": "defend", "actor_id": victim.id})
    assert any(p.get("actor_id") == victim.id and p["resolved"] for p in packets)
