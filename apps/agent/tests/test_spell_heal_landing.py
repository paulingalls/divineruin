"""Real spell casts land HP through the registered exploration and combat commands."""

from types import SimpleNamespace
from unittest.mock import patch

import asyncpg
import pytest
from _spell_heal_fixtures import LOCATION, MASS, PRAYER, REGENERATE, TOUCH, WOUNDS
from _spell_heal_fixtures import spell_heal_walk as spell_heal_walk
from sample_fixtures import published_payloads

import db_mutations
import db_queries
import spells


def heal_die(total):
    return patch("dice.roll", return_value=SimpleNamespace(total=total))


def receipt(target_id, healed, current, *, rolled=5, modifier=3, maximum=20):
    return {
        "target_id": target_id,
        "rolled": rolled,
        "modifier": modifier,
        "healed": healed,
        "hp_current": current,
        "hp_max": maximum,
    }


@pytest.mark.parametrize("spell,combat", [(WOUNDS, True), (WOUNDS, False), (TOUCH, False), (REGENERATE, True)])
async def test_immediate_healing_persists_and_names_the_actual_restoration(healer, spell, combat):
    regenerate = spell == REGENERATE
    rolled, modifier, maximum = (35, 0, 50) if regenerate else (5, 3, 20)
    await healer.prepare(spell)
    ally = await healer.add_player(maximum=maximum)
    if combat:
        state = await healer.fight()
        state.get_participant(ally).initiative += 1
        await healer.declare(spell, [ally])
    with heal_die(rolled) as roll:
        if combat:
            first = await healer.command("resolve_phase", {})
            packet = next(p["cast"] for p in first["packets"] if p["actor_id"] == healer.player)
            healer.sd.combat_state = await healer.checkpoint()
            if first["beat"] != "declaration":
                assert not any(p.get("cast") for p in await healer.wrap())
        else:
            packet = await healer.cast(spell, targets=[ally])
    healed = rolled + modifier
    assert (await healer.read(ally))["hp"] == {"current": 3 + healed, "max": maximum}
    assert packet["healing_results"] == [
        receipt(ally, healed, 3 + healed, rolled=rolled, modifier=modifier, maximum=maximum)
    ]
    assert (await healer.focus()) == 30 - spells.get_spell(spell).focus_cost
    assert [call.args[0] for call in roll.call_args_list] == ["4d8+15" if regenerate else "1d8"]
    if combat:
        assert (await healer.checkpoint()).get_participant(ally).hp_current == 3 + healed


@pytest.mark.parametrize("combat", [False, True])
@pytest.mark.parametrize(
    "hp,kaelen,override,expected",
    [
        (19, False, 0, (1, 20, 20)),
        (20, False, 0, (0, 20, 20)),
        (19, True, 0, (6, 25, 25)),
        (14, False, -5, (1, 15, 15)),
    ],
)
async def test_healing_clamps_to_effective_max(
    healer, mock_combat_agent_factory, combat, hp, kaelen, override, expected
):
    await healer.prepare(WOUNDS)
    ally = await healer.add_player(hp=hp)
    if kaelen:
        await healer.patch_row(ally, divine_favor={"patron": "kaelen", "level": 40, "max": 100})
    if override:
        await healer.patch_row(ally, maxhp_override=override)
    if combat:
        if kaelen or override:
            await healer.enter(mock_combat_agent_factory)
        else:
            await healer.fight()
    with heal_die(5):
        packet = await healer.cast(WOUNDS, targets=[ally], combat=combat)
    healed, current, maximum = expected
    assert packet["healing_results"] == [receipt(ally, healed, current, maximum=maximum)]
    assert (await healer.read(ally))["hp"] == {"current": current, "max": 20}
    if combat:
        assert (await healer.checkpoint()).get_participant(ally).hp_current == current


async def test_nonpositive_heal_does_not_damage_the_recipient(healer):
    await healer.prepare(WOUNDS, wisdom=2)
    ally = await healer.add_player()
    with heal_die(1):
        packet = await healer.cast(WOUNDS, targets=[ally])
    assert packet["healing_results"] == [receipt(ally, 0, 3, rolled=1, modifier=-4)]
    assert (await healer.read(ally))["hp"]["current"] == 3


