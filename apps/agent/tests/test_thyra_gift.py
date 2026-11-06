import copy
import json
from unittest.mock import AsyncMock, patch

import pytest
from sample_fixtures import make_context

import check_tools
import db_activity_queries
import db_content_queries
import db_mutations
import query_tools
from _gods_content import load_gods
from check_payloads import DiscoverCheck, SkillCheck
from combat_state import CombatState
from conditions import apply_condition
from tools._discover_fixtures import _roll
from tools._helpers import _skill_mocks


@pytest.fixture
def world(monkeypatch):
    ctx = make_context(location_id="forest_here")
    queries, mutations = _skill_mocks()
    queries.get_player.return_value = {
        "player_id": "player_1",
        "level": 3,
        "attributes": {},
        "conditions": [],
        "divine_favor": {"patron": "thyra", "level": 0, "max": 100},
        "flags": {},
    }
    monkeypatch.setattr(check_tools.db_queries, "get_player", queries.get_player)
    monkeypatch.setattr(check_tools.db_queries, "get_single_skill_advancement", queries.get_single_skill_advancement)
    monkeypatch.setattr(
        check_tools.db_mutations_skill_advancement, "update_skill_advancement", mutations.update_skill_advancement
    )
    terrain = AsyncMock(return_value="forest")
    monkeypatch.setattr(db_content_queries, "get_location_terrain", terrain)
    monkeypatch.setattr(
        db_content_queries,
        "get_location",
        AsyncMock(return_value={"id": "forest_here", "name": "Forest", "hidden_elements": []}),
    )
    favor = AsyncMock(side_effect=lambda _: queries.get_player.return_value["divine_favor"])
    monkeypatch.setattr(db_activity_queries, "get_divine_favor", favor)
    monkeypatch.setattr(db_mutations, "set_player_flag", AsyncMock())
    return ctx, queries.get_player.return_value, terrain, favor


async def skill_roll(ctx, skill="perception", dice=(2, 18), difficulty="moderate", hearing_only=False):
    with patch("check_resolution.dice_roll", side_effect=[_roll(n) for n in dice]) as rolls:
        result = json.loads(
            await check_tools.check(
                ctx,
                SkillCheck(
                    kind="skill",
                    skill=skill,
                    difficulty=difficulty,
                    context_description="Observe the woods",
                    hearing_only=hearing_only,
                ),
            )
        )
    return result, rolls.call_count


@pytest.mark.asyncio
@pytest.mark.parametrize("skill", ["perception", "survival"])
async def test_natures_pulse_rolls_with_advantage(world, skill):
    result, count = await skill_roll(world[0], skill)
    assert (result["roll"], count, result.get("gift_name")) == (18, 2, "Nature's Pulse")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "patron,terrain,skill",
    [
        ("thyra", "city", "perception"),
        ("thyra", "village", "perception"),
        ("aelora", "forest", "perception"),
        ("none", "forest", "perception"),
        ("thyra", "forest", "athletics"),
    ],
)
async def test_exclusions(world, patron, terrain, skill):
    ctx, player, terrain_read, _ = world
    positive, count = await skill_roll(ctx)
    assert (positive["roll"], count, positive.get("gift_name")) == (18, 2, "Nature's Pulse")
    player["divine_favor"]["patron"] = patron
    terrain_read.return_value = terrain
    terrain_read.reset_mock()
    result, count = await skill_roll(ctx, skill)
    assert (result["roll"], count) == (2, 1)
    assert "gift_name" not in result
    if patron != "thyra" or skill == "athletics":
        terrain_read.assert_not_awaited()


@pytest.mark.asyncio
async def test_condition_disadvantage_cancels(world):
    ctx, player, _, _ = world
    player["conditions"] = apply_condition([], "blinded")
    result, count = await skill_roll(ctx, dice=(18, 2))
    assert (result["roll"], count, result.get("gift_name")) == (18, 1, "Nature's Pulse")


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["location", "patron"])
async def test_ecosystem_cue_only_here_on_natural_terrain(world, kind):
    ctx, player, terrain_read, favor_read = world

    async def query(target="forest_here"):
        return json.loads(await query_tools.query_info(ctx, kind, target))

    result = await query()
    cue = result["ecosystem_health_cue"]
    assert cue["gift_name"] == "Nature's Pulse"
    assert cue["location_id"] == "forest_here"
    assert "ecosystem health" in cue["instruction"] and "without a check" in cue["instruction"]
    terrain_read.return_value = "city"
    assert "ecosystem_health_cue" not in await query()
    terrain_read.return_value = "forest"
    player["divine_favor"]["patron"] = "aelora"
    assert "ecosystem_health_cue" not in await query()
    if kind == "location":
        player["divine_favor"]["patron"] = "thyra"
        favor_read.reset_mock()
        assert "ecosystem_health_cue" not in await query("remote_forest")
        favor_read.assert_not_awaited()


