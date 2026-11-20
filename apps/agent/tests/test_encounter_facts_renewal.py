"""Death Feeds Renewal through registered phase tools and persisted checkpoints."""

from types import SimpleNamespace
from unittest.mock import patch

import asyncpg
import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import row
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import attack, defend
from acceptance._capstone_helpers import _enemy
from acceptance.seeds import seed_known_spells
from combat.test_handle_hp_zero import _hollowed
from test_encounter_facts_damage import GOBLIN, OTHER, Fight, dice, fight, goblin_strike
from test_encounter_facts_heal import wrap
from voice_condition_fixtures import participant, place_actors

import db_mutations
import db_queries
import still_encounter
from _gods_content import load_gods
from combat_participant import CombatParticipant
from combat_structures import add_wall
from creature_combat_loader import load_creature_enemy

CLAUSE = "mortaen_death_feeds_renewal"


async def focus(world: SimpleNamespace, index: int = 0) -> int:
    return (await row(world, index))["focus"]["current"]


def receipt(player: str, deceased: str, before: int, after: int) -> dict:
    return dict(
        clause_id=CLAUSE,
        player_id=player,
        deceased_id=deceased,
        focus_regained=after - before,
        focus_current=after,
        focus_max=10,
    )


def renewals(packets: list[dict]) -> list[dict]:
    return [r for packet in packets for r in packet.get("focus_renewals", [])]


async def setup_recipient(world: SimpleNamespace, archetype: str, start: int = 3) -> None:
    await configure(world, "mortaen", archetype, focus={"current": start, "max": 10})


async def catalog_scenario(world: SimpleNamespace, archetype: str) -> None:
    async with fight(world, "mortaen", archetype=archetype, goblin_hp=5) as f:
        await setup_recipient(world, archetype)
        packets = await f.round(attack(f.ally, GOBLIN))
        assert participant(f.session.combat_state, GOBLIN).hp_current == 0
        assert await focus(world) == 5
        assert renewals(packets) == [receipt(f.hero, GOBLIN, 3, 5)]
        authored = next(g for g in load_gods() if g["god_id"] == "mortaen")["layer_4_synergy_matrix"][archetype]
        assert (await f.call("query_info", kind="patron"))["synergy"] == authored
        assert (authored["type"], authored["name"]) == ("divine", "Death Feeds Renewal")
        assert [(c["status"], c["resolution"], c["implementation_id"]) for c in authored["clauses"]] == [
            ("active", "engine", CLAUSE)
        ]


SCENARIOS = {CLAUSE: ("encounter_facts:renew_on_death", catalog_scenario, [("druid",), ("warden",)])}


@pytest.mark.parametrize("start", [3, 9])
async def test_multiple_deaths_and_independent_pools(world: SimpleNamespace, start: int) -> None:
    async with fight(world, "mortaen", archetype="druid", goblin_hp=5) as f:
        await setup_recipient(world, "druid", start)
        await configure(world, "mortaen", "warden", index=1, focus={"current": 3, "max": 10})
        state = f.session.combat_state
        second = _enemy("goblin_three", 5)
        state.participants.append(second)
        state.initiative_order.append(second.id)
        place_actors(state)
        packets = await f.round(attack(f.ally, GOBLIN), attack(f.hero, second.id), faces=(15, 15))
        got = renewals(packets)
        assert len(got) == 4
        for index, original in enumerate((start, 3)):
            pid = world.ids[index]
            first, last = [r for r in got if r["player_id"] == pid]
            middle, final = min(10, original + 2), min(10, original + 4)
            assert first == receipt(pid, first["deceased_id"], original, middle)
            assert last == receipt(pid, last["deceased_id"], middle, final)
            assert {first["deceased_id"], last["deceased_id"]} == {GOBLIN, second.id}
            assert await focus(world, index) == final


@pytest.mark.parametrize("kill_first", [True, False])
async def test_focus_spell_and_renewal_share_the_latest_row(world: SimpleNamespace, kill_first: bool) -> None:
    async with fight(world, "mortaen", archetype="druid", goblin_hp=5) as f:
        await setup_recipient(world, "druid")
        spell = "primal_bark_skin"
        await seed_known_spells(world.pool, f.hero, (spell,))
        state = f.session.combat_state
        state.terrain = "forest"
        participant(state, f.ally).initiative = 25 if kill_first else 10
        state.initiative_order[:2] = [f.ally, f.hero] if kill_first else [f.hero, f.ally]
        packets = await f.round(
            attack(f.ally, GOBLIN),
            dict(actor_id=f.hero, kind="ability", action=spell, targets=[f.hero], argument_type=""),
        )
        actors = [p["actor_id"] for p in packets if "cast" in p or p.get("damage")]
        assert actors == state.initiative_order[:2]
        before = 3 if kill_first else 1
        assert renewals(packets) == [receipt(f.hero, GOBLIN, before, before + 2)]
        assert await focus(world) == 3


