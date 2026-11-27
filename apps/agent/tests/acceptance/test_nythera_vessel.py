"""Nythera vessel clauses through seeded discovery, combat entry, and settlement."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import attack, game_tools
from acceptance._enemy_opportunity_helpers import move
from acceptance.test_orenthel_guardian_ward import dev_db_pool as dev_db_pool
from acceptance.test_orenthel_guardian_ward import persist, place
from livekit.agents.llm import ToolError
from sample_fixtures import CONTENT_ROOT, FIXED_NOW
from test_aelora_gift import _live_party
from test_encounter_facts_damage import Fight, dice
from voice_condition_fixtures import participant
from weapon_fixtures import LONGSWORD, SHORTBOW

import db
import db_mutations
from combat_spatial import position, require_spatial
from creation_rules import build_character_data
from mode_tools import enter_mode

COAST = "sunward_tidal_shore"
DECK, BOARDING, ASHORE = "sunward_ship_deck", "sunward_dock_boarding", "shadeling_cluster"
DECK_CLAUSE, GUARD_CLAUSE = "nythera_deck_footing", "nythera_gangway_guard"
FATE = "zhael_fates_thread"
BASE_AC = 14
PROFILES = json.loads((CONTENT_ROOT / "packages/shared/fixtures/god_profiles.json").read_text())
TEMPLATES = {row["id"]: row for row in json.loads((CONTENT_ROOT / "content/encounter_templates.json").read_text())}


async def prepare(world: SimpleNamespace, archetype: str, patron: str, *, level: int) -> Fight:
    f = Fight(world)
    f.session.location_id = COAST
    for pid, job, god in ((f.hero, archetype, patron), (f.ally, "warrior", "thyra")):
        row = build_character_data(pid, "human", job, god, "", created_at=FIXED_NOW)
        row.update(
            level=level,
            ac=BASE_AC,
            hp={"current": 30, "max": 30},
            equipment={"main_hand": LONGSWORD, "ranged": SHORTBOW},
        )
        row["attributes"].update(strength=10, dexterity=10)
        await world.pool.execute("UPDATE players SET data=$2::jsonb WHERE player_id=$1", pid, json.dumps(row))
    return f


async def discovered(f: Fight) -> dict[str, dict]:
    rows = (await f.call("query_info", kind="creature"))["encounter_templates"]
    return {row["id"]: row for row in rows}


@asynccontextmanager
async def entered(
    world: SimpleNamespace,
    template: str,
    archetype: str,
    *,
    patron: str = "nythera",
    level: int = 2,
    discovery_floor: bool = False,
) -> AsyncIterator[Fight]:
    f = await prepare(world, archetype, patron, level=1 if discovery_floor else level)
    enter = game_tools(f.session, enter_mode)
    authored = TEMPLATES[template]
    with patch.object(db, "_cache_get", AsyncMock(return_value=None)), patch.object(db, "_cache_set", AsyncMock()):
        if discovery_floor:
            assert not {DECK, BOARDING} & (await discovered(f)).keys()
            await world.pool.execute(
                "UPDATE players SET data=jsonb_set(data, '{level}', '2') WHERE player_id=ANY($1)", world.ids
            )
        if template == ASHORE:
            f.session.location_id = "greyvale_wilderness_north"
        entries = await discovered(f)
        if discovery_floor:
            assert {DECK, BOARDING} <= entries.keys()
        with patch("combat_agent.create_combat_agent"):
            _, receipt = await enter("enter_mode", mode="combat", encounter_id=entries[template]["id"])
    f.combat_id = receipt["combat_id"]
    try:
        assert receipt["encounter_name"] == authored["name"]
        stored = await world.pool.fetchval("SELECT data FROM encounter_templates WHERE id=$1", template)
        assert json.loads(stored) == authored
        vessel = {DECK: "aboard_moving", BOARDING: "boarding", ASHORE: None}[template]
        if vessel:
            saved = json.loads(
                await world.pool.fetchval("SELECT data FROM combat_instances WHERE combat_id=$1", f.combat_id)
            )
            assert saved["vessel"] == vessel
            assert saved["round_checkpoints"][0]["combat"]["vessel"] == vessel
        assert (await f.reload()).vessel == vessel
        yield f
    finally:
        await db_mutations.delete_combat_state(f.combat_id)


async def enable_fate(world: SimpleNamespace) -> None:
    await configure(world, "zhael", "warrior", index=1, level=2, patron_gifts={"zhael_lucky": {"spent": True}})


async def keep_fate(f: Fight, offer: dict, roller: str, total: int) -> dict:
    assert (offer["roller_id"], offer["total"]) == (roller, total)
    assert f.ally in offer["eligible_followers"]
    lifecycle = f.session.multiplayer_owner.lifecycle
    with f.session._bind_authenticated_actor(f.ally, 1, lifecycle.require_authorized):
        return await f.call("activate", id=FATE, offer_id=offer["offer_id"], keep="original")


async def swing(f: Fight, bonus: int, *, weapon: str = LONGSWORD["name"], held: bool = False) -> None:
    enemy = next(p for p in f.session.combat_state.participants if p.type == "enemy")
    face = enemy.ac - 2
    strike = attack(f.hero, enemy.id, weapon)
    idle = {**move(enemy.id, 0), "destination": position(require_spatial(f.session.combat_state), enemy.id)}
    if held:
        await f.declare(strike, idle)
        with dice(face):
            offer = (await f.call("resolve_phase"))["fate_offer"]
            saved = await f.reload()
            assert saved.ally_continuation and participant(saved, enemy.id).hp_current == enemy.hp_current
            result = await keep_fate(f, offer, f.hero, face + 2)
        packets = result["packets"]
    else:
        packets = await f.round(strike, idle, faces=(face,))
    packet = next(p for p in packets if p["actor_id"] == f.hero)
    assert (packet["attack_total"], packet["hit"], packet["damage"]) == (face + 1 + bonus, bool(bonus), 5 * bonus)
    assert (packet["nythera_attack_bonus"], packet.get("nythera_attack_clause_id")) == (
        bonus,
        DECK_CLAUSE if bonus else None,
    )
    assert participant(await f.reload(), enemy.id).hp_current == enemy.hp_current - packet["damage"]


async def deck_footing(world: SimpleNamespace) -> None:
    async with entered(world, DECK, "warrior", discovery_floor=True) as f:
        await swing(f, 1)
        assert (await f.call("query_info", kind="patron"))["synergy"] == PROFILES["deck_footing"]


async def test_deck_footing(world: SimpleNamespace) -> None:
    await deck_footing(world)


@pytest.mark.parametrize(
    ("template", "patron", "weapon"),
    [
        (DECK, "nythera", SHORTBOW["name"]),
        (BOARDING, "nythera", LONGSWORD["name"]),
        (ASHORE, "nythera", LONGSWORD["name"]),
        (DECK, "thyra", LONGSWORD["name"]),
    ],
)
async def test_deck_controls(world: SimpleNamespace, template: str, patron: str, weapon: str) -> None:
    async with entered(world, template, "warrior", patron=patron) as f:
        await swing(f, 0, weapon=weapon)


async def test_deck_fate_keep_after_reload(world: SimpleNamespace) -> None:
    async with entered(world, DECK, "warrior") as f:
        lifecycle = _live_party(f.session, *world.ids)
        try:
            await enable_fate(world)
            await swing(f, 1, held=True)
        finally:
            await lifecycle.aclose()


def guard_receipt(packet: dict, bonus: int, total: int) -> None:
    hit = total >= BASE_AC + bonus
    assert (packet["attack_total"], packet["target_ac"], packet["hit"], packet["damage"]) == (
        total,
        BASE_AC + bonus,
        hit,
        5 if hit else 0,
    )
    assert (packet["nythera_ac_bonus"], packet.get("nythera_ac_clause_id")) == (bonus, GUARD_CLAUSE if bonus else None)


async def position_guard(f: Fight, distance: int) -> tuple[str, dict, int]:
    state = f.session.combat_state
    enemy = next(p for p in state.participants if p.type == "enemy")
    ally = participant(state, f.ally)
    assert ally.hp_current == ally.hp_max and not ally.is_fallen
    place(f, f.ally, distance)
    place(f, enemy.id, 5)
    await persist(f)
    action = (
        enemy.action_pool[0]
        if state.encounter_id == ASHORE
        else next(a for a in enemy.action_pool if a["name"] == "Tail Slap")
    )
    return enemy.id, attack(enemy.id, f.hero, action["name"]), BASE_AC - action["to_hit"]


async def incoming(f: Fight, bonus: int, distance: int) -> None:
    enemy, strike, face = await position_guard(f, distance)
    hp = participant(f.session.combat_state, f.hero).hp_current
    packets = await f.round(move(f.hero, 0), strike, faces=(face,))
    packet = next(p for p in packets if p["actor_id"] == enemy)
    guard_receipt(packet, bonus, BASE_AC)
    hero = participant(await f.reload(), f.hero)
    assert (hero.ac, hero.hp_current) == (BASE_AC, hp - packet["damage"])


async def gangway_guard(world: SimpleNamespace) -> None:
    async with entered(world, BOARDING, "guardian") as f:
        await incoming(f, 1, 5)
        assert (await f.call("query_info", kind="patron"))["synergy"] == PROFILES["gangway_guard"]


async def test_gangway_guard(world: SimpleNamespace) -> None:
    await gangway_guard(world)


@pytest.mark.parametrize(
    ("template", "patron", "distance"),
    [(BOARDING, "nythera", 6), (BOARDING, "thyra", 5), (DECK, "nythera", 5), (ASHORE, "nythera", 5)],
)
async def test_boarding_controls(world: SimpleNamespace, template: str, patron: str, distance: int) -> None:
    async with entered(world, template, "guardian", patron=patron) as f:
        await incoming(f, 0, distance)


async def test_hostile_fate_keep_after_reload(world: SimpleNamespace) -> None:
    async with entered(world, BOARDING, "guardian") as f:
        enemy, strike, face = await position_guard(f, 5)
        lifecycle = _live_party(f.session, *world.ids)
        try:
            await enable_fate(world)
            hp = participant(f.session.combat_state, f.hero).hp_current
            await f.declare(move(f.hero, 0), strike)
            await f.call("resolve_phase")
            with dice(face):
                offer = (await f.call("resolve_phase"))["fate_offer"]
                saved = await f.reload()
                assert saved.held_actions and participant(saved, f.hero).hp_current == hp
                place(f, f.ally, 6)
                await persist(f)
                result = await keep_fate(f, offer, enemy, BASE_AC)
            guard_receipt(next(p for p in result["packets"] if p["actor_id"] == enemy), 1, BASE_AC)
            assert participant(await f.reload(), f.hero).hp_current == hp
        finally:
            await lifecycle.aclose()


@pytest.mark.parametrize("bonus", [0, 1], ids=["move_near", "move_away"])
async def test_post_roll_replay_after_reload(world: SimpleNamespace, bonus: int) -> None:
    async with entered(world, BOARDING, "guardian", level=6) as f:
        enemy, strike, face = await position_guard(f, 6 - bonus)
        hp = participant(f.session.combat_state, f.hero).hp_current
        await f.declare(move(f.hero, 0), strike)
        with dice(face + 2):
            for _ in range(3):
                window = (await f.call("resolve_phase"))["next"]["waiting_on"]
                if window and window["stage"] == "post_roll":
                    break
            else:
                raise AssertionError("no post-roll reaction window")
        assert (window["actor_id"], window["target_id"]) == (enemy, f.hero)
        assert "guardian_retaliating_shield" in {r["id"] for r in window["reactions"]}
        saved = await f.reload()
        assert participant(saved, f.hero).hp_current == hp
        place(f, f.ally, 5 + bonus)
        await persist(f)
        with dice():
            result = await f.call("resolve_phase")
        packet = next(p for p in result["packets"] if p["actor_id"] == enemy)
        guard_receipt(packet, bonus, BASE_AC + 2)
        assert participant(await f.reload(), f.hero).hp_current == hp - packet["damage"]
        if result["beat"] != "declaration":
            assert (await f.call("resolve_phase"))["beat"] == "declaration"
        await incoming(f, 1 - bonus, 5 + bonus)


async def test_legacy_combat_row_without_vessel(world: SimpleNamespace) -> None:
    async with entered(world, DECK, "warrior") as f:
        await world.pool.execute("UPDATE combat_instances SET data=data - 'vessel' WHERE combat_id=$1", f.combat_id)
        assert (await f.reload()).vessel is None


async def test_entry_refuses_unknown_vessel(world: SimpleNamespace) -> None:
    f = await prepare(world, "warrior", "nythera", level=2)
    template_id = f"bad_vessel_{uuid4().hex}"
    invalid = dict(TEMPLATES[DECK], id=template_id, vessel="sailing")
    await world.pool.execute(
        "INSERT INTO encounter_templates (id, data) VALUES ($1, $2::jsonb)", template_id, json.dumps(invalid)
    )
    before = await world.pool.fetchval("SELECT count(*) FROM combat_instances")
    try:
        enter = game_tools(f.session, enter_mode)
        with pytest.raises(ToolError, match="vessel must be"):
            await enter("enter_mode", mode="combat", encounter_id=template_id)
        assert f.session.combat_state is None
        assert await world.pool.fetchval("SELECT count(*) FROM combat_instances") == before
    finally:
        if f.session.combat_state:
            await db_mutations.delete_combat_state(f.session.combat_state.combat_id)
        await world.pool.execute("DELETE FROM encounter_templates WHERE id=$1", template_id)


SCENARIOS = {
    DECK_CLAUSE: ("patron_synergy_combat:deck_footing_bonus", deck_footing, [()]),
    GUARD_CLAUSE: ("patron_synergy_combat:boarding_ally_defense", gangway_guard, [()]),
}
