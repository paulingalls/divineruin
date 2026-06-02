"""LEVEL_UP payload tests for award_xp — archetype-aware hp_gains + auto-grant side-effects."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from sample_fixtures import GUILD_PLAYER, level_up_payload, make_context, make_db_mod, make_mock_room

from leveling import build_level_up_payload_for_archetype, get_level_up_rewards
from milestones import Grant, Milestone
from progression_tools import _award_xp_impl


async def _award_crossing_threshold(player):
    """Award 100 XP to a level-1 player at xp 250, crossing into level 2,
    and return the published LEVEL_UP payload."""
    room = make_mock_room()
    mock_db, _ = make_db_mod()
    queries = MagicMock()
    queries.get_player = AsyncMock(return_value={**player, "xp": 250})
    mutations = MagicMock()
    mutations.update_player_xp = AsyncMock()
    ctx = make_context(room=room)
    await _award_xp_impl(ctx, 100, "quest done", db_mod=mock_db, mutations=mutations, queries=queries)
    return level_up_payload(room)


@pytest.mark.asyncio
async def test_level_up_payload_carries_archetype_hp_gains():
    player = {**GUILD_PLAYER, "class": "artificer", "attributes": {**GUILD_PLAYER["attributes"], "constitution": 14}}
    payload = await _award_crossing_threshold(player)

    expected = build_level_up_payload_for_archetype(1, get_level_up_rewards(1, 2), "artificer", con_mod=2)
    assert payload is not None
    assert payload["hp_gains"] == expected["hp_gains"]


@pytest.mark.asyncio
async def test_level_up_payload_zero_con_mod_still_carries_hp_gains():
    player = {**GUILD_PLAYER, "class": "artificer", "attributes": {**GUILD_PLAYER["attributes"], "constitution": 10}}
    payload = await _award_crossing_threshold(player)

    expected = build_level_up_payload_for_archetype(1, get_level_up_rewards(1, 2), "artificer", con_mod=0)
    assert payload is not None
    assert "hp_gains" in payload
    assert payload["hp_gains"] == expected["hp_gains"]


@pytest.mark.asyncio
async def test_level_up_hp_gains_resolve_from_chassis_for_diverging_archetype():
    # AC#3: progression resolves HP from the chassis accessor. Warrior's hp_base
    # (12) diverges from its legacy hit_die (10), so this pins the level-up path
    # to the chassis SSOT (calculate_max_hp), not any ClassData copy.
    from hp_scaling import calculate_max_hp

    player = {**GUILD_PLAYER, "class": "warrior", "attributes": {**GUILD_PLAYER["attributes"], "constitution": 10}}
    payload = await _award_crossing_threshold(player)

    assert payload is not None
    expected_gain = calculate_max_hp("warrior", 2, 0) - calculate_max_hp("warrior", 1, 0)
    assert payload["hp_gains"] == [{"level": 2, "hp_gain": expected_gain}]


# --- Auto-grant side-effects: L10/15/20 milestone grants resolve in award_xp (story-007) ---

# Warrior milestone ladder stub (mirrors content/archetype_milestones.json shapes):
# L5 fork (no auto-grant), L10 auto-grant with the extra_attack flag, L15/L20 narrative-only.
_WARRIOR_MILESTONES = [
    Milestone("warrior_identity", "warrior", "identity", 5, "specialization_fork", False, (), None, "cue"),
    Milestone(
        "warrior_power",
        "warrior",
        "power",
        10,
        "auto_grant",
        False,
        (),
        Grant("Extra Attack", "Your blade strikes twice.", "extra_attack"),
        "cue",
    ),
    Milestone(
        "warrior_mastery",
        "warrior",
        "mastery",
        15,
        "auto_grant",
        False,
        (),
        Grant("Indomitable", "Reroll a failed save.", None),
        "cue",
    ),
    Milestone(
        "warrior_legend",
        "warrior",
        "legend",
        20,
        "auto_grant",
        False,
        (),
        Grant("Legendary Action", "Act outside the turn order.", None),
        "cue",
    ),
]


def _milestones_mod():
    mod = MagicMock()
    by_level = {m.level: m for m in _WARRIOR_MILESTONES}
    mod.get_milestone_by_level = MagicMock(
        side_effect=lambda archetype_id, level: by_level.get(level) if archetype_id == "warrior" else None
    )
    return mod


async def _award_levels(from_level: int, from_xp: int, amount: int):
    """Award `amount` XP to a warrior at (from_level, from_xp); return the mutations mock + conn."""
    room = make_mock_room()
    mock_db, mock_conn = make_db_mod()
    queries = MagicMock()
    queries.get_player = AsyncMock(
        return_value={**GUILD_PLAYER, "class": "warrior", "level": from_level, "xp": from_xp}
    )
    mutations = MagicMock()
    mutations.update_player_xp = AsyncMock()
    mutations.set_player_flag = AsyncMock()
    ctx = make_context(room=room)
    await _award_xp_impl(
        ctx,
        amount,
        "milestone reached",
        db_mod=mock_db,
        mutations=mutations,
        queries=queries,
        milestones_mod=_milestones_mod(),
    )
    return mutations, mock_conn


@pytest.mark.asyncio
async def test_l10_auto_grant_sets_extra_attack_flag_in_code():
    # L9 (2900 xp) -> L10 (3450) crosses warrior_power: the extra_attack flag is set
    # deterministically in award_xp, with no LLM resolve_milestone call.
    mutations, conn = await _award_levels(from_level=9, from_xp=2900, amount=550)
    mutations.set_player_flag.assert_awaited_once_with("player_1", "extra_attack", True, conn=conn)


@pytest.mark.asyncio
async def test_multi_level_jump_still_applies_crossed_auto_grant():
    # L9 (2900) -> L11 (4050) jumps two levels, crossing L10 — the grant still fires.
    mutations, conn = await _award_levels(from_level=9, from_xp=2900, amount=1150)
    mutations.set_player_flag.assert_awaited_once_with("player_1", "extra_attack", True, conn=conn)


@pytest.mark.asyncio
async def test_narrative_only_grant_writes_no_flag():
    # L14 (6000) -> L15 (6750): warrior_mastery is narrative-only (flag=None) — no flag write.
    mutations, _ = await _award_levels(from_level=14, from_xp=6000, amount=750)
    mutations.set_player_flag.assert_not_awaited()


@pytest.mark.asyncio
async def test_l5_specialization_fork_awards_no_auto_grant():
    # L4 (750) -> L5 (1050): the L5 fork needs a player choice — award_xp applies no auto-grant.
    mutations, _ = await _award_levels(from_level=4, from_xp=750, amount=300)
    mutations.set_player_flag.assert_not_awaited()