@pytest.mark.asyncio
async def test_inactive_gift_grants_neither_half(world, monkeypatch):
    ctx = world[0]
    assert (await skill_roll(ctx))[0].get("gift_name") == "Nature's Pulse"
    assert "ecosystem_health_cue" in json.loads(await query_tools.query_info(ctx, "patron", ""))
    rows = copy.deepcopy(load_gods())
    next(row for row in rows if row["god_id"] == "thyra")["layer_1_gift"]["status"] = "awaits_terrain"
    monkeypatch.setattr("patron_gifts.load_gods", lambda: rows)
    result, count = await skill_roll(ctx)
    assert (result["roll"], count) == (2, 1)
    assert "gift_name" not in result
    for kind in ("location", "patron"):
        assert "ecosystem_health_cue" not in json.loads(await query_tools.query_info(ctx, kind, "forest_here"))


@pytest.mark.asyncio
async def test_combat_cache_controls_both_halves(world, monkeypatch):
    ctx, _, terrain_read, _ = world
    ctx.userdata.combat_state = CombatState(
        combat_id="combat", participants=[], initiative_order=[], location_id="combat_forest", terrain="forest"
    )
    monkeypatch.setattr(db_content_queries, "get_location", AsyncMock(return_value={"name": "City", "terrain": "city"}))
    terrain_read.side_effect = AssertionError("Combat must use cached terrain")
    result, count = await skill_roll(ctx)
    assert (result["roll"], count, result.get("gift_name")) == (18, 2, "Nature's Pulse")
    for kind in ("location", "patron"):
        cue = json.loads(await query_tools.query_info(ctx, kind, "combat_forest"))["ecosystem_health_cue"]
        assert cue["location_id"] == "combat_forest"


@pytest.mark.asyncio
@pytest.mark.parametrize("producer", ["discover_empty", "discover_candidate"])
async def test_discover_gets_advantage(world, monkeypatch, producer):
    hidden = (
        []
        if producer == "discover_empty"
        else [{"id": "secret", "discover_skill": "perception", "dc": 12, "description": "A trail"}]
    )
    monkeypatch.setattr(db_content_queries, "get_location", AsyncMock(return_value={"hidden_elements": hidden}))
    with patch("check_resolution.dice_roll", side_effect=[_roll(2), _roll(18)]) as rolls:
        result = json.loads(
            await check_tools.check(
                world[0], DiscoverCheck(kind="discover", skill="perception", target="trees", hearing_only=False)
            )
        )
    assert (result["roll"], rolls.call_count, result.get("gift_name")) == (18, 2, "Nature's Pulse")


@pytest.mark.asyncio
@pytest.mark.parametrize("producer", ["gather", "travel", "choir"])
async def test_other_skill_producers_get_advantage(world, producer):
    from types import SimpleNamespace

    from combat._catalog_fixtures import deps, setup
    from test_travel_tools import _run as travel_run
    from test_travel_tools import _travel_mocks

    import choir_encounter
    from combat_packet import _resolve_one_packet
    from declarations import Declaration, DeclarationType
    from tools.test_gathering_tools import _gather_mocks
    from tools.test_gathering_tools import _run as gather_run

    ctx, player, terrain_read, _ = world
    with patch("check_resolution.dice_roll", side_effect=[_roll(2), _roll(18)]) as rolls:
        if producer == "gather":
            mocks = _gather_mocks(player=player)
            mocks[2].get_location_terrain = terrain_read
            result = await gather_run(ctx, mocks)
        elif producer == "travel":
            mocks = _travel_mocks()
            mocks.queries.get_player.return_value = player
            mocks.content.get_location.return_value = {"id": "dest", "navigation": "dense_forest", "terrain": "city"}
            mocks.content.get_location_terrain = terrain_read
            result = await travel_run(ctx, mocks)
            terrain_read.assert_awaited_once_with("forest_here")
        else:
            state, source, _ = setup()
            source.creature_id = "hollow_choir"
            actor = state.participants[0]
            state.location_id, state.terrain = "combat_forest", "forest"
            choir_encounter.initialize(state)
            assert state.choir_encounter is not None
            state.choir_encounter["aura_receipts"][actor.id] = state.round_number
            packet = SimpleNamespace(
                actor_id=actor.id,
                declaration=Declaration(
                    type=DeclarationType.INTERACT, action="choir_search_perception", target_id="choir_sound"
                ),
            )
            dependencies = deps()
            dependencies["queries"].get_player = AsyncMock(return_value=player)
            result = await _resolve_one_packet(ctx.userdata, state, packet, **dependencies)
            terrain_read.assert_not_awaited()
    assert (result["roll"], rolls.call_count, result.get("gift_name")) == (18, 2, "Nature's Pulse")


@pytest.mark.asyncio
@pytest.mark.parametrize("hearing_only,difficulty", [(True, "moderate"), (False, "legendary")])
async def test_no_roll_failures_do_not_apply_gift(world, hearing_only, difficulty):
    ctx, player, _, _ = world
    player["conditions"] = apply_condition([], "deafened") if hearing_only else []
    result, count = await skill_roll(ctx, difficulty=difficulty, hearing_only=hearing_only)
    assert result["roll"] == 0 and count == 0
    assert "gift_name" not in result
