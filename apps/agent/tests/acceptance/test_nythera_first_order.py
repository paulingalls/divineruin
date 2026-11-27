"""Landfall Orders through registered combat entry and the saved checkpoint."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import game_tools
from acceptance.test_valdris_sanctuary import AWARD as LAWFUL_COMMAND
from acceptance.test_valdris_sanctuary import TEMPLE
from acceptance.test_valdris_sanctuary import dev_db_pool as dev_db_pool
from sample_fixtures import CONTENT_ROOT, FIXED_NOW, make_context, make_mock_room

import db
import db_mutations
from creation_rules import build_character_data
from mode_tools import enter_mode
from query_tools import query_info

CLAUSE = "nythera_first_order"
LANDFALL = {"id": CLAUSE, "name": "Landfall Orders", "bonus": 1}
PROFILE = json.loads((CONTENT_ROOT / "packages/shared/fixtures/god_profiles.json").read_text())["first_order"]
ENCOUNTER = "ruins_mawling_pair"
COMPANION = "companion_kael"
ENEMIES = ("mawling_1", "mawling_2")


@asynccontextmanager
async def encounter_silence(pool, center: str | None) -> AsyncIterator[None]:
    if center is None:
        yield
        return

    original = await pool.fetchval("SELECT data FROM encounter_templates WHERE id=$1", ENCOUNTER)
    encounter = json.loads(original)
    scene = encounter["scene_placement"]
    scene["locations"]["silence_center"] = scene[center]
    scene["zones"]["silence_sphere"] = {"kind": "silence", "center_id": "silence_center", "radius_ft": 1}
    await pool.execute("UPDATE encounter_templates SET data=$2::jsonb WHERE id=$1", ENCOUNTER, json.dumps(encounter))
    try:
        yield
    finally:
        await pool.execute("UPDATE encounter_templates SET data=$2::jsonb WHERE id=$1", ENCOUNTER, original)


async def enter_with_orders(
    world: SimpleNamespace,
    *,
    landfall: tuple[str, ...] = ("host", "guest", COMPANION),
    history: tuple[int, int] = (1, 0),
    marshal: str = "host",
    source_condition: str | None = None,
    silence: str | None = None,
    valdris: bool = False,
    two_sources: bool = False,
    deaf_ally: bool = False,
    active_profile: bool = False,
) -> None:
    host, guest = world.ids
    ids = {"host": host, "guest": guest, COMPANION: COMPANION, **{enemy: enemy for enemy in ENEMIES}}
    rolls = {host: 8, guest: 12, ENEMIES[0]: 10, ENEMIES[1]: 3, COMPANION: 10}
    base_totals = {host: 10, guest: 14, ENEMIES[0]: 11, ENEMIES[1]: 4, COMPANION: 11}
    third = f"{host}_third"
    if deaf_ally:
        rolls = {host: 8, guest: 12, third: 3, ENEMIES[0]: 10, ENEMIES[1]: 3, COMPANION: 10}
        base_totals[third] = 5
        await world.pool.execute("INSERT INTO players (player_id, data) VALUES ($1, '{}'::jsonb)", third)

    session = make_context(
        host,
        TEMPLE,
        make_mock_room(),
        party_member_ids=[guest, *([third] if deaf_ally else [])],
        companion_id=COMPANION,
    ).userdata
    try:
        for pid in session.party.member_ids:
            if pid == ids[marshal] or (two_sources and pid == guest):
                job, patron = ("mage" if source_condition == "wrong-class" else "marshal"), "nythera"
            elif valdris and pid == guest:
                job, patron = "marshal", "valdris"
            else:
                job, patron = "warrior", "kaelen"
            row = build_character_data(pid, "human", job, patron, "", created_at=FIXED_NOW)
            row["attributes"]["dexterity"] = 14
            if pid == ids[marshal] and source_condition == "unconscious":
                row["hp"]["current"] = 0
            if pid == third or (pid == ids[marshal] and source_condition == "deafened"):
                row["conditions"] = [{"type": "deafened"}]
            await world.pool.execute("UPDATE players SET data=$2::jsonb WHERE player_id=$1", pid, json.dumps(row))

        for pid, visits in zip(world.ids, history, strict=True):
            for _ in range(visits):
                await db_mutations.upsert_map_progress(pid, TEMPLE, [], conn=world.pool)

        faces = iter(rolls.values())
        call = game_tools(session, enter_mode, query_info)
        async with encounter_silence(world.pool, silence):
            with (
                patch.object(db, "_cache_get", AsyncMock(return_value=None)),
                patch.object(db, "_cache_set", AsyncMock()),
                patch("combat_agent.create_combat_agent") as factory,
                patch("combat_resolution.dice_roll", side_effect=lambda *_a, **_kw: SimpleNamespace(total=next(faces))),
            ):
                if active_profile:
                    assert (await call("query_info", kind="patron"))["synergy"] == PROFILE
                _, receipt = await call(
                    "enter_mode", mode="combat", encounter_id=ENCOUNTER, initiated_by="enemies" if valdris else "party"
                )

        awards = {ids[role]: [LANDFALL] for role in landfall}
        if valdris:
            awards[guest].insert(0, LAWFUL_COMMAND)
        expected_totals = {
            pid: total + (pid in awards) + (valdris and pid == guest) for pid, total in base_totals.items()
        }
        if "host" in landfall and COMPANION in landfall:
            expected_order = [guest, COMPANION, host, *ENEMIES]
        elif "host" in landfall:
            expected_order = [guest, host, ENEMIES[0], COMPANION, ENEMIES[1]]
        else:
            expected_order = [guest, ENEMIES[0], COMPANION, host, ENEMIES[1]]
        if deaf_ally:
            expected_order.insert(-1, third)

        saved = await db_mutations.load_combat_state(receipt["combat_id"])
        assert saved is not None
        if active_profile:
            checkpoint = saved.round_checkpoints[0]["combat"]
            assert checkpoint["initiative_order"] == expected_order
            assert {row["id"]: row["initiative"] for row in checkpoint["participants"]} == expected_totals
        assert {participant.id: participant.initiative for participant in saved.participants} == expected_totals
        assert saved.initiative_order == expected_order
        summary = receipt["initiative_order"]
        assert [row["id"] for row in summary] == expected_order
        assert {row["id"]: (row["roll"], row["total"]) for row in summary} == {
            pid: (roll, expected_totals[pid]) for pid, roll in rolls.items()
        }
        assert {row["id"]: row["initiative_bonus"] for row in summary if "initiative_bonus" in row} == awards
        if valdris:
            (handoff,) = factory.call_args.kwargs["chat_ctx"].items
            _, label, encoded = handoff.content[0].partition("Initiative bonuses by participant: ")
            assert label
            assert json.JSONDecoder().raw_decode(encoded)[0] == awards
    finally:
        if session.combat_state:
            await db_mutations.delete_combat_state(session.combat_state.combat_id, conn=world.pool)
        if deaf_ally:
            await world.pool.execute("DELETE FROM players WHERE player_id=$1", third)


async def landfall_orders(world: SimpleNamespace) -> None:
    await enter_with_orders(world, active_profile=True)


@pytest.mark.parametrize(
    "options",
    [
        pytest.param({"history": (1, 1), "two_sources": True}, id="two-sources"),
        pytest.param({"history": (2, 0), "landfall": ()}, id="revisited"),
        pytest.param({"history": (0, 0), "landfall": ()}, id="no-map-row"),
        pytest.param({"source_condition": "unconscious", "landfall": ()}, id="unconscious"),
        pytest.param({"source_condition": "wrong-class", "landfall": ()}, id="wrong-class"),
        pytest.param({"marshal": "guest", "history": (2, 1)}, id="only-other-player-revisited"),
        pytest.param({"marshal": "guest", "history": (1, 2), "landfall": ()}, id="only-marshal-revisited"),
        pytest.param({"deaf_ally": True}, id="deafened-ally"),
        pytest.param({"silence": "companion_start", "landfall": ("host", "guest")}, id="silenced-companion"),
        pytest.param({"silence": "party_start", "landfall": ()}, id="silenced-marshal"),
        pytest.param({"source_condition": "deafened"}, id="deafened-marshal"),
        pytest.param({"valdris": True}, id="lawful-command-stacks"),
    ],
)
async def test_registered_combat_entry(world: SimpleNamespace, options: dict) -> None:
    await enter_with_orders(world, **options)


async def test_landfall_profile_and_checkpoint(world: SimpleNamespace) -> None:
    await landfall_orders(world)


SCENARIOS = {CLAUSE: ("patron_synergy_combat:first_order_initiative_bonus", landfall_orders, [()])}
