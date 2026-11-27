from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import patch

from acceptance._capstone_helpers import _d20, _damage_die, _dice_events
from acceptance.defensive_reactions_harness import declare_attacks, defense_fight, player_row
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_bark_skin import keep_original
from acceptance.test_guardian_intercept import tool_receipt

from db_mutations_concentration import update_player_concentration

BARD = "bard_dissonant_whisper"
DOUBT = "whisper_implant_doubt"


@asynccontextmanager
async def ambush(
    ability: str, *, fate: bool = False, ally_archetype: str = "guardian", followup: bool = False
) -> AsyncIterator[MawlingHarness]:
    async with defense_fight(
        "bard" if ability == BARD else "whisper", fate=fate, ally_archetype=ally_archetype
    ) as fight:
        state = await fight.reload()
        reactor, ally = (state.get_participant(actor) for actor in fight.players)
        enemy = state.get_participant(fight.enemies[0])
        assert reactor and ally and enemy
        if fate:
            await update_player_concentration(reactor.id, None, conn=fight.pool)
            fight.sd.concentration.spell_id = None
        reactor.attributes.update(charisma=24, intelligence=18)
        enemy.attributes["wisdom"] = 6
        enemy.saving_throw_proficiencies = []
        ally.ac = 16
        await fight.persist()
        await declare_attacks(
            fight, reactor.id if ability == BARD else ally.id, *(fight.enemies if followup else [enemy.id])
        )
        yield fight


def dice(*faces: int):
    return patch("check_resolution.dice_roll", side_effect=[_d20(face) for face in faces])


def attack_damage(*totals: int):
    return patch("check_resolution_attack.dice_roll", side_effect=[_damage_die(total) for total in totals])


async def open_stage(fight: MawlingHarness, stage: str) -> dict:
    for _ in range(6):
        result = await fight.command("resolve_phase", {})
        if offer := result.get("fate_offer"):
            result = await keep_original(fight, offer)
        window = result["next"]["waiting_on"]
        if window and window["stage"] == stage:
            return window
    raise AssertionError(f"No {stage} reaction window")


async def focus(fight: MawlingHarness) -> int:
    return (await player_row(fight.players[0]))["focus"]["current"]


async def activate(fight: MawlingHarness, ability: str):
    return await tool_receipt(fight, fight.players[0], "activate", {"id": ability})


async def spend(fight: MawlingHarness, ability: str) -> int:
    before = await focus(fight)
    receipt = await activate(fight, ability)
    assert not receipt.is_error, receipt.output
    assert await focus(fight) == before - 2
    return before - 2


def attacks(fight: MawlingHarness) -> list[dict]:
    return [event for event in _dice_events(fight.sd.room) if event.get("roll_type") == "attack"]
