"""Infusion eligibility and atomicity through registered commands."""

from unittest.mock import patch

import asyncpg
import pytest
from acceptance.infusion_harness import ASHMARK, CLUB, DAGGER, HANDAXE, INFUSE, SHORTSWORD, STARTER, InfusionWalk
from acceptance.infusion_harness import walk as walk
from acceptance.test_martial_core_kit import declare
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory

import infusion


@pytest.mark.parametrize(("item", "reason"), [(None, "equip a main-hand weapon"), (ASHMARK, "already magical")])
async def test_ineligible_weapon_preserves_player(walk: InfusionWalk, item: str | None, reason: str) -> None:
    if item:
        await walk.equip(item, acquire=True)
    before = await walk.row()
    refusal = await walk.activate_infusion(error=True)
    assert isinstance(refusal, str) and reason in refusal.lower()
    assert await walk.row() == before


async def test_combat_refusal_preserves_player(walk: InfusionWalk) -> None:
    await walk.equip(SHORTSWORD, acquire=True)
    await walk.enter()
    before = await walk.row()
    state = (await walk.reload()).to_dict()
    assert "cannot be used in a fight" in await walk.activate_infusion(error=True)
    assert f"{INFUSE} is not declarable in combat" in await declare(walk, INFUSE, [], error=True)
    assert await walk.row() == before
    assert (await walk.reload()).to_dict() == state


@pytest.mark.parametrize("walk", [(4, True, 12)], indirect=True)
async def test_starter_weapon_has_catalog_identity(walk: InfusionWalk) -> None:
    assert "id" not in await walk.weapon()
    await walk.infuse(STARTER, 1)
    assert set(await walk.infusions()) == {STARTER}
    await walk.strike(1)


@pytest.mark.parametrize("walk", [(10, False, 12)], indirect=True)
async def test_reinfusion_moves_item_to_newest_without_eviction(walk: InfusionWalk) -> None:
    items = (SHORTSWORD, CLUB, HANDAXE)
    for item in items:
        await walk.equip(item, acquire=True)
        await walk.infuse(item, 2)
    await walk.equip(SHORTSWORD)
    await walk.infuse(SHORTSWORD, 2)
    assert set(await walk.infusions()) == set(items)
    await walk.equip(DAGGER, acquire=True)
    await walk.infuse(DAGGER, 2, replaced=CLUB)
    assert set(await walk.infusions()) == {HANDAXE, SHORTSWORD, DAGGER}


async def test_infusion_write_failure_rolls_back_focus_and_record(walk: InfusionWalk) -> None:
    await walk.equip(SHORTSWORD, acquire=True)
    await walk.infuse(SHORTSWORD, 1)
    await walk.equip(CLUB, acquire=True)
    before = await walk.row()
    save = infusion.save
    debited_focus = None

    async def fail_after_save(player_id: str, infusions: dict, *, conn: asyncpg.Connection) -> None:
        nonlocal debited_focus
        await save(player_id, infusions, conn=conn)
        debited_focus = await conn.fetchval(
            "SELECT (data #>> '{focus,current}')::integer FROM players WHERE player_id=$1", player_id
        )
        raise RuntimeError("injected infusion write failure")

    with patch.object(infusion, "save", fail_after_save):
        await walk.activate_infusion(error=True)
    assert debited_focus == before["focus"]["current"] - 2
    assert await walk.row() == before


@pytest.mark.parametrize("walk", [(4, False, 1)], indirect=True)
async def test_insufficient_focus_produces_no_infusion(walk: InfusionWalk) -> None:
    await walk.equip(SHORTSWORD, acquire=True)
    before = await walk.row()
    refusal = await walk.activate_infusion(error=True)
    assert isinstance(refusal, str) and "focus" in refusal.lower()
    assert await walk.row() == before
