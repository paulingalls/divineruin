"""Song of Rest through registered tools and committed player rows."""

import json
import random
from contextlib import asynccontextmanager

import pytest
from acceptance.mawling_harness import MawlingHarness
from livekit.agents.llm import ToolError
from test_aelora_gift import _live_party

import abilities
import ability_persistence
import db_mutations
import db_queries
import dice
import mentor_variants
import song_of_rest
from activate_tools import activate
from rest_tools import rest

SONG = "bard_song_of_rest"
TIDECALLER = "bard_song_of_rest_tidecaller"
THORNWARDEN = "bard_song_of_rest_thornwarden"
INN = "millhaven_inn"
SEED = 7


@pytest.fixture
def party(dev_db_pool, monkeypatch):
    @asynccontextmanager
    async def prepare(*classes: str, owned: tuple[int, ...] = (0,), focus_max: int = 12):
        walk = await MawlingHarness().prepare((4,) * len(classes), companion=None, location=INN, tools=[rest, activate])
        ids = sorted(walk.players)
        walk.players[:] = reversed(ids)
        walk.sd.party.members.sort(key=lambda member: member.player_id, reverse=True)
        rolls: list[int] = []
        rng = random.Random(SEED)

        def seeded_roll(notation: str) -> dice.DiceResult:
            assert notation == "1d8"
            result = dice.roll(notation, rng=rng)
            rolls.append(result.total)
            return result

        monkeypatch.setattr(song_of_rest, "roll", seeded_roll)
        lifecycle = _live_party(walk.sd, *ids)
        try:
            for index, (pid, class_) in enumerate(zip(ids, classes, strict=True)):
                await update(
                    walk,
                    pid,
                    name=f"Resting {class_.title()} {index}",
                    **{"class": class_},
                    hp={"current": 3, "max": 30},
                    stamina={"current": 1, "max": 10},
                    focus={"current": 0, "max": focus_max if index == 0 else 12},
                    resonance={"current": 5, "flickering_bonus": 0},
                    conditions=[],
                )
                walk.sd.member_state(pid).resonance.current = 5
                if index in owned:
                    await ability_persistence.set_elective_equipped(pid, SONG, False, conn=dev_db_pool)
            for pid in ids:
                assert await lifecycle.authorize(pid) is not None
            walk.sd.event_bus.drain()
            yield walk, ids, rolls
        finally:
            await lifecycle.aclose()
            await walk.close()

    return prepare


async def update(walk: MawlingHarness, player_id: str, **fields: object) -> None:
    await walk.pool.execute(
        "UPDATE players SET data=data || $2::jsonb WHERE player_id=$1", player_id, json.dumps(fields)
    )


async def row(player_id: str, **kwargs) -> dict:
    player = await db_queries.get_player(player_id, **kwargs)
    assert player is not None
    return player


async def snapshot(walk: MawlingHarness) -> tuple[list[dict], list[int]]:
    return (
        [await row(pid) for pid in walk.players],
        [walk.sd.member_state(pid).resonance.current for pid in walk.players],
    )


async def take_rest(walk: MawlingHarness, kind: str = "short", *, song: bool = True, error: bool = False):
    return await walk.command("rest", {"rest_type": kind, "use_song_of_rest": song}, error=error)


def expected_rolls(count: int) -> list[int]:
    rng = random.Random(SEED)
    return [dice.roll("1d8", rng=rng).total for _ in range(count)]


@pytest.mark.parametrize("variant,cost,maximum", [(None, 3, 12), (TIDECALLER, 2, 4), (THORNWARDEN, 4, 12)])
async def test_extra_healing_and_recovered_focus(party, variant, cost, maximum):
    async with party("bard", "warrior", focus_max=maximum) as (walk, (bard, warrior), rolls):
        await update(walk, warrior, hp={"current": 24, "max": 30}, maxhp_override=-5)
        source = abilities.get_ability(SONG)
        if variant:
            await ability_persistence.set_active_variant(bard, SONG, variant, conn=walk.pool)
            source = mentor_variants.get_variant(SONG, variant)
        else:
            ordinary = await take_rest(walk, song=False)
            assert "song_of_rest" not in ordinary and rolls == []
            assert (await row(bard))["focus"]["current"] == 6
            assert [(await row(pid))["hp"]["current"] for pid in (bard, warrior)] == [3, 24]
            await update(walk, bard, focus={"current": 0, "max": maximum})

        result = await take_rest(walk)
        bard_roll, warrior_roll = expected_rolls(2)
        assert (await row(bard))["hp"]["current"] == 3 + bard_roll
        assert (await row(bard))["focus"]["current"] == maximum // 2 - cost
        warrior_row = await row(warrior)
        assert warrior_row["hp"] == {"current": 25, "max": 30}
        assert warrior_row["maxhp_override"] == -5
        assert rolls == [bard_roll, warrior_roll]
        assert result["song_of_rest"] == {
            "ability_id": SONG,
            "singer_id": bard,
            "singer_name": "Resting Bard 0",
            "variant_id": variant,
            "focus_paid": cost,
            "narration_cue": source.narration_cue,
            "healing": [
                {"player_id": bard, "roll": bard_roll, "hp_before": 3, "hp_after": 3 + bard_roll, "healed": bard_roll},
                {"player_id": warrior, "roll": warrior_roll, "hp_before": 24, "hp_after": 25, "healed": 1},
            ],
            "skipped": [],
        }