async def test_combat_mass_heal_reaches_allies_once_and_leaves_the_dead_and_enemies(healer):
    await healer.prepare(MASS)
    ally = await healer.add_player()
    dead = await healer.add_player(hp=0)
    state = await healer.fight(companion=True)
    fallen = state.get_participant(dead)
    fallen.is_fallen = True
    fallen.death_save_failures = 3
    await healer.save()
    with heal_die(8) as roll:
        packet = await healer.cast(MASS, combat=True)
    results = packet["healing_results"]
    assert {entry["target_id"]: entry for entry in results} == {
        pid: receipt(pid, 11, 14, rolled=8) for pid in (healer.player, ally, "companion")
    }
    assert len(results) == 3
    roll.assert_called_once_with("2d8")
    assert (await healer.focus()) == 30 - spells.get_spell(MASS).focus_cost
    saved = await healer.checkpoint()
    assert [saved.get_participant(pid).hp_current for pid in (healer.player, ally, "companion", dead, "foe")] == [
        14,
        14,
        14,
        0,
        100,
    ]
    for pid in (healer.player, ally, dead):
        assert (await healer.read(pid))["hp"]["current"] == saved.get_participant(pid).hp_current


async def test_exploration_mass_heal_uses_one_ordered_lock_and_the_persisted_location(healer):
    await healer.prepare(MASS)
    present = [await healer.add_player(), await healer.add_player()]
    remote = await healer.add_player(location="accord_guild_hall")
    outsider = await healer.add_player(party=False)
    healer.sd.location_id = "accord_guild_hall"
    lock_rows, write_hp = db_queries.get_players_for_update, db_mutations.update_player_hp

    async def verify_lock(pid, hp, *, conn):
        for locked_id in (healer.player, pid):
            with pytest.raises(asyncpg.LockNotAvailableError):
                await healer.pool.fetchval("SELECT 1 FROM players WHERE player_id=$1 FOR UPDATE NOWAIT", locked_id)
        await write_hp(pid, hp, conn=conn)

    with (
        heal_die(8) as roll,
        patch.object(db_queries, "get_players_for_update", wraps=lock_rows) as locked,
        patch.object(db_mutations, "update_player_hp", side_effect=verify_lock),
    ):
        packet = await healer.cast(MASS)
    assert [call.args[0] for call in locked.call_args_list] == [sorted([healer.player, *present, remote])]
    roll.assert_called_once_with("2d8")
    results = packet["healing_results"]
    assert len(results) == 3
    assert {r["target_id"]: r for r in results} == {
        pid: receipt(pid, 11, 14, rolled=8) for pid in (healer.player, *present)
    }
    for pid in (healer.player, *present, remote, outsider):
        assert (await healer.read(pid))["hp"]["current"] == (3 if pid in (remote, outsider) else 14)


@pytest.mark.parametrize("scenario", ["hostile", "hollow", "unknown", "prayer", "multiple", "mass", "dead", "failed"])
async def test_combat_refuses_ineligible_heals_at_declaration(healer, mock_combat_agent_factory, scenario):
    spell = {"prayer": PRAYER, "mass": MASS}.get(scenario, WOUNDS)
    await healer.prepare(spell)
    ally = await healer.add_player(hp=0 if scenario in ("dead", "failed") else 3)
    if scenario == "hollow":
        await healer.enter(mock_combat_agent_factory)
        hostile = next(p for p in healer.sd.combat_state.participants if not p.is_ally and p.hollow)
    else:
        state = await healer.fight()
        hostile = state.get_participant("foe")
    if scenario in ("dead", "failed"):
        fallen = healer.sd.combat_state.get_participant(ally)
        fallen.is_fallen = True
        fallen.is_dead = scenario == "dead"
        fallen.death_save_failures = 3 if scenario == "failed" else 0
        await healer.save()
    targets, message = {
        "hostile": ([hostile.id], "ally"),
        "hollow": ([hostile.id], "ally"),
        "unknown": (["missing"], "missing"),
        "prayer": ([ally], "outside combat"),
        "multiple": ([ally, healer.player], "one recipient"),
        "mass": ([ally], "automatically"),
        "dead": ([ally], "dead"),
        "failed": ([ally], "dead"),
    }[scenario]
    before = (await healer.checkpoint()).to_dict(), await healer.row(), await healer.read(ally)
    error = await healer.declare(spell, targets, error=True)
    assert message in error.lower()
    assert ((await healer.checkpoint()).to_dict(), await healer.row(), await healer.read(ally)) == before


