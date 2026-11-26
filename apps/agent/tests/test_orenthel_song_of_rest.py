"""Restoring Song through the authored catalog and registered rest command."""

import random
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import row
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import game_tools
from acceptance.seeds import seed_player_with_pools
from test_aelora_gift import _live_party

import dice
from _gods_content import load_gods
from db_mutations import update_player_hp
from rest_tools import rest

ORENTHEL_SONG = "orenthel_song_of_rest"
RestCommand = Callable[..., Awaitable[dict]]


def test_restoring_song_catalog() -> None:
    orenthel = next(god for god in load_gods() if god["god_id"] == "orenthel")
    assert orenthel["layer_4_synergy_matrix"]["bard"] == {
        "type": "divine",
        "name": "Restoring Song",
        "clauses": [
            {
                "effect": "Song of Rest +1d6 HP.",
                "status": "active",
                "resolution": "engine",
                "implementation_id": ORENTHEL_SONG,
            },
            {
                "effect": "Inspire dice can heal instead of buffing rolls",
                "status": "active",
                "resolution": "engine",
                "implementation_id": "orenthel_inspire_heal",
            },
        ],
    }


@asynccontextmanager
async def song_party(
    world: SimpleNamespace, patrons: tuple[str, str], *, singer_index: int = 0, deafened_guest: bool = False
) -> AsyncIterator[RestCommand]:
    session = world.ctx.userdata
    host, guest = world.ids
    assert session.primary_player_id == host
    session.location_id = "millhaven_inn"
    for index, (pid, patron) in enumerate(zip((host, guest), patrons, strict=True)):
        sings = index == singer_index
        archetype = "bard" if sings else "warrior"
        await seed_player_with_pools(
            world.pool,
            player_id=pid,
            class_=archetype,
            stamina_current=1,
            focus_current=0,
            equipped_electives=("bard_song_of_rest",) if sings else (),
        )
        await configure(
            world,
            patron,
            archetype,
            index=index,
            level=4,
            location_id=session.location_id,
            hp={"current": 24 if deafened_guest and sings else 3, "max": 30},
            maxhp_override=-5 if deafened_guest and sings else 0,
            focus={"current": 0, "max": 12},
            resonance={"current": 9, "flickering_bonus": 0},
            conditions=[{"type": "deafened"}] if deafened_guest and pid == guest else [],
        )
    lifecycle = _live_party(session, host, guest)
    try:
        generation = await lifecycle.authorize(host)
        assert generation is not None
        assert await lifecycle.authorize(guest) is not None
        session.member_state(world.ids[singer_index]).patron_id = patrons[1 - singer_index]
        with session._bind_authenticated_actor(host, generation, lifecycle.require_authorized):
            yield game_tools(session, rest)
    finally:
        await lifecycle.aclose()


async def assert_song(
    world: SimpleNamespace,
    call: RestCommand,
    *,
    singer: str,
    expected_dice: list[tuple[int, int]],
    unheard: tuple[str, ...] = (),
    capped: str | None = None,
) -> None:
    rng = random.Random(7)
    rolls: list[tuple[str, int]] = []

    def seeded_roll(notation: str) -> dice.DiceResult:
        result = dice.roll(notation, rng=rng)
        rolls.append((notation, result.total))
        return result

    with patch("song_of_rest.roll", seeded_roll):
        result = await call("rest", rest_type="short", use_song_of_rest=True)
    receipt = result["song_of_rest"]
    assert receipt["singer_id"] == singer
    assert receipt["focus_paid"] == 3

    expected_rolls = []
    expected_healing = []
    expected_hp = dict.fromkeys(world.ids, 3)
    recipients = sorted(set(world.ids) - set(unheard))
    for pid, (base, bonus) in zip(recipients, expected_dice, strict=True):
        expected_rolls.append(("1d8", base))
        hp_before = 24 if pid == capped else 3
        hp_after = 25 if pid == capped else hp_before + base + bonus
        expected_hp[pid] = hp_after
        entry: dict = {
            "player_id": pid,
            "roll": base,
            "hp_before": hp_before,
            "hp_after": hp_after,
            "healed": hp_after - hp_before,
        }
        if bonus:
            expected_rolls.append(("1d6", bonus))
            entry["synergy_components"] = [{"id": ORENTHEL_SONG, "dice": "1d6", "bonus": bonus}]
        expected_healing.append(entry)

    assert rolls == expected_rolls
    assert receipt["healing"] == expected_healing
    assert receipt["skipped"] == [{"player_id": pid, "reason": "cannot_hear"} for pid in unheard]
    for index, pid in enumerate(world.ids):
        rested = await row(world, index)
        assert rested["hp"]["current"] == expected_hp[pid]
        assert rested["focus"]["current"] == (3 if pid == singer else 6)
        if pid in unheard:
            assert rested["stamina"]["current"] == 10
            assert rested["resonance"]["current"] == world.ctx.userdata.member_state(pid).resonance.current == 0


async def restoring_song_scenario(world: SimpleNamespace) -> None:
    host, guest = world.ids
    async with song_party(world, ("orenthel", "kaelen")) as call:
        await assert_song(world, call, singer=host, expected_dice=[(6, 2), (7, 6)])

        await configure(world, "kaelen", "bard", hp={"current": 3, "max": 30})
        await update_player_hp(guest, 3, conn=world.pool)
        await assert_song(world, call, singer=host, expected_dice=[(6, 0), (3, 0)])


@pytest.mark.parametrize(
    "host_patron,guest_patron,expected_dice",
    [("kaelen", "orenthel", [(6, 2), (7, 6)]), ("orenthel", "kaelen", [(6, 0), (3, 0)])],
)
async def test_guest_singer_uses_persisted_patron(
    world: SimpleNamespace, host_patron: str, guest_patron: str, expected_dice: list[tuple[int, int]]
) -> None:
    async with song_party(world, (host_patron, guest_patron), singer_index=1) as call:
        await assert_song(world, call, singer=world.ids[1], expected_dice=expected_dice)


async def test_deafened_guest_gets_neither_die(world: SimpleNamespace) -> None:
    host, guest = world.ids
    async with song_party(world, ("orenthel", "kaelen"), deafened_guest=True) as call:
        await assert_song(world, call, singer=host, expected_dice=[(6, 2)], unheard=(guest,), capped=host)


SCENARIOS = {ORENTHEL_SONG: ("song_of_rest:apply_song_of_rest", restoring_song_scenario, [()])}
