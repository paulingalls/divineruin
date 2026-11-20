"""Appointed Mercy through registered combat tools and persisted checkpoints."""

from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import AsyncMock, patch

import asyncpg
import pytest
from _item_heal_fixtures import ItemHealWalk, heal_roll
from _item_heal_fixtures import item_heal_walk as item_heal_walk
from _spell_heal_fixtures import MASS, WOUNDS
from _zhael_fate_fixtures import attack, defend, game_tools
from acceptance._capstone_helpers import _d20
from acceptance.seeds import seed_known_spells
from test_dawns_resilience import assert_hp
from test_encounter_facts_damage import dice
from test_heal_synergies import assert_revived, healed, prepare, scenario

import db_mutations
import spells
from _gods_content import load_gods
from combat_death_save import request_death_save
from combat_turn import declare_phase, resolve_phase

MERCY = "zhael_appointed_mercy"
Call = Callable[..., Awaitable[Any]]


async def wrap(call: Call) -> dict:
    for _ in range(8):
        result = await call("resolve_phase")
        if result["beat"] == "declaration":
            return result
    raise AssertionError("Combat did not reach the next declaration beat")


async def fall(
    walk: ItemHealWalk, *, patron: str = "zhael", spell: str = WOUNDS, extra: bool = False
) -> tuple[Call, str, str | None]:
    await prepare(walk, walk.player, favor={"patron": patron, "level": 0, "max": 100}, hp=20)
    await walk.patch(patron_gifts={gift: {"spent": True} for gift in ("zhael_fates_thread", "zhael_lucky")})
    await seed_known_spells(walk.pool, walk.player, (spell,))
    ally = await walk.add_player()
    other = await walk.add_player() if extra else None
    state = await walk.fight()
    call = game_tools(walk.sd, declare_phase, resolve_phase, request_death_save)
    strike = {**attack("foe", ally), "action": "Scimitar"}
    await call("declare_phase", declarations=[strike, *(defend(pid) for pid in state.initiative_order if pid != "foe")])
    with dice(15):
        result = await wrap(call)
    assert result["death_saves_due"] == [ally]
    fallen = walk.fight_state.get_participant(ally)
    assert fallen is not None and fallen.is_fallen and fallen.hp_current == 0
    return call, ally, other


async def save(call: Call, ally: str, face: int) -> dict:
    with patch("combat_resolution.dice_roll", return_value=_d20(face)):
        return await call("request_death_save", player_id=ally)


async def reload(walk: ItemHealWalk) -> dict[str, int]:
    saved = await walk.checkpoint()
    walk.sd.combat_state = saved
    return saved.encounter_facts["death_save_success_round"]


async def cast(walk: ItemHealWalk, spell: str, targets: list[str]) -> list[dict]:
    await walk.declare(spell, targets)
    with heal_roll(5) as roll:
        result = await walk.command("resolve_phase", {})
    roll.assert_called_once_with("2d8" if spell == MASS else "1d8")
    assert await walk.focus() == 30 - spells.get_spell(spell).focus_cost
    return next(p["cast"]["healing_results"] for p in result["packets"] if p["actor_id"] == walk.player)


async def appointed_mercy(walk: ItemHealWalk, face: int) -> None:
    call, ally, _ = await fall(walk)
    round_number = walk.fight_state.round_number
    result = await save(call, ally, face)
    assert result["success"] and result["critical_success"] == (face == 20)
    assert await reload(walk) == {ally: round_number}
    before = int(face == 20)
    await assert_hp(walk, True, {ally: before})
    assert await cast(walk, WOUNDS, [ally]) == [healed(ally, 9, before + 9, bonus=1, implementation=MERCY)]
    await assert_hp(walk, True, {ally: before + 9})
    await assert_revived(walk, ally)
    assert_authored_appointed_mercy()


SCENARIOS = {MERCY: ("patron_synergy_heal:for_cast", scenario, [(appointed_mercy, 15), (appointed_mercy, 20)])}


def assert_authored_appointed_mercy() -> None:
    zhael = next(god for god in load_gods() if god["god_id"] == "zhael")
    assert zhael["layer_4_synergy_matrix"]["cleric"] == {
        "type": "divine",
        "name": "Appointed Mercy",
        "clauses": [
            {
                "effect": "Healing an ally who succeeded on a death saving throw this round restores 1 additional HP.",
                "status": "active",
                "resolution": "engine",
                "implementation_id": MERCY,
            },
        ],
    }


@pytest.mark.parametrize("control", ["failed_save", "earlier_round", "other_patron"])
async def test_heal_wounds_eligibility(walk: ItemHealWalk, control: str) -> None:
    call, ally, _ = await fall(walk, patron="valdris" if control == "other_patron" else "zhael")
    round_number = walk.fight_state.round_number
    succeeded = control != "failed_save"
    result = await save(call, ally, 15 if succeeded else 5)
    assert result["success"] == succeeded
    if control == "earlier_round":
        await call("declare_phase", declarations=[defend(walk.player), defend("foe")])
        await wrap(call)
        assert walk.fight_state.round_number == round_number + 1
    assert await reload(walk) == ({ally: round_number} if succeeded else {})
    assert await cast(walk, WOUNDS, [ally]) == [healed(ally, 8, 8, bonus=0)]
    await assert_hp(walk, True, {ally: 8})


async def test_mass_heal_selects_only_the_saver(walk: ItemHealWalk) -> None:
    call, ally, other = await fall(walk, spell=MASS, extra=True)
    assert other is not None
    assert (await save(call, ally, 15))["success"]
    await reload(walk)
    results = await cast(walk, MASS, [])
    injured = {r["target_id"]: r for r in results if r["target_id"] != walk.player}
    assert injured == {ally: healed(ally, 9, 9, bonus=1, implementation=MERCY), other: healed(other, 8, 11, bonus=0)}
    await assert_hp(walk, True, {ally: 9, other: 11, walk.player: 20})


async def test_healing_item_has_no_appointed_mercy_bonus(walk: ItemHealWalk) -> None:
    call, ally, _ = await fall(walk)
    assert (await save(call, ally, 15))["success"]
    await reload(walk)
    await walk.put()
    await walk.declare_item(target=ally)
    with heal_roll(7):
        packet = await walk.resolve_item()
    assert packet["healing_results"] == [healed(ally, 7, 7, rolled=7, modifier=0, bonus=0)]
    assert packet["remaining_quantity"] == await walk.quantity() == 1
    assert await walk.focus() == 30
    await assert_hp(walk, True, {ally: 7})


@pytest.mark.parametrize("face", [15, 20])
async def test_death_save_rollback(walk: ItemHealWalk, face: int) -> None:
    call, ally, _ = await fall(walk)
    before = (await walk.checkpoint()).to_dict()
    player_before = await walk.read(ally)
    persist = db_mutations.save_combat_state

    async def abort(combat_id: str, data: dict, *, conn: asyncpg.Connection) -> None:
        assert data["encounter_facts"].get("death_save_success_round") == {ally: before["round_number"]}
        await persist(combat_id, data, conn=conn)
        await conn.execute("SELECT 1 / 0")

    attempted = AsyncMock(side_effect=abort)
    with patch("db_mutations.save_combat_state", attempted), pytest.raises(asyncpg.DivisionByZeroError):
        await save(call, ally, face)
    attempted.assert_awaited_once()
    assert walk.fight_state.to_dict() == before
    assert (await walk.checkpoint()).to_dict() == before
    assert await walk.read(ally) == player_before
