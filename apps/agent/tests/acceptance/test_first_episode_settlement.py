"""Episode settlement is owned by the combat engine, on every terminal outcome."""

import pytest
from acceptance.first_episode_settlement_harness import assert_settled
from acceptance.first_episode_settlement_harness import fragment_player as fragment_player

import db_queries
from combat_end import end_combat
from mode_tools import enter_mode
from quest_tools import update_quest


@pytest.fixture
def quest_starts(monkeypatch):
    from unittest.mock import AsyncMock

    import first_episode

    observer = AsyncMock(wraps=first_episode.advance_quest_db)
    monkeypatch.setattr(first_episode, "advance_quest_db", observer)
    return observer


@pytest.mark.parametrize("outcome", ["victory", "defeat", "fled"])
async def test_standalone_settlement(fragment_player, quest_starts, outcome):
    ctx = await fragment_player()
    cs = ctx.userdata.combat_state
    combat_id = cs.combat_id
    if outcome == "victory":
        for actor in cs.participants:
            if actor.type == "enemy":
                actor.hp_current = 0
                actor.is_fallen = True
    await end_combat(ctx, outcome)
    await assert_settled(ctx)
    assert quest_starts.await_count == 1
    assert quest_starts.await_args.args[1:] == ("greyvale_anomaly", 0)
    import db_mutations

    assert await db_mutations.load_combat_state(combat_id) is None
    if outcome == "defeat":
        player = await db_queries.get_player(ctx.userdata.player_id)
        assert player is not None
        assert player["hp"]["current"] > 0
        assert ctx.userdata.location_id == player["location_id"]


async def test_replay_preserves_fragment_and_advanced_quest(fragment_player, quest_starts):
    ctx = await fragment_player()
    await end_combat(ctx, "fled")
    await assert_settled(ctx)
    assert quest_starts.await_count == 1
    assert quest_starts.await_args.args[1:] == ("greyvale_anomaly", 0)
    await update_quest(ctx, "greyvale_anomaly", 1)
    ctx.userdata.location_id = "accord_guild_infirmary"
    await enter_mode(ctx, "combat", "fragment_shadeling", "Replay")
    await end_combat(ctx, "fled")
    await assert_settled(ctx, stage=1)
    assert quest_starts.await_count == 1
    from sample_fixtures import published_payloads

    import event_types as E

    assert (
        sum(
            p["type"] == E.ITEM_ACQUIRED and p.get("item_id") == "greyvale_veil_fragment"
            for p in published_payloads(ctx.userdata.room)
        )
        == 1
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"location": "accord_market_square"},
        {"receipt": None},
        {"receipt": "complete"},
        {"encounter": "shadeling_cluster"},
    ],
)
async def test_unrelated_fight_does_not_start_episode(fragment_player, quest_starts, overrides):
    ctx = await fragment_player(**overrides)
    await end_combat(ctx, "fled")
    quest_starts.assert_not_awaited()
    assert await db_queries.get_player_quest(ctx.userdata.player_id, "greyvale_anomaly") is None
    inventory = await db_queries.get_player_inventory(ctx.userdata.player_id)
    assert not any(row["id"] == "greyvale_veil_fragment" for row in inventory)


@pytest.mark.parametrize("outcome", ["victory", "defeat", "deescalated"])
async def test_automatic_wrap_settlement(fragment_player, quest_starts, outcome):
    from unittest.mock import patch

    from acceptance._capstone_helpers import _d20
    from acceptance.first_episode_settlement_harness import declarations, drain

    import db
    from combat_death_save import request_death_save

    ctx = await fragment_player(archetype="cleric" if outcome == "deescalated" else "warrior")
    cs = ctx.userdata.combat_state
    if outcome == "defeat":
        for actor in cs.participants:
            if actor.type != "enemy":
                actor.hp_current = 0
                actor.is_fallen = True
        cs.get_participant(ctx.userdata.player_id).death_save_failures = 2
        with patch("combat_resolution.dice_roll", return_value=_d20(1)):
            await request_death_save(ctx, ctx.userdata.player_id)
    if outcome == "deescalated":
        pool = await db.get_pool()
        await pool.execute(
            "UPDATE players SET data=jsonb_set(jsonb_set(data, '{focus}', '{\"current\":12,\"max\":12}'), '{attributes,charisma}', '22') WHERE player_id=$1",
            ctx.userdata.player_id,
        )
    result = None
    with patch("check_resolution.dice_roll", return_value=_d20(20)):
        for _ in range(12):
            await declarations(ctx, argue=outcome == "deescalated")
            result = await drain(ctx)
            if isinstance(result, tuple):
                break
    import json

    assert isinstance(result, tuple)
    assert json.loads(result[1])["outcome"] == outcome
    await assert_settled(ctx)
    assert quest_starts.await_count == 1
    assert quest_starts.await_args.args[1:] == ("greyvale_anomaly", 0)


async def test_seeded_rider_instructions_and_retained_events(reset_db_pool):
    import json

    from sample_fixtures import CONTENT_ROOT

    import db_content_queries

    scene = await db_content_queries.get_scene("scene_rider_arrival")
    assert scene is not None
    instructions = scene["instructions"]
    assert 'enter_mode(mode="combat", encounter_id="fragment_shadeling")' in instructions
    assert "accord_guild_infirmary" in instructions
    assert all(
        cue in instructions + scene["aftermath"]
        for cue in ("oilcloth", "Sound thins", "One shadeling", "After the fight", "Torin", "north")
    )
    assert scene["beats"] and all(beat["companion_hints"] for beat in scene["beats"])
    events = json.loads((CONTENT_ROOT / "content/events.json").read_text())
    assert {event["id"] for event in events} == {
        "hollow_patrol_encounter",
        "ruins_discovery_ripple",
        "faction_interest_triggered",
        "god_whisper_patron",
        "millhaven_under_threat",
    }


async def test_quest_started_during_rider_is_preserved(fragment_player, quest_starts):
    ctx = await fragment_player()
    await update_quest(ctx, "greyvale_anomaly", 0)
    await update_quest(ctx, "greyvale_anomaly", 1)
    await end_combat(ctx, "fled")
    await assert_settled(ctx, stage=1)
    quest_starts.assert_not_awaited()
