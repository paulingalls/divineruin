"""Martial elective discovery and resolution through the registered tools."""

from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_architect_entomb import favor
from acceptance.test_martial_core_kit import enter, weapon_attack
from acceptance.test_still_anchors import fresh_session
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory

import ability_persistence
import combat_spatial
import conditions
import db_mutations
import db_mutations_conditions
import db_queries
import mentor_variant_progress
from activate_tools import activate
from combat_agent import CombatAgent
from declaration_payloads import AttackDecl

PRECISION = "warrior_precision_strike"
RECKLESS = "warrior_reckless_assault"
DIRTY_TRICK = "rogue_dirty_trick"


@pytest.fixture
async def electives(reset_db_pool: str):
    walk = MawlingHarness()
    try:
        await walk.prepare((10, 10), companion=None, tools=(activate,))
        walk.encounter_id = "bandit_ambush"
        yield walk
    finally:
        await walk.close()


async def equip(walk: MawlingHarness, ability: str) -> None:
    await ability_persistence.set_elective_equipped(walk.players[0], ability, True, conn=walk.pool)


async def enter_bandit_fight(walk: MawlingHarness) -> str:
    await enter(walk)
    state = await walk.reload()
    bandit = next(p for p in state.participants if p.creature_id == "bandit")
    bandit.hp_current = bandit.hp_max = 100
    positions = combat_spatial.require_spatial(state)["positions"]
    combat_spatial.place(state, bandit.id, positions[walk.players[0]])
    combat_spatial.place(state, walk.players[1], positions[walk.players[0]])
    await walk.persist()
    return bandit.id


async def stamina(actor: str) -> int:
    row = await db_queries.get_player(actor)
    assert row is not None
    return row["stamina"]["current"]


async def discovered(walk: MawlingHarness, ability: str) -> dict:
    result = await walk.command("query_info", {"kind": "abilities"})
    row = next(row for row in result["abilities"] if row["id"] == ability)
    assert row["combat"] is True
    return row


async def declare(walk: MawlingHarness, *declarations: dict) -> None:
    await walk.command("declare_phase", {"declarations": list(declarations)})


def defend(actor: str) -> dict:
    return {"kind": "defend", "actor_id": actor, "reshape": []}


def receipt(packets: list[dict], actor: str) -> dict:
    result = next((packet for packet in packets if packet["actor_id"] == actor), None)
    assert result is not None, packets
    return result


async def condition_types(walk: MawlingHarness, actor: str) -> set[str]:
    participant = (await walk.reload()).get_participant(actor)
    assert participant is not None
    return {condition["type"] for condition in participant.conditions}


async def bandit_attack(walk: MawlingHarness, foe: str, target: str) -> dict:
    bandit = (await walk.reload()).get_participant(foe)
    assert bandit is not None
    return {**weapon_attack(foe, target, ""), "action": bandit.action_pool[0]["name"]}


