"""Turn Undead/Hollow through exploration, combat and settlement tools."""

from itertools import chain, repeat
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from _patron_engine_fixtures import configure
from _zhael_fate_fixtures import defend, game_tools
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.turn_undead_harness import TURN, TurnFight
from acceptance.turn_undead_harness import fight as fight
from combat.test_synergy_crit_edges import fight as engine_fight
from voice_condition_fixtures import participant

import character_spells
import db_mutations
from combat_spatial import distance, require_spatial
from combat_turn import declare_phase, resolve_phase
from conditions import apply_condition
from query_tools import query_info

CLAUSE = "valdris_absolute_authority"
BONUS = {"id": CLAUSE, "name": "Absolute Authority", "bonus": 1}


async def absolute_authority_query(world: SimpleNamespace) -> None:
    call = game_tools(world.ctx.userdata, query_info)
    assert (await call("query_info", kind="patron"))["synergy"] == {
        "name": "Absolute Authority",
        "type": "divine",
        "clauses": [
            {
                "effect": "Turn Undead/Hollow DC +1. Absolute authority against unnatural things",
                "status": "active",
                "resolution": "engine",
                "implementation_id": CLAUSE,
            }
        ],
    }


async def absolute_authority(world: SimpleNamespace, archetype: str) -> None:
    host = world.ids[0]
    await character_spells.record_learned(host, TURN, "training", is_prepared=True, conn=world.pool)
    for patron, dc, success in (("thyra", 13, True), ("valdris", 14, False)):
        await configure(world, patron, archetype, level=4, focus={"current": 10}, resonance={"current": 0})
        world.ctx.userdata.resonance.current = 0
        async with engine_fight(world) as state:
            caster = participant(state, host)
            caster.level, caster.archetype_id, caster.attributes["wisdom"] = 4, archetype, 18
            foe = participant(state, "foe")
            foe.category, foe.attributes["wisdom"] = "undead", 10
            call = game_tools(world.ctx.userdata, declare_phase, resolve_phase)
            strike = {**defend(host), "kind": "ability", "action": TURN, "targets": [], "argument_type": ""}
            await call("declare_phase", declarations=[strike, defend("foe")])
            with patch("check_resolution.dice_roll", return_value=_d20(13)):
                result = await call("resolve_phase")
            cast = next(p["cast"] for p in result["packets"] if p.get("action") == TURN)
            (entry,) = cast["turn_undead"]
            save = entry["save"]
            assert (save["total"], save["dc"], save["success"], entry["outcome"]) == (
                13,
                dc,
                success,
                "unaffected" if success else "frightened",
            )
            assert cast["turn_undead_dc"] == dc
            if success:
                assert "turn_undead_dc_bonus" not in cast
            else:
                assert cast["turn_undead_dc_bonus"] == BONUS
    await absolute_authority_query(world)


SCENARIOS = {CLAUSE: ("patron_synergy_combat:turn_undead_dc_bonus", absolute_authority, [("cleric",), ("oracle",)])}


def frightened(fight: TurnFight, actor_id: str) -> dict | None:
    return next((c for c in fight.actor(actor_id).conditions if c["type"] == "frightened"), None)


@pytest.mark.parametrize("archetype", ["cleric", "oracle"])
async def test_valdris_turn_dc_after_reload(fight: TurnFight, archetype: str) -> None:
    await fight.enter({"maw": ("hollow_mawling", 12), "skeleton": ("undead", 4)}, archetype=archetype, patron="valdris")
    await fight.declare_turn(cast=True)
    declared = fight.sd.combat_state
    assert await fight.reload() is not declared
    with patch("check_resolution.dice_roll", return_value=_d20(13)):
        result = await fight.command("resolve_phase", {})
    cast = fight.cast(result["packets"])
    outcomes = {row["target_id"]: row for row in cast["turn_undead"]}
    assert set(outcomes) == {"maw", "skeleton"}
    for entry in outcomes.values():
        save = entry["save"]
        assert (save["total"], save["dc"], save["success"], entry["outcome"]) == (13, 14, False, "frightened")
    assert cast["turn_undead_dc"] == 14 and cast["turn_undead_dc_bonus"] == BONUS
    await fight.reload()
    for actor_id in outcomes:
        condition = frightened(fight, actor_id)
        assert condition is not None and condition["source"] == fight.caster