@pytest.mark.parametrize("scenario", ["outsider", "missing", "remote", "too_many", "mass"])
async def test_exploration_refuses_invalid_selection_without_spending(healer, scenario):
    spell = {"too_many": PRAYER, "mass": MASS}.get(scenario, WOUNDS)
    await healer.prepare(spell)
    target = await healer.add_player(
        party=scenario != "outsider", location=LOCATION if scenario != "remote" else "accord_guild_hall"
    )
    if scenario == "missing":
        await healer.pool.execute("DELETE FROM players WHERE player_id=$1", target)
    args = {"id": spell, "target_id": target}
    if scenario == "too_many":
        args = {"id": spell, "target_ids": [target, *[await healer.add_player() for _ in range(6)]]}
    before = await healer.row()
    error = await healer.command("activate", args, error=True)
    assert {"too_many": "targets at most 6", "mass": "automatically"}.get(scenario, target) in error
    assert await healer.row() == before
    if scenario != "missing":
        assert (await healer.read(target))["hp"]["current"] == 3


@pytest.mark.parametrize("self_cast", [False, True])
async def test_prayer_heals_six_distinct_selected_allies_or_defaults_to_self(healer, self_cast):
    await healer.prepare(PRAYER)
    selected = [await healer.add_player() for _ in range(6)]
    with heal_die(8) as roll:
        packet = await healer.cast(PRAYER, targets=None if self_cast else [*selected, selected[0]])
    recipients = [healer.player] if self_cast else selected
    assert packet["healing_results"] == [receipt(pid, 11, 14, rolled=8) for pid in recipients]
    roll.assert_called_once_with("2d8")
    for pid in [healer.player, *selected]:
        assert (await healer.read(pid))["hp"]["current"] == (14 if pid in recipients else 3)


@pytest.mark.parametrize("companion", [False, True])
async def test_healing_revives_nonterminal_fallers_and_resets_death_saves(healer, companion):
    await healer.prepare(WOUNDS)
    target = "companion" if companion else await healer.add_player(hp=0)
    state = await healer.fight(companion=companion)
    faller = state.get_participant(target)
    faller.hp_current = 0
    faller.is_fallen = True
    faller.death_save_successes = 1
    faller.death_save_failures = 2
    await healer.save()
    with heal_die(5):
        packet = await healer.cast(WOUNDS, targets=[target], combat=True)
    assert packet["healing_results"] == [receipt(target, 8, 8)]
    revived = (await healer.checkpoint()).get_participant(target)
    assert (revived.hp_current, revived.is_fallen, revived.death_save_successes, revived.death_save_failures) == (
        8,
        False,
        0,
        0,
    )
    if not companion:
        assert (await healer.read(target))["hp"]["current"] == 8


async def test_combat_activate_refuses_a_heal_without_spending(healer):
    await healer.prepare(WOUNDS)
    ally = await healer.add_player()
    await healer.fight()
    before = await healer.row()
    error = await healer.command("activate", {"id": WOUNDS, "target_id": ally}, error=True)
    assert "declare_phase" in error
    assert await healer.row() == before
    assert (await healer.read(ally))["hp"]["current"] == 3


async def test_exploration_heal_pushes_each_healed_recipients_hp(healer):
    await healer.prepare(MASS)
    ally = await healer.add_player(hp=20)
    with heal_die(5):
        await healer.cast(MASS)
    calls = healer.sd.room.local_participant.publish_data.call_args_list
    pushes = [
        (c.kwargs.get("destination_identities"), p)
        for c, p in zip(calls, published_payloads(healer.sd.room), strict=True)
    ]
    assert [(to, p["current"], p["max"]) for to, p in pushes if p["type"] == "hp_changed"] == [
        ([healer.player], 11, 20)
    ]
    assert (await healer.read(ally))["hp"]["current"] == 20


async def test_a_zero_heal_leaves_a_dying_ally_dying(healer):
    await healer.prepare(WOUNDS, wisdom=2)
    target = await healer.add_player(hp=0)
    state = await healer.fight()
    faller = state.get_participant(target)
    faller.hp_current, faller.is_fallen = 0, True
    faller.death_save_successes, faller.death_save_failures = 1, 2
    await healer.save()
    with heal_die(1):
        packet = await healer.cast(WOUNDS, targets=[target], combat=True)
    assert packet["healing_results"] == [receipt(target, 0, 0, rolled=1, modifier=-4)]
    still = (await healer.checkpoint()).get_participant(target)
    assert (still.hp_current, still.is_fallen, still.death_save_successes, still.death_save_failures) == (0, True, 1, 2)
