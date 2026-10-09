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
async def maw(reset_db_pool):
    harness = MawlingHarness()
    try:
        await harness.start()
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


async def grapple(maw):
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
                    "target_id": maw.players[0],
                },
                {"kind": "defend", "actor_id": maw.players[1]},
            ]
        },
    )
    packets = await drain(maw)
    assert not any(p.get("automatic") for p in packets)
    victim = maw.sd.combat_state.get_participant(maw.players[0])
    assert any(c.get("source") == maw.enemies[0] and c["type"] == "grappled" for c in victim.conditions)
    return victim


@pytest.mark.parametrize("omitted", [False, True])
async def test_lunge_field_rounds(maw, omitted):
    with (
        patch("check_resolution.dice_roll", return_value=SimpleNamespace(total=15)),
        patch("check_resolution_attack.dice_roll", return_value=SimpleNamespace(total=4)),
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
            assert len(ticks) == 1 and ticks[0]["damage"] == 4
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