@pytest.mark.parametrize("variant", [None, "warrior_precision_strike_tidecaller"])
async def test_precision_sequence(electives: MawlingHarness, variant: str | None) -> None:
    actor, ally = electives.players
    await equip(electives, PRECISION)
    await db_mutations.set_player_flag(actor, "extra_attack", True)
    if variant:
        await mentor_variant_progress.record_unlocked(actor, variant, conn=electives.pool)
        await ability_persistence.set_active_variant(actor, PRECISION, variant, conn=electives.pool)
        await ability_persistence.update_player_resources(actor, stamina=2, conn=electives.pool)
    foe = await enter_bandit_fight(electives)
    row = await discovered(electives, PRECISION)
    assert row["declaration"] == {"kind": "attack", "rider": "precision_strike"}
    assert row.get("active_variant_id") == variant
    before = await stamina(actor)
    await declare(electives, weapon_attack(actor, foe, row["declaration"]["rider"]))
    with (
        patch("check_resolution.dice_roll", side_effect=map(_d20, [2, 18, 3, 17])) as rolls,
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        result = receipt(await electives.drain(), actor)
    assert rolls.call_count == 4
    assert [(swing["roll"], swing["hit"]) for swing in result["attacks"]] == [(18, True), (17, True)]
    assert await stamina(actor) == before - (2 if variant else 3)
    assert result.get("variant_id") == variant
    if variant:
        assert result["cultural_attribution"] == "Tidecallers technique"
    assert not await condition_types(electives, ally)
    await declare(electives, weapon_attack(actor, foe, ""))
    with patch("check_resolution.dice_roll", side_effect=map(_d20, [2, 3])):
        ordinary = receipt(await electives.drain(), actor)
    assert [swing["roll"] for swing in ordinary["attacks"]] == [2, 3]


async def test_precision_resumes_without_rolling_or_paying_twice(electives: MawlingHarness) -> None:
    actor = electives.players[0]
    await equip(electives, PRECISION)
    await db_mutations.set_player_flag(actor, "extra_attack", True)
    foe = await enter_bandit_fight(electives)
    await favor(electives)
    before = await stamina(actor)
    await declare(electives, weapon_attack(actor, foe, "precision_strike"))
    with (
        patch("check_resolution.dice_roll", side_effect=map(_d20, [2, 18, 3, 17])) as rolls,
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        first = await electives.command("resolve_phase", {})
        assert first["fate_offer"]["roller_id"] == actor
        assert rolls.call_count == 2
        assert await stamina(actor) == before - 3
        await fresh_session(electives, await electives.reload())
        second = await electives.command("resolve_phase", {})
        assert second["fate_offer"]["roller_id"] == actor
        assert rolls.call_count == 4
        finished = await electives.command("resolve_phase", {})
        result = receipt(finished["settled_fate"]["packets"], actor)
    assert [swing["roll"] for swing in result["attacks"]] == [18, 17]
    assert rolls.call_count == 4
    assert await stamina(actor) == before - 3


@pytest.mark.parametrize("stunned", [False, True], ids=["warrior_declares", "warrior_omitted"])
async def test_reckless_exposure_ends_at_next_declaration_beat(electives: MawlingHarness, stunned: bool) -> None:
    actor, ally = electives.players
    await equip(electives, RECKLESS)
    await db_mutations.set_player_flag(actor, "extra_attack", True)
    foe = await enter_bandit_fight(electives)
    row = await discovered(electives, RECKLESS)
    assert row["declaration"] == {"kind": "attack", "rider": "reckless_assault"}
    strike = await bandit_attack(electives, foe, actor)
    before = await stamina(actor)
    await declare(electives, weapon_attack(actor, foe, row["declaration"]["rider"]), strike)
    with (
        patch("check_resolution.dice_roll", side_effect=map(_d20, [2, 18, 3, 17, 4, 16])),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        first = await electives.command("resolve_phase", {})
        assert [swing["roll"] for swing in receipt(first["packets"], actor)["attacks"]] == [18, 17]
        state = await electives.reload()
        assert state.held_actions[0]["actor_id"] == foe
        await fresh_session(electives, state)
        assert receipt(await electives.drain(), foe)["roll"] == 16
    assert await stamina(actor) == before - 2
    assert "reckless_assault" in await condition_types(electives, actor)
    assert "reckless_assault" not in await condition_types(electives, ally)
    if stunned:
        state = await electives.reload()
        warrior = state.get_participant(actor)
        assert warrior is not None
        warrior.conditions = conditions.apply_condition(warrior.conditions, "stunned", source=foe, duration=1)
        await electives.persist()
        await declare(electives, strike)
    else:
        await declare(electives, weapon_attack(actor, foe, ""), strike)
    assert "reckless_assault" not in await condition_types(electives, actor)
    ordinary_faces = [4] if stunned else [2, 3, 4]
    with patch("check_resolution.dice_roll", side_effect=map(_d20, ordinary_faces)) as rolls:
        ordinary = await electives.drain()
    if not stunned:
        assert [swing["roll"] for swing in receipt(ordinary, actor)["attacks"]] == [2, 3]
    assert receipt(ordinary, foe)["roll"] == 4
    assert rolls.call_count == len(ordinary_faces)


async def prepare_rogue(walk: MawlingHarness) -> None:
    await walk.pool.execute(
        """UPDATE players SET data = data || '{"class":"rogue"}' WHERE player_id = $1""", walk.players[0]
    )
    await equip(walk, DIRTY_TRICK)


@pytest.mark.parametrize("attacks", [True, False], ids=["consumed_on_miss", "expires_at_wrap"])
async def test_dirty_trick(electives: MawlingHarness, attacks: bool) -> None:
    actor = electives.players[0]
    await prepare_rogue(electives)
    foe = await enter_bandit_fight(electives)
    row = await discovered(electives, DIRTY_TRICK)
    assert "declaration" not in row
    strike = await bandit_attack(electives, foe, actor)
    before = await stamina(actor)
    await declare(
        electives,
        {
            "kind": "ability",
            "actor_id": actor,
            "action": row["id"],
            "targets": [foe],
            "argument_type": "",
            "reshape": [],
        },
        strike if attacks else defend(foe),
    )
    with patch("check_resolution_save.roll_participant_save") as saves:
        first = await electives.command("resolve_phase", {})
    saves.assert_not_called()
    result = receipt(first["packets"], actor)
    bandit = (await electives.reload()).get_participant(foe)
    assert bandit is not None
    assert result["target"] == bandit.name and result["condition_inflicted"] == "shaken"
    assert "save_success" not in result and "condition_applied" not in result
    assert await stamina(actor) == before - 2
    assert "shaken" in await condition_types(electives, foe)
    if attacks:
        with patch("check_resolution.dice_roll", side_effect=map(_d20, [19, 2])) as rolls:
            second = await electives.command("resolve_phase", {})
        blow = receipt(second["packets"], foe)
        assert blow["roll"] == 2 and not blow["hit"] and rolls.call_count == 2
        assert "shaken" not in await condition_types(electives, foe)
    # Resolving the held attack can also wrap the round.
    if (await electives.reload()).beat != "declaration":
        await electives.drain()
    assert "shaken" not in await condition_types(electives, foe)
    await declare(electives, defend(actor), strike)
    with patch("check_resolution.dice_roll", side_effect=[_d20(2)]) as rolls:
        assert receipt(await electives.drain(), foe)["roll"] == 2
    rolls.assert_called_once()


async def test_dirty_trick_cannot_write_party_conditions(electives: MawlingHarness) -> None:
    await prepare_rogue(electives)
    before = [await db_queries.get_player(actor) for actor in electives.players]
    with patch.object(
        db_mutations_conditions,
        "save_many_player_conditions",
        wraps=db_mutations_conditions.save_many_player_conditions,
    ) as write:
        for target in ({}, {"target_id": electives.players[1]}):
            refusal = await electives.command("activate", {"id": DIRTY_TRICK, **target}, error=True)
            assert "needs a foe" in refusal
    write.assert_not_awaited()
    assert [await db_queries.get_player(actor) for actor in electives.players] == before


def test_combat_instructions_and_schema_publish_elective_riders() -> None:
    prompt = CombatAgent().instructions
    assert isinstance(prompt, str)
    schema = AttackDecl.model_json_schema()["properties"]["rider"]["description"]
    for rider in ("precision_strike", "reckless_assault"):
        assert rider in prompt and rider in schema
    assert DIRTY_TRICK in prompt
