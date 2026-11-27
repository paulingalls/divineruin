import pytest
from _zhael_fate_fixtures import defend
from _zhael_unravel_fixtures import durable, favor, patch_player, unravel_fight
from acceptance.seeds import seed_known_spells
from combat._round_checkpoint_helpers import Fight

from patron_synergy import get_archetype_synergy

CLAUSE = "thyra_wild_shape"
EFFECT = "Wild Shape +5 temp HP"


async def shift(
    fight: Fight, archetype: str, patron: str, host: str, index: int, temporary: int
) -> tuple[dict, dict, dict]:
    pid = fight.ids[index]
    await favor(fight, fight.ids[0], host)
    await favor(fight, pid, patron)
    await patch_player(
        fight, pid, **{"class": archetype, "level": 5, "focus": {"current": 10, "max": 10}, "temp_hp": temporary}
    )
    action = "druid_wild_shape" if archetype == "druid" else "primal_wild_shape"
    if archetype != "druid":
        await seed_known_spells(fight.pool, pid, (action,))
    await fight.start()
    row = await fight.row()
    await fight.declare(
        {
            "kind": "ability",
            "actor_id": pid,
            "action": action,
            "targets": [],
            "argument_type": "grey_wolf",
            "reshape": [],
        },
        *(defend(p["id"]) for p in row["participants"] if p["id"] != pid),
    )
    result = await fight.call("resolve_phase")
    packet = next(p for p in result["packets"] if p["actor_id"] == pid)
    assert packet["resolved"] and packet["wild_shape"]["form_id"] == "grey_wolf"
    committed = await durable(fight)
    combatant = next(p for p in committed["combat"]["participants"] if p["id"] == pid)
    assert combatant["wild_shape"]["form_id"] == "grey_wolf"
    return packet, combatant, committed["players"][pid]["data"]


def assert_pool(combatant: dict, player: dict, expected: int) -> None:
    assert (combatant["temp_hp"], player["temp_hp"]) == (expected, expected)


async def wild_kinship_on_shift(world, archetype: str, index: int) -> None:
    async with unravel_fight(world.pool) as fight:
        packet, combatant, player = await shift(fight, archetype, "thyra", "kaelen" if index else "thyra", index, 0)
    assert_pool(combatant, player, 5)
    assert packet["wild_shape_synergy"] == {
        "id": CLAUSE,
        "name": "Wild Kinship",
        "effect": EFFECT,
        "temp_hp": 5,
        "granted": 5,
    }


@pytest.mark.parametrize("archetype", ["druid", "beastcaller", "warden"])
def test_catalog_pins_the_thyra_wild_shape_clause(archetype: str) -> None:
    row = get_archetype_synergy(archetype, "thyra")
    assert row is not None and row["type"] == "natural" and row["name"] == "Wild Kinship"
    assert [clause for clause in row["clauses"] if clause["effect"] == EFFECT] == [
        {"effect": EFFECT, "status": "active", "resolution": "engine", "implementation_id": CLAUSE}
    ]


@pytest.mark.parametrize(
    ("patron", "host", "index", "temporary"),
    [("thyra", "thyra", 0, 8), ("kaelen", "kaelen", 0, 0), ("kaelen", "thyra", 1, 0)],
)
async def test_wild_shape_keeps_the_larger_pool_and_uses_the_shifter_patron(
    dev_db_pool, patron: str, host: str, index: int, temporary: int
) -> None:
    async with unravel_fight(dev_db_pool) as fight:
        packet, combatant, player = await shift(fight, "druid", patron, host, index, temporary)
    assert_pool(combatant, player, temporary)
    if patron == "thyra":
        assert packet["wild_shape_synergy"]["granted"] == 0
        assert packet["wild_shape_synergy"]["temp_hp"] == 8
    else:
        assert "wild_shape_synergy" not in packet


SCENARIOS = {
    CLAUSE: (
        "patron_synergy:wild_shape_bonus",
        wild_kinship_on_shift,
        [("druid", 0), ("beastcaller", 0), ("warden", 0), ("druid", 1)],
    ),
}