@pytest.mark.parametrize(
    "kind,owned,maximum,reason",
    [
        ("short", (), 12, "learned"),
        ("short", (0,), 4, "Focus"),
        ("long", (0,), 12, "short rest"),
    ],
)
async def test_refusal_leaves_rest_untouched(party, kind, owned, maximum, reason):
    async with party("bard", "warrior", owned=owned, focus_max=maximum) as (walk, _, rolls):
        before = await snapshot(walk)
        assert reason in await take_rest(walk, kind, error=True)
        assert await snapshot(walk) == before
        assert rolls == [] and walk.sd.event_bus.drain() == []
        if kind == "long":
            assert (await take_rest(walk, kind, song=False))["rested"]
            assert rolls == []


@pytest.mark.parametrize("first_maximum", [12, 4])
async def test_one_singer_in_player_id_order(party, first_maximum):
    async with party("bard", "bard", owned=(0, 1), focus_max=first_maximum) as (walk, ids, rolls):
        singer = ids[0] if first_maximum == 12 else ids[1]
        receipt = (await take_rest(walk))["song_of_rest"]
        assert receipt["singer_id"] == singer and receipt["focus_paid"] == 3
        assert rolls == expected_rolls(2)
        for pid, maximum, rolled in zip(ids, (first_maximum, 12), rolls, strict=True):
            player = await row(pid)
            assert player["hp"]["current"] == 3 + rolled
            assert player["focus"]["current"] == maximum // 2 - (3 if pid == singer else 0)


async def test_remote_owner_and_ally_are_skipped(party):
    async with party("bard", "warrior", "bard", "warrior", owned=(0, 2)) as (walk, ids, rolls):
        remote_owner, remote_ally, local_bard, local_ally = ids
        remotes = (remote_owner, remote_ally)
        for pid in remotes:
            await update(walk, pid, location_id="millhaven")
        before = [await row(pid) for pid in remotes]
        receipt = (await take_rest(walk))["song_of_rest"]
        assert receipt["singer_id"] == local_bard
        assert receipt["skipped"] == [{"player_id": pid, "reason": "not_at_rest_location"} for pid in remotes]
        assert [await row(pid) for pid in remotes] == before
        assert (await row(local_bard))["focus"]["current"] == 3
        assert rolls == expected_rolls(2)
        assert [(await row(pid))["hp"]["current"] for pid in (local_bard, local_ally)] == [3 + roll for roll in rolls]


async def test_mid_rest_write_failure_rolls_back_song(party, monkeypatch):
    async with party("bard", "warrior") as (walk, (bard, warrior), rolls):
        before = await snapshot(walk)
        update_hp = db_mutations.update_player_hp
        reached = False

        async def fail_warrior_write(player_id, hp, *, conn):
            nonlocal reached
            if player_id == warrior:
                written = await row(bard, conn=conn)
                assert written["hp"]["current"] == 3 + expected_rolls(2)[0]
                assert written["focus"]["current"] == 3
                reached = True
                raise ToolError("injected rest HP write failure")
            await update_hp(player_id, hp, conn=conn)

        monkeypatch.setattr(db_mutations, "update_player_hp", fail_warrior_write)
        error = await take_rest(walk, error=True)
        assert reached and "injected rest HP write failure" in error
        assert rolls == expected_rolls(2)
        assert await snapshot(walk) == before
        assert walk.sd.event_bus.drain() == []


@pytest.mark.parametrize("ability_id", [SONG, TIDECALLER, THORNWARDEN])
async def test_activate_routes_song_to_rest_without_spending(party, ability_id):
    async with party("bard") as (walk, (bard,), rolls):
        await update(walk, bard, focus={"current": 12, "max": 12})
        if ability_id != SONG:
            await ability_persistence.set_active_variant(bard, SONG, ability_id, conn=walk.pool)
        before = await snapshot(walk)
        error = await walk.command("activate", {"id": ability_id}, error=True)
        assert 'rest(rest_type="short", use_song_of_rest=true)' in error
        assert await snapshot(walk) == before
        assert rolls == [] and walk.sd.event_bus.drain() == []