async def test_deescalation_spends_focus_after_renewal(world: SimpleNamespace) -> None:
    async with fight(world, "mortaen", archetype="druid", goblin_hp=5) as f:
        await setup_recipient(world, "druid", start=5)
        state = f.session.combat_state
        participant(state, f.ally).initiative = 25
        state.initiative_order[:2] = [f.ally, f.hero]
        packets = await f.round(
            attack(f.ally, GOBLIN),
            dict(actor_id=f.hero, kind="ability", action="de_escalate", targets=[], argument_type="reason"),
            faces=(15, 10),
        )
        assert renewals(packets) == [receipt(f.hero, GOBLIN, 5, 7)]
        assert any(p.get("action") == "de_escalate" and p["resolved"] for p in packets)
        assert await focus(world) == 4


@pytest.mark.parametrize("control", ["fallen", "thyra"])
async def test_only_standing_mortaen_players_renew(world: SimpleNamespace, control: str) -> None:
    async with fight(world, "mortaen", archetype="warden", goblin_hp=5) as f:
        await setup_recipient(world, "warden")
        await configure(
            world, "thyra" if control == "thyra" else "mortaen", "druid", index=1, focus={"current": 3, "max": 10}
        )
        ally = participant(f.session.combat_state, f.ally)
        ally.is_fallen = control == "fallen"
        if ally.is_fallen:
            ally.hp_current = 0
        packets = await f.round(attack(f.hero, GOBLIN))
        assert renewals(packets) == [receipt(f.hero, GOBLIN, 3, 5)]
        assert (await focus(world), await focus(world, 1)) == (5, 3)


@pytest.mark.parametrize("control", ["fortitude", "hollowed", "fall", "instant", "ward", "embrace"])
async def test_damage_observes_the_zero_hp_outcome(world: SimpleNamespace, control: str) -> None:
    async with fight(world, "mortaen", archetype="warden", ally_hp=4, goblin_hp=5) as f:
        if control != "embrace":
            await setup_recipient(world, "warden")
        state = f.session.combat_state
        ally = participant(state, f.ally)
        if control == "embrace":
            await configure(
                world,
                "orenthel",
                "warrior",
                divine_favor={"patron": "orenthel", "level": 75, "max": 100},
                patron_gifts={"orenthel_dawns_embrace": {"spent": False}},
            )
            await configure(
                world,
                "mortaen",
                "warden",
                index=1,
                focus={"current": 3, "max": 10},
                patron_gifts={"mortaen_death_ward": {"spent": True}},
            )
        if control in ("ward", "fall", "instant"):
            await configure(
                world,
                "mortaen",
                "druid",
                index=1,
                focus={"current": 3, "max": 10},
                patron_gifts={"mortaen_death_ward": {"spent": control != "ward"}},
            )
        if control == "hollowed":
            ally.conditions = _hollowed(2)
        if control in ("instant", "ward", "embrace"):
            ally.hp_current = ally.hp_max = 1
        if control == "fortitude":
            participant(state, GOBLIN).unholy_fortitude = {
                "save": "CON",
                "dc": 10,
                "increment": 5,
                "narration_cue": "It stands again.",
            }
        strike = attack(f.hero, GOBLIN) if control == "fortitude" else goblin_strike(OTHER, f.ally)
        packets = await f.round(strike, faces=(15, 20))
        state = f.session.combat_state
        ally = participant(state, f.ally)
        recipient = f.ally if control == "embrace" else f.hero
        index = int(control == "embrace")
        assert renewals(packets) == ([receipt(recipient, f.ally, 3, 5)] if control == "instant" else [])
        assert await focus(world, index) == (5 if control == "instant" else 3)
        if control == "instant":
            assert await focus(world, 1) == 3
        if control in ("ward", "embrace"):
            gift = "Death Ward" if control == "ward" else "Dawn's Embrace"
            assert any(p.get("gift_triggered") == gift for p in packets)
            assert ally.hp_current > 0 and state.encounter_facts["ally_downers"] == []
        elif control == "hollowed":
            assert ally.type == "temporary_hollowed" and ally.hp_current > 0
            ally.hp_current = 5
        elif control == "fortitude":
            assert participant(state, GOBLIN).hp_current == 1
        else:
            assert ally.is_fallen and ally.is_dead == (control == "instant")

        target = f.ally if control == "hollowed" else GOBLIN
        actor = f.ally if control == "ward" else f.hero
        packets = await f.round(attack(actor, target), faces=(15, 1))
        prior = 5 if control == "instant" else 3
        expected = [receipt(recipient, target, prior, prior + 2)]
        if control == "ward":
            expected.append(receipt(f.ally, target, 3, 5))
        assert sorted(renewals(packets), key=lambda r: r["player_id"]) == sorted(expected, key=lambda r: r["player_id"])
        assert await focus(world, index) == prior + 2


