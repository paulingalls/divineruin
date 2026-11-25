"""Place-based healing through registered spell and item commands."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from _item_heal_fixtures import ItemHealWalk
from _spell_heal_fixtures import LOCATION, MASS, WOUNDS
from acceptance.seeds import seed_known_spells
from test_dawns_resilience import ORENTHEL, assert_hp
from test_heal_synergies import FULL_FOCUS, cast_as, healed, prepare, scenario

import ability_persistence
import db_mutations
from _gods_content import load_gods

VERDANT = "thyra_verdant_healing"
TRAVELER = "nythera_travelers_blessing"


def test_authored_cleric_place_healing() -> None:
    gods = {god["god_id"]: god for god in load_gods()}
    active = {"status": "active", "resolution": "engine"}
    for patron, name, effect, implementation in (
        ("thyra", "Verdant Healing", "Healing in natural terrain +1d4 extra HP", VERDANT),
        (
            "nythera",
            "Traveler's Blessing",
            "Healing a creature in an unexplored location restores 1 additional HP.",
            TRAVELER,
        ),
    ):
        assert gods[patron]["layer_4_synergy_matrix"]["cleric"] == {
            "type": "divine",
            "name": name,
            "clauses": [{**active, "effect": effect, "implementation_id": implementation}],
        }


def rolls(**totals: int):
    return patch("dice.roll", side_effect=lambda notation: SimpleNamespace(total=totals[notation]))


async def setup(walk: ItemHealWalk, patron: str, spell: str, *, hp: int = 20) -> None:
    await prepare(walk, walk.player, favor={**ORENTHEL, "patron": patron}, hp=hp)
    await seed_known_spells(walk.pool, walk.player, (spell,))


async def reset(walk: ItemHealWalk, combat: bool, target: str, *, terrain: str = "forest") -> None:
    await walk.patch(focus=FULL_FOCUS)
    await walk.patch_row(target, hp={"current": 3, "max": 20})
    if combat:
        await walk.fight()
        walk.fight_state.terrain = terrain
        await walk.save()


async def item_heal(walk: ItemHealWalk, combat: bool, target: str) -> None:
    await walk.put()
    with rolls(**{"2d4+2": 7}) as roll:
        if combat:
            await walk.declare_item(target=target)
            packet = await walk.resolve_item()
            await walk.wrap()
        else:
            packet = await walk.consume(target=target)
    roll.assert_called_once_with("2d4+2")
    assert packet["healing_results"] == [healed(target, 7, 10, bonus=0, rolled=7, modifier=0)]
    assert packet["remaining_quantity"] == await walk.quantity() == 1
    await assert_hp(walk, combat, {target: 10})
    assert await walk.focus() == 30


async def assert_single(
    walk: ItemHealWalk, combat: bool, target: str, bonus: int, implementation: str, layer2: dict | None = None
) -> None:
    packet = await cast_as(walk, combat, walk.player, target)
    assert packet["healing_results"] == [
        healed(target, 8 + bonus, 11 + bonus, bonus=bonus, implementation=implementation)
    ]
    assert packet["resonance_generated"] == (0 if layer2 else 1)
    assert packet.get("patron_resonance") == layer2
    await assert_hp(walk, combat, {target: 11 + bonus})
    assert await walk.focus() == 28


async def invalid_terrain(walk: ItemHealWalk, combat: bool, target: str) -> None:
    before = await walk.row(), await walk.read(target)
    if combat:
        await walk.declare(WOUNDS, [target])
        saved = (await walk.checkpoint()).to_dict()
    with (
        patch.object(
            ability_persistence, "update_player_resources", wraps=ability_persistence.update_player_resources
        ) as spend,
        patch.object(db_mutations, "update_player_hp", wraps=db_mutations.update_player_hp) as persist,
    ):
        error = (
            await walk.command("resolve_phase", {}, error=True)
            if combat
            else await walk.command("activate", {"id": WOUNDS, "target_id": target}, error=True)
        )
    assert "unresolvable terrain" in error
    spend.assert_not_awaited()
    persist.assert_not_awaited()
    assert (await walk.row(), await walk.read(target)) == before
    if combat:
        assert (await walk.checkpoint()).to_dict() == saved


async def thyra_single(walk: ItemHealWalk, combat: bool) -> None:
    await setup(walk, "thyra", WOUNDS)
    target = await walk.add_player()
    if combat:
        await walk.fight()
    layer2 = {"patron": "thyra", "applies_to": ["natural_ground"], "standard": 1, "generated": 0}
    with (
        patch(
            "db_content_queries.get_location_terrain", AsyncMock(return_value="city" if combat else "forest")
        ) as lookup,
        rolls(**{"1d8": 5, "1d4": 2}) as roll,
    ):
        await assert_single(walk, combat, target, 2, VERDANT, layer2)
    assert sorted(c.args[0] for c in roll.call_args_list) == ["1d4", "1d8"]
    if combat:
        lookup.assert_not_awaited()
    else:
        lookup.assert_awaited_once_with(LOCATION)

    await reset(walk, combat, target, terrain="city")
    with patch("db_content_queries.get_location_terrain", AsyncMock(return_value="city")), rolls(**{"1d8": 5}):
        await assert_single(walk, combat, target, 0, VERDANT)

    await reset(walk, combat, target, terrain="invalid")
    with patch("db_content_queries.get_location_terrain", AsyncMock(return_value="city" if combat else "invalid")):
        await invalid_terrain(walk, combat, target)

    await reset(walk, combat, target)
    with patch("db_content_queries.get_location_terrain", AsyncMock(return_value="forest")):
        await item_heal(walk, combat, target)


async def thyra_mass(walk: ItemHealWalk, combat: bool) -> None:
    await setup(walk, "thyra", MASS, hp=3)
    recipients = [walk.player, await walk.add_player(), await walk.add_player()]
    if combat:
        await walk.fight()
    with (
        patch("db_content_queries.get_location_terrain", AsyncMock(return_value="forest")),
        patch("world_season.current_season", AsyncMock(return_value="spring")),
        rolls(**{"2d8": 5, "1d4": 2}) as roll,
    ):
        if combat:
            await walk.declare(MASS, [])
            (packet,) = [p["cast"] for p in await walk.wrap() if "cast" in p]
        else:
            packet = await walk.cast(MASS)
    assert sorted(c.args[0] for c in roll.call_args_list) == ["1d4", "2d8"]
    hp = dict.fromkeys(recipients, 13) | {walk.player: 14}
    assert sorted(packet["healing_results"], key=lambda r: r["target_id"]) == [
        healed(target, hp[target] - 3, hp[target], bonus=2, implementation=VERDANT) for target in sorted(recipients)
    ]
    await assert_hp(walk, combat, hp)
    assert await walk.focus() == 24


async def map_progress(walk: ItemHealWalk, player: str, *, revisited: bool) -> None:
    await walk.pool.execute(
        "INSERT INTO player_map_progress (player_id, location_id, data) VALUES ($1,$2,$3::jsonb) "
        "ON CONFLICT (player_id, location_id) DO UPDATE SET data=excluded.data",
        player,
        LOCATION,
        json.dumps({"revisited": revisited}),
    )


async def nythera_single(walk: ItemHealWalk, combat: bool) -> None:
    await setup(walk, "nythera", WOUNDS)
    target = await walk.add_player()
    walk.stack.push_async_callback(
        walk.pool.execute,
        "DELETE FROM player_map_progress WHERE player_id IN ($1, $2) AND location_id=$3",
        walk.player,
        target,
        LOCATION,
    )
    await map_progress(walk, walk.player, revisited=False)
    await map_progress(walk, target, revisited=True)
    if combat:
        await walk.fight()
    layer2 = {"patron": "nythera", "applies_to": ["unvisited_location"], "standard": 1, "generated": 0}
    with rolls(**{"1d8": 5}):
        await assert_single(walk, combat, target, 1, TRAVELER, layer2)

        await reset(walk, combat, target)
        await map_progress(walk, walk.player, revisited=True)
        await map_progress(walk, target, revisited=False)
        await assert_single(walk, combat, target, 0, TRAVELER)

        await reset(walk, combat, target)
        await walk.pool.execute(
            "DELETE FROM player_map_progress WHERE player_id=$1 AND location_id=$2", walk.player, LOCATION
        )
        await assert_single(walk, combat, target, 0, TRAVELER)

    await reset(walk, combat, target)
    await map_progress(walk, walk.player, revisited=False)
    await item_heal(walk, combat, target)


SCENARIOS = {
    VERDANT: (
        "patron_synergy_heal:for_cast",
        scenario,
        [(check, combat) for check in (thyra_single, thyra_mass) for combat in (False, True)],
    ),
    TRAVELER: ("patron_synergy_heal:for_cast", scenario, [(nythera_single, combat) for combat in (False, True)]),
}
