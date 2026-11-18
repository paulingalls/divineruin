"""Real quest/select boundaries for category, overflow and saved increase behavior."""

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import make_context, make_mock_room, published_payloads

import db
import db_mutations
import db_queries
import event_types as E
from choice_tools import _select_impl
from creation_rules import build_character_data
from quest_tools import _update_quest_impl
from rules_engine import XP_FOR_LEVEL
from session_data import CombatState

CATEGORIES = {
    "strength": ("warrior", "guardian", "skirmisher"),
    "intelligence": ("mage", "artificer", "seeker"),
    "wisdom": ("cleric", "paladin", "oracle", "druid", "beastcaller", "warden"),
    "dexterity": ("rogue", "spy", "whisper"),
    "charisma": ("bard", "diplomat", "marshal"),
}
CASES = [(archetype, attr) for attr, archetypes in CATEGORIES.items() for archetype in archetypes]


@pytest.fixture
async def character(dev_db_pool):
    pool = dev_db_pool
    pid = "increase_" + uuid4().hex
    quests = []
    ctx = make_context(pid, room=make_mock_room())

    async def seed(archetype="warrior", level=3, scores=None, **extra):
        row = build_character_data(
            "Increase", "human", archetype, None, "", created_at=datetime(2026, 11, 18, tzinfo=UTC)
        )
        row.update(level=level, xp=XP_FOR_LEVEL[level], **extra)
        if scores:
            row["attributes"].update(scores)
        await db_mutations.create_player(pid, None, row)
        return row

    async def award(level):
        row = await db_queries.get_player(pid)
        assert row is not None
        quest = "increase_quest_" + uuid4().hex
        quests.append(quest)
        data = {
            "name": "Increase",
            "stages": [{"objective": "Finish", "on_complete": {"xp": max(1, XP_FOR_LEVEL[level] - row["xp"])}}],
        }
        await pool.execute("INSERT INTO quests(id,data) VALUES($1,$2::jsonb)", quest, json.dumps(data))
        await db_mutations.set_player_quest(pid, quest, {"current_stage": 0, "status": "active"})
        result = json.loads(await _update_quest_impl(ctx, quest, 1))
        updated = await db_queries.get_player(pid)
        assert updated is not None
        return updated, result

    yield ctx, seed, award
    await pool.execute("DELETE FROM players WHERE player_id=$1", pid)
    for quest in quests:
        await pool.execute("DELETE FROM quests WHERE id=$1", quest)


@pytest.mark.parametrize("archetype,attribute", CASES)
async def test_category_first_all_archetypes(character, archetype, attribute):
    assert len(CASES) == len({case[0] for case in CASES}) == 18
    _, seed, award = character
    before = await seed(archetype)
    row, result = await award(4)
    assert row["attributes"] == {**before["attributes"], attribute: before["attributes"][attribute] + 2}
    assert row["attribute_increases"] == {"4": {"allocation": {attribute: 2}, "locked": False}}
    assert result["attribute_increases"][0]["player_id"] == character[0].userdata.player_id


@pytest.mark.parametrize(
    "scores,allocation",
    [
        ({"strength": 19}, {"strength": 1, "constitution": 1}),
        ({"strength": 20}, {"constitution": 2}),
        ({"strength": 20, "constitution": 20, "dexterity": 19}, {"dexterity": 1, "wisdom": 1}),
    ],
)
async def test_cap_overflow(character, scores, allocation):
    _, seed, award = character
    before = await seed(scores=scores)
    row, _ = await award(4)
    assert row["attribute_increases"]["4"]["allocation"] == allocation
    assert sum(row["attributes"].values()) == sum(before["attributes"].values()) + 2
    assert max(row["attributes"].values()) <= 20


async def test_two_thresholds_and_replacing_one_offer(character):
    ctx, seed, award = character
    await seed(scores={"strength": 19})
    row, result = await award(8)
    assert row["attributes"]["strength"] == 20 and row["attributes"]["constitution"] == 18
    assert [r["level"] for r in result["attribute_increases"]] == [4, 8]
    packet = next(e for e in published_payloads(ctx.userdata.room) if e["type"] == E.LEVEL_UP)
    assert packet["hp_gains"] == [
        {"level": level, "hp_gain": delta} for level, delta in zip(range(4, 9), (10, 7, 7, 7, 8), strict=True)
    ]
    assert row["hp"]["max"] == 65
    await _select_impl(ctx, "attribute_increase_4", "wisdom")
    redirected = await db_queries.get_player(ctx.userdata.player_id)
    assert redirected is not None
    assert redirected["attributes"]["strength"] == 19
    assert redirected["attributes"]["constitution"] == 17
    assert redirected["attribute_increases"]["8"] == row["attribute_increases"]["8"]
    await _select_impl(ctx, "attribute_increase_4", "wisdom")
    assert await db_queries.get_player(ctx.userdata.player_id) == redirected
    await _select_impl(ctx, "attribute_increase_4", "dexterity")
    replaced = await db_queries.get_player(ctx.userdata.player_id)
    assert replaced is not None and replaced["attributes"]["wisdom"] == 13