@pytest.mark.parametrize("start", [3, 7])
async def test_still_anchors_and_owner_each_renew(world: SimpleNamespace, start: int) -> None:
    async with fight(world, "mortaen", archetype="druid") as f:
        await setup_recipient(world, "druid", start)
        state = f.session.combat_state
        source = await load_creature_enemy("hollow_still", encounter_id=f.combat_id, enemy_id="still", role="named")
        owner = CombatParticipant(
            id="still",
            name=source["name"],
            type="enemy",
            initiative=5,
            hp_current=source["hp"],
            hp_max=source["hp"],
            ac=source["ac"],
            **{
                key: source[key]
                for key in ("creature_id", "action_pool", "tier", "hollow", "damage_affinities", "catalog_narration")
            },
        )
        state.participants.append(owner)
        state.initiative_order.append(owner.id)
        place_actors(state)
        still_encounter.initialize(state)
        record = state.still_encounter
        record["revealed_ids"] = list(record["anchor_ids"])
        for anchor_id in record["anchor_ids"][:-2]:
            anchor = participant(state, anchor_id)
            anchor.hp_current, anchor.is_fallen = 0, True
        for anchor_id in record["anchor_ids"][-2:]:
            participant(state, anchor_id).hp_current = 4
        owner.hp_current = 8
        await db_mutations.save_combat_state(f.combat_id, state.to_dict())
        await f.reload()
        previous = start
        for i, anchor_id in enumerate(record["anchor_ids"][-2:]):
            await f.call(
                "declare_phase",
                declarations=[
                    attack(f.ally, anchor_id),
                    defend(f.hero),
                    defend(GOBLIN),
                    defend(OTHER),
                ],
            )
            with dice(20):
                packets = (await f.call("resolve_phase"))["packets"]
            if not i:
                await wrap(f.call)
                await f.reload()
            current = min(10, previous + 2)
            expected = [receipt(f.hero, anchor_id, previous, current)]
            if i:
                expected.append(receipt(f.hero, owner.id, current, min(10, current + 2)))
                current = min(10, current + 2)
            assert renewals(packets) == expected
            assert await focus(world) == current
            previous = current
        saved = await f.reload()
        saved_owner = participant(saved, owner.id)
        assert saved_owner.is_fallen and saved_owner.hp_current == 0
        assert saved.still_encounter is not None
        assert saved.still_encounter["phase"] == "destroyed"


async def rollback(
    world: SimpleNamespace,
    f: Fight,
    command,
    target: str,
    terminal_field: str,
    terminal_value: int,
) -> None:
    before = (await f.reload()).to_dict()
    persist = db_mutations.save_combat_state

    async def abort(combat_id: str, data: dict, *, conn: asyncpg.Connection) -> None:
        await persist(combat_id, data, conn=conn)
        assert next(p for p in data["participants"] if p["id"] == target)[terminal_field] == terminal_value
        player = await db_queries.get_player(f.hero, conn=conn)
        assert player is not None
        assert player["focus"]["current"] == 5
        await conn.execute("SELECT 1 / 0")

    with patch.object(db_mutations, "save_combat_state", side_effect=abort), pytest.raises(asyncpg.DivisionByZeroError):
        await command()
    assert f.session.combat_state.to_dict() == before
    assert (await f.reload()).to_dict() == before
    assert await focus(world) == 3


async def test_phase_death_and_renewal_roll_back_together(world: SimpleNamespace) -> None:
    async with fight(world, "mortaen", archetype="druid", goblin_hp=5) as f:
        await setup_recipient(world, "druid")
        await f.declare(attack(f.ally, GOBLIN))

        async def resolve() -> dict:
            with dice(15):
                return await f.call("resolve_phase")

        await rollback(world, f, resolve, GOBLIN, "hp_current", 0)
        assert renewals((await resolve())["packets"]) == [receipt(f.hero, GOBLIN, 3, 5)]
        assert await focus(world) == 5


async def test_a_destroyed_wall_is_not_a_death(world: SimpleNamespace) -> None:
    async with fight(world, "mortaen", archetype="druid") as f:
        await setup_recipient(world, "druid")
        state = f.session.combat_state
        at = state.spatial["positions"][f.ally]
        wall = add_wall(
            state,
            "wall",
            "Slate Wall",
            {**at, "x": at["x"] + 3, "y": at["y"] - 5},
            {**at, "x": at["x"] + 3, "y": at["y"] + 5},
        )
        wall.hp_current = 1
        await db_mutations.save_combat_state(f.combat_id, state.to_dict())
        await f.reload()
        packets = await f.round(attack(f.ally, "wall"), faces=(20,))
        assert participant(f.session.combat_state, "wall").is_dead
        assert renewals(packets) == []
        assert await focus(world) == 3