async def test_turn_saves_and_flight(fight: TurnFight) -> None:
    await fight.enter({"maw": ("hollow_mawling", 30), "skeleton": ("undead", 4)})
    before = await fight.player()
    multi = fight.composite([fight.caster, fight.caster])
    with patch("check_resolution.dice_roll", return_value=_d20(2)):
        packets = await fight.phase(multi, fight.attack("skeleton"), cast=True)
    cast = fight.cast(packets)
    dc = cast["turn_undead_dc"]
    assert dc == 13
    outcomes = {row["target_id"]: row for row in cast["turn_undead"]}
    for actor_id in ("maw", "skeleton"):
        entry = outcomes[actor_id]
        assert entry["save"]["roll"] == 2 and entry["save"]["total"] < dc
        assert entry["save"]["dc"] == dc and entry["save"]["success"] is False
        assert entry["outcome"] == "frightened" and "declare" in entry["reason"].lower()
        condition = frightened(fight, actor_id)
        assert condition is not None and condition["source"] == condition["originating_participant_id"] == fight.caster
        assert condition["duration"] == 9
    assert (await fight.player())["focus"]["current"] == before["focus"]["current"] - 3

    assert {p["actor_id"] for p in packets if p.get("fled")} == {"maw", "skeleton"}
    starts = dict(require_spatial(await fight.reload())["positions"])
    with patch("check_resolution.dice_roll", return_value=_d20(18)):
        packets = await fight.phase(multi, fight.attack("skeleton"))
    ends = require_spatial(await fight.reload())["positions"]
    for actor_id in ("maw", "skeleton"):
        receipts = [p for p in packets if p["actor_id"] == actor_id]
        (fled,) = [p for p in receipts if p.get("fled")]
        assert fled["source_id"] == fight.caster and fled["origin"] == starts[actor_id]
        assert fled["destination"] == ends[actor_id] and fled["moved_ft"] > 0
        assert distance(ends[actor_id], ends[fight.caster]) > distance(starts[actor_id], starts[fight.caster])
        assert all("hit" not in p and "damage" not in p for p in receipts)
        assert frightened(fight, actor_id) is None
    assert (await fight.player())["hp"] == before["hp"]

    with (
        patch("check_resolution.dice_roll", return_value=_d20(18)),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        packets = await fight.phase(fight.attack("skeleton", ranged=True))
    assert any(p["actor_id"] == "skeleton" and p.get("hit") and p["damage"] > 0 for p in packets)
    assert (await fight.player())["hp"]["current"] < before["hp"]["current"]


@pytest.mark.parametrize("immune", [False, True])
async def test_destruction_and_victory(fight: TurnFight, immune: bool) -> None:
    enemies = {"skeleton": ("undead", 4)}
    if immune:
        enemies["knight"] = ("hollow_knight", 5)
    await fight.enter(enemies, level=5)
    target = fight.actor("skeleton")
    target.hp_current = 24
    if immune:
        target.conditions = apply_condition(target.conditions, "temporary_hollowed")
        target.damage_affinities["immune"] = ["radiant"]
        knight = fight.actor("knight")
        knight.hp_current = 12
        assert knight.unholy_fortitude is not None and knight.hollow is not None
    state = await fight.persist()
    before = await fight.player()
    await fight.declare_turn(*(fight.attack(enemy) for enemy in enemies), cast=True)
    rolls = chain(repeat(_d20(2), len(enemies)), repeat(_d20(18)))
    with patch("check_resolution.dice_roll", side_effect=rolls):
        result = await fight.command("resolve_phase", {})
        cast = fight.cast(result["packets"])
        await fight.reload()
        defeated = [fight.actor(enemy) for enemy in enemies]
        outcomes = {row["target_id"]: row for row in cast["turn_undead"]}
        for target in defeated:
            outcome = outcomes[target.id]
            assert outcome["save"]["success"] is False and outcome["outcome"] == "destroyed"
            assert target.hp_current == 0 and target.is_fallen and target.is_dead
            assert frightened(fight, target.id) is None and "unholy_fortitude" not in outcome
        if immune:
            knight = fight.actor("knight")
            assert knight.hollow_death_resolved and knight.hollow is not None
            assert (await fight.player())["resonance"]["current"] == (
                cast["resonance_generated"] + knight.hollow["resonance_on_death"]
            )
        await fight.drain()
    victory = fight.last_result
    assert victory["outcome"] == "victory"
    assert sorted(victory["defeated_enemies"]) == sorted(target.name for target in defeated)
    assert victory["xp_granted"] == sum(target.xp_value for target in defeated)
    assert (await fight.player())["xp"] - before.get("xp", 0) == victory["xp_granted"]
    assert (await fight.player())["hp"] == before["hp"]
    assert await db_mutations.load_combat_state(state.combat_id) is None


async def test_exploration_refuses_without_spending(fight: TurnFight) -> None:
    await fight.ready(4)
    before = await fight.player()
    events = fight.events()
    refusal = await fight.command("activate", {"id": TURN}, error=True)
    assert "needs combat targets" in refusal.lower()
    assert await fight.player() == before
    assert fight.events() == events


async def test_second_recipient_resumes_through_fate(fight: TurnFight) -> None:
    from acceptance.test_architect_entomb import favor

    await fight.enter({"first": ("undead", 4), "second": ("undead", 6)})
    await favor(fight)
    before = await fight.player()
    await fight.declare_turn(cast=True)
    with patch("check_resolution.dice_roll", side_effect=[_d20(2), _d20(3), _d20(20), _d20(18)]):
        first = (await fight.command("resolve_phase", {}))["fate_offer"]
        assert first["roller_id"] == "first"
        next_result = await fight.command(
            "activate", {"id": "zhael_fates_thread", "offer_id": first["offer_id"], "keep": "original"}
        )
        second = next_result["fate_offer"]
        assert second["roller_id"] == "second" and second["die"] == 3
        await fight.reload()
        previous = frightened(fight, "first")
        assert previous is not None and frightened(fight, "second") is None
        args = {"id": "zhael_fates_thread", "offer_id": second["offer_id"]}
        shown = await fight.command("activate", args)
        assert shown["reroll"]["die"] == 20
        resolved = await fight.command("activate", {**args, "keep": "reroll"})
        outcomes = fight.cast(resolved["packets"])["turn_undead"]
        assert [(row["target_id"], row["save"]["roll"], row["outcome"]) for row in outcomes] == [
            ("first", 2, "frightened"),
            ("second", 20, "unaffected"),
        ]
        await fight.reload()
        assert frightened(fight, "first") == previous and frightened(fight, "second") is None
        assert (await fight.player())["focus"]["current"] == before["focus"]["current"] - 3
