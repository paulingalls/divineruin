from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from acceptance.defensive_reactions_harness import defense_fight
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_architect_fight import pos
from acceptance.test_guardian_intercept import SWORD, tool_receipt
from acceptance.test_opportunity_strike import participant

import db_queries
from combat_spatial import require_spatial
from durability import max_hits

RETALIATE = "guardian_retaliating_shield"
RIPOSTE = "skirmisher_riposte"
SIDESTEP = "skirmisher_sidestep"
SHIELD_ITEM = "thornveld_guardian_shield"
WEAPON = "dagger_balanced"


@asynccontextmanager
async def counter_fight(
    reaction: str,
    *,
    reach: int = 5,
    ranged: bool = False,
    gear: str | None = None,
    fate: bool = False,
    ally_archetype: str = "warden",
    enemy_type: str = "bandit",
) -> AsyncIterator[MawlingHarness]:
    archetype = "guardian" if reaction == RETALIATE else "skirmisher"
    async with defense_fight(archetype, enemy_type, ally_archetype=ally_archetype, gear=gear, fate=fate) as fight:
        reactor, ally = fight.players
        attacker, *lookouts = fight.enemies
        state = await fight.reload()
        require_spatial(state)["positions"].update(
            {attacker: pos(0), reactor: pos(5), ally: pos(0, 5), **{actor: pos(-15) for actor in lookouts}}
        )
        participant(state, reactor).attributes["strength"] = 16
        participant(state, reactor).enhancers.append("extra_attack")
        name = {"bandit": SWORD, "hollow_knight": "Corrupted Blade", "hollow_architect": "Construct Slam"}[enemy_type]
        sword = next(action for action in participant(state, attacker).action_pool if action["name"] == name)
        sword.update(type="ranged" if ranged else "melee", reach=reach)
        await fight.persist()
        yield fight


async def react(fight: MawlingHarness, ability: str, **selectors: object) -> str:
    receipt = await tool_receipt(fight, fight.players[0], "activate", {"id": ability, **selectors})
    assert not receipt.is_error, receipt.output
    return receipt.output


async def window_for(fight: MawlingHarness, ability: str, packets: list[dict]) -> dict:
    for _ in range(6):
        result = await fight.command("resolve_phase", {})
        packets.extend(result["packets"])
        window = result["next"]["waiting_on"]
        if window and ability in {reaction["id"] for reaction in window["reactions"]}:
            return window
    raise AssertionError(f"No window for {ability}")


async def shield_hits(actor: str) -> int:
    (item,) = [row for row in await db_queries.get_player_inventory(actor) if row["id"] == SHIELD_ITEM]
    return item["slot_info"].get("current_hits", max_hits(item["durability_tier"]))
