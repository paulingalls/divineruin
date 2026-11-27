"""Rest and travel settle concentration before exposing the party again."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import game_tools
from _zhael_unravel_fixtures import patch_player
from _zhael_unravel_fixtures import unravel as unravel
from acceptance._spell_hostile_condition_helpers import dev_db_pool as dev_db_pool
from acceptance.seeds import seed_known_spells
from acceptance.test_spell_bless_lifecycle import BLESS, context, ooc_player, save_total
from acceptance.test_spell_lasting_buffs import BEACON, PROTECTION, save_face
from combat.test_spell_damage_lands import saved_player
from livekit.agents.llm import ToolError
from sample_fixtures import FixedRng, make_context, make_mock_room
from test_orenthel_song_of_rest import song_party

import db
import db_mutations_concentration
import db_mutations_resonance
import db_queries
from activate_tools import activate
from combat_end import end_combat
from movement_tools import _move_player_impl
from participant_lifecycle import PartyLifecycle
from session_hydration import hydrate_session_state
from travel_tools import _travel_impl

INVISIBILITY = "arcane_invisibility"
ANIMAL_SHAPES = "primal_animal_shapes"


async def reload_guest(host, guest, location):
    room = make_mock_room()
    room.remote_participants = {guest: SimpleNamespace(identity=guest)}
    fresh = make_context(host, location, room=room)
    lifecycle = PartyLifecycle(
        room,
        fresh.userdata,
        queries=db_queries,
        resonance_mod=db_mutations_resonance,
        concentration_mod=db_mutations_concentration,
    )
    try:
        assert await lifecycle.authorize(guest) is not None
        return fresh.userdata.member_state(guest).concentration
    finally:
        await lifecycle.aclose()


async def test_rest_keeps_only_spells_longer_than_an_hour(world) -> None:
    async with song_party(world, ("orenthel", "kaelen")) as rest:
        host, guest = world.ids
        remote = await ooc_player(BLESS)
        remote_ctx = context(remote)
        plain = await save_total(remote)
        await activate(remote_ctx, BLESS)
        world.ctx.userdata.party.members.append(remote_ctx.userdata.party.primary)
        for pid, spell, archetype in ((host, INVISIBILITY, "mage"), (guest, ANIMAL_SHAPES, "druid")):
            await seed_known_spells(world.pool, pid, (spell,))
            await world.pool.execute(
                "UPDATE players SET data=data || jsonb_build_object('class', $2::text, 'level', 20, "
                "'focus', '{\"current\":100,\"max\":100}'::jsonb) WHERE player_id=$1",
                pid,
                archetype,
            )
            session = world.ctx.userdata
            lifecycle = session.multiplayer_owner.lifecycle
            generation = await lifecycle.authorize(pid)
            assert generation is not None
            with session._bind_authenticated_actor(pid, generation, lifecycle.require_authorized):
                await game_tools(session, activate)("activate", id=spell)
        with (
            patch("rest_tools.reset_resonance_on_rest", side_effect=RuntimeError("rest recovery failed")),
            pytest.raises(RuntimeError, match="rest recovery failed"),
        ):
            await rest("rest", rest_type="short", use_song_of_rest=False)
        assert (await saved_player(host))["concentration"]["spell_id"] == INVISIBILITY
        assert session.concentration.spell_id == INVISIBILITY
        assert (await saved_player(guest))["concentration"]["elapsed_seconds"] == 0

        await rest("rest", rest_type="short", use_song_of_rest=False)
        fresh = context(host)
        await hydrate_session_state(fresh.userdata, await saved_player(host))
        assert not fresh.userdata.concentration.is_active
        guest_record = (await saved_player(guest))["concentration"]
        assert (guest_record["spell_id"], guest_record["elapsed_seconds"]) == (ANIMAL_SHAPES, 3600)
        joined = await reload_guest(host, guest, session.location_id)
        assert joined == session.member_state(guest).concentration
        await rest("rest", rest_type="long", use_song_of_rest=False)
        assert not (await reload_guest(host, guest, session.location_id)).is_active
        assert await save_total(remote) == plain


async def test_rest_settles_a_caster_who_moved_away(world) -> None:
    async with song_party(world, ("orenthel", "kaelen")) as rest:
        cleric, ally = world.ids
        session = world.ctx.userdata
        await seed_known_spells(world.pool, cleric, (BEACON,))
        await world.pool.execute(
            "UPDATE players SET data=jsonb_set(data,'{focus,current}','12') WHERE player_id=$1", cleric
        )
        await game_tools(session, activate)("activate", id=BEACON, target_id=ally)
        await _move_player_impl(make_context(cleric, session.location_id, room=make_mock_room()), "millhaven")
        assert (await saved_player(cleric))["location_id"] == "millhaven"
        lifecycle = session.multiplayer_owner.lifecycle
        generation = await lifecycle.authorize(ally)
        with session._bind_authenticated_actor(ally, generation, lifecycle.require_authorized):
            packet = await rest("rest", rest_type="short", use_song_of_rest=False)
        assert packet["players"] == [ally]
        assert packet["concentration_expired"] == [{"caster_id": cleric, "spell_id": BEACON}]
        fresh = context(cleric)
        await hydrate_session_state(fresh.userdata, await saved_player(cleric))
        assert fresh.userdata.concentration.spell_id is None
        assert (await saved_player(cleric))["concentration"]["spell_id"] is None
        conditions = (await saved_player(ally))["conditions"]
        assert not [condition for condition in conditions if "sustaining_caster_ids" in condition]


async def test_consecutive_travel_segments_accumulate_cast_time(dev_db_pool) -> None:
    caster = await ooc_player(INVISIBILITY)
    ctx = context(caster)
    await activate(ctx, INVISIBILITY)
    for destination, expected in (("greyvale_south_road", INVISIBILITY), ("greyvale_ruins_exterior", None)):
        await _travel_impl(ctx, destination, "compressed", hours=1, rng=FixedRng(20))
        assert (await saved_player(caster))["concentration"]["spell_id"] == expected


@pytest.mark.parametrize("natural_end", [False, True])
async def test_carried_bless_ends_with_combat(unravel, natural_end) -> None:
    fight = unravel
    caster, other = fight.ids
    await seed_known_spells(fight.pool, caster, (BLESS,))
    await seed_known_spells(fight.pool, other, (PROTECTION,))
    for pid in (caster, other):
        await patch_player(fight, pid, focus={"current": 10, "max": 10})
    cast = game_tools(fight.session, activate)
    baseline = await save_total(caster)
    await fight.invoke(cast, "activate", actor=caster, id=BLESS, target_id=caster)
    await fight.invoke(cast, "activate", actor=other, id=PROTECTION, target_id=other)
    assert await save_total(caster) == baseline + 3
    await fight.start()
    carried = (await saved_player(caster))["concentration"]
    assert (carried["combat_id"], carried["started_round"]) == (fight.session.combat_state.combat_id, 1)
    for round_number in range(2, 5):
        await fight.declare()
        await fight.finish_round(round_number)
    if natural_end:
        state = fight.session.combat_state
        for foe in state.participants:
            if foe.type == "enemy":
                foe.hp_current = 0
                foe.is_fallen = True
        await fight.declare()
        await fight.call("resolve_phase")
        _, result = await fight.call("resolve_phase")
        assert result["outcome"] == "victory"
    else:
        _, result = await fight.invoke(game_tools(fight.session, end_combat), "end_combat", outcome="fled")
    assert result["concentration_expired"] == [{"caster_id": caster, "spell_id": BLESS}]
    player = await saved_player(caster)
    assert player["concentration"]["spell_id"] is None
    assert all(condition["type"] != "blessed" for condition in player["conditions"])
    fresh = context(caster)
    await hydrate_session_state(fresh.userdata, player)
    assert fresh.userdata.concentration.spell_id is None
    assert await save_total(caster, ctx=fresh) == baseline
    survived = await reload_guest(caster, other, fight.session.location_id)
    assert (survived.spell_id, survived.elapsed_seconds, survived.combat_id) == (PROTECTION, 18, None)
    assert await save_face(context(other), "constitution", "hollowed") == 17


@pytest.mark.parametrize(
    ("destination", "arrived"), [("greyvale_south_road", True), ("greyvale_wilderness_north", False)]
)
async def test_first_committed_travel_segment_releases_bless(dev_db_pool, destination, arrived) -> None:
    caster = await ooc_player(BLESS)
    ctx = context(caster)
    plain = await save_total(caster)
    await activate(ctx, BLESS)
    with pytest.raises(ToolError, match="at least 1"):
        await _travel_impl(ctx, destination, "compressed", hours=0)
    assert await save_total(caster, ctx=ctx) == plain + 3

    receipt = json.loads(await _travel_impl(ctx, destination, "compressed", hours=1, rng=FixedRng(1)))
    assert receipt["arrived"] is arrived
    assert receipt["concentration_expired"] == [{"caster_id": caster, "spell_id": BLESS}]
    fresh = context(caster)
    await hydrate_session_state(fresh.userdata, await saved_player(caster))
    assert not fresh.userdata.concentration.is_active
    assert await save_total(caster, ctx=fresh) == plain


async def test_migration_backfills_concentration_in_combat_and_checkpoint(unravel) -> None:
    fight = unravel
    caster = fight.ids[0]
    await fight.start()
    row = await fight.row()
    encounter_id = row["combat_id"]
    record = {"spell_id": BLESS}
    row["round_checkpoints"][0]["players"][caster]["data"]["concentration"] = record
    await fight.write_row(row)
    await patch_player(fight, caster, concentration=record)

    migration = Path(__file__).resolve().parents[4] / "scripts/migrations/070_concentration_lifetime.sql"
    await (await db.get_pool()).execute(migration.read_text())
    expected = {**record, "elapsed_seconds": 0, "combat_id": encounter_id, "started_round": 1}
    assert (await saved_player(caster))["concentration"] == expected
    assert (await fight.row())["round_checkpoints"][0]["players"][caster]["data"]["concentration"] == expected