@pytest.mark.parametrize("level", [12, 16, 20])
async def test_later_threshold_preserves_locked_grant(character, level):
    _, seed, award = character
    saved = {"4": {"allocation": {"strength": 2}, "locked": True}}
    await seed(level=level - 1, attribute_increases=saved)
    row, _ = await award(level)
    assert row["attribute_increases"]["4"] == saved["4"]
    assert row["attribute_increases"][str(level)] == {"allocation": {"strength": 2}, "locked": False}


@pytest.mark.parametrize("level,target", [(3, 3), (4, 5), (20, 20)])
async def test_ordinary_awards_leave_attributes(character, level, target):
    _, seed, award = character
    before = await seed(level=level)
    row, result = await award(target)
    assert row["attributes"] == before["attributes"] and result["attribute_increases"] == []


@pytest.mark.parametrize(
    "choice,option,reason",
    [
        ("attribute_increase_4", "luck", "attribute"),
        ("attribute_increase_4", "dexterity", "20"),
        ("attribute_increase_8", "wisdom", "available"),
    ],
)
async def test_refusals_preserve_row_after_successful_offer(character, choice, option, reason):
    ctx, seed, award = character
    await seed(scores={"dexterity": 19})
    await award(4)
    await _select_impl(ctx, "attribute_increase_4", "wisdom")
    before = await db_queries.get_player(ctx.userdata.player_id)
    with pytest.raises(ToolError, match=reason):
        await _select_impl(ctx, choice, option)
    assert await db_queries.get_player(ctx.userdata.player_id) == before


async def test_combat_and_other_actor_refused(character):
    ctx, seed, award = character
    await seed()
    await award(4)
    before = await db_queries.get_player(ctx.userdata.player_id)
    assert before is not None
    ctx.userdata.combat_state = CombatState("increase_combat", [], [])
    with pytest.raises(ToolError, match="after the fight"):
        await _select_impl(ctx, "attribute_increase_4", "wisdom")
    assert await db_queries.get_player(ctx.userdata.player_id) == before
    ctx.userdata.combat_state = None
    other = ctx.userdata.player_id + "_other"
    await db_mutations.create_player(other, None, {**before, "attribute_increases": {}})
    try:
        with pytest.raises(ToolError, match="available"):
            await _select_impl(make_context(other, room=make_mock_room()), "attribute_increase_4", "wisdom")
        assert await db_queries.get_player(ctx.userdata.player_id) == before
    finally:
        await (await db.get_pool()).execute("DELETE FROM players WHERE player_id=$1", other)


@pytest.mark.parametrize("failure", ["capacity", "existing"])
async def test_unusable_grant_rolls_back_award(character, failure):
    ctx, seed, award = character
    before = await seed(
        **(
            {
                "scores": dict.fromkeys(
                    ("strength", "constitution", "dexterity", "wisdom", "charisma", "intelligence"), 20
                )
            }
            if failure == "capacity"
            else {"attribute_increases": {"4": {"allocation": {"wisdom": 2}, "locked": True}}}
        )
    )
    with pytest.raises(ValueError, match=r"capacity|already recorded"):
        await award(4)
    row = await db_queries.get_player(ctx.userdata.player_id)
    assert row is not None and row["attributes"] == before["attributes"] and row["level"] == 3


@pytest.mark.parametrize(
    "archetype,scores,hp,stamina,focus,ac",
    [
        ("mage", {}, 22, None, 16, 12),
        ("bard", {}, 21, 8, 11, 13),
        ("warrior", {"strength": 20}, 36, 15, None, 15),
        ("rogue", {}, 22, 16, None, 15),
    ],
)
async def test_stored_derived_values_no_refill(character, archetype, scores, hp, stamina, focus, ac):
    _, seed, award = character
    before = await seed(archetype, scores=scores)
    row, _ = await award(4)
    assert row["hp"] == {"current": before["hp"]["current"], "max": hp}
    assert row["ac"] == ac
    for name, maximum in (("stamina", stamina), ("focus", focus)):
        if maximum is None:
            assert name not in row
        else:
            assert row[name] == {"current": before[name]["current"], "max": maximum}


async def test_redirect_caps_current_preserves_override_and_other_data(character):
    ctx, seed, award = character
    await seed(scores={"strength": 20}, maxhp_override=4, flags={"kept": True})
    await award(4)
    pid = ctx.userdata.player_id
    await db_mutations.update_player_hp(pid, 40)
    await _select_impl(ctx, "attribute_increase_4", "wisdom")
    row = await db_queries.get_player(pid)
    assert row is not None
    assert row["hp"] == {"current": 36, "max": 32}
    assert row["stamina"]["max"] == 14
    assert row["maxhp_override"] == 4 and row["flags"]["kept"]
