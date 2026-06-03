"""LEVEL_UP payload tests for award_xp — archetype-aware hp_gains + auto-grant side-effects."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from sample_fixtures import GUILD_PLAYER, level_up_payload, make_context, make_db_mod, make_mock_room

import event_types as E
from leveling import build_level_up_payload_for_archetype, get_level_up_rewards
from milestones import Grant, Milestone, SpecializationOption
from progression_tools import AwardXpResult, PendingChoice, _award_xp_core, _award_xp_impl


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

_FORK_OPTIONS = (
    SpecializationOption("battle_master", "Battle Master", "Tactical maneuvers."),
    SpecializationOption("berserker", "Berserker", "Reckless fury."),
)

# Warrior milestone ladder stub (mirrors content/archetype_milestones.json shapes):
# L5 fork with populated options (the fork-present path), L10 auto-grant with the
# extra_attack flag, L15/L20 narrative-only.
_WARRIOR_MILESTONES = [
    Milestone("warrior_identity", "warrior", "identity", 5, "specialization_fork", False, _FORK_OPTIONS, None, "cue"),
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


def _milestones_mod_for(ladder, archetype_id):
    mod = MagicMock()
    by_level = {m.level: m for m in ladder}
    mod.get_milestone_by_level = MagicMock(
        side_effect=lambda aid, level: by_level.get(level) if aid == archetype_id else None
    )
    return mod


def _milestones_mod():
    return _milestones_mod_for(_WARRIOR_MILESTONES, "warrior")


async def _award_levels(from_level: int, from_xp: int, amount: int):
    """Award `amount` XP to a warrior at (from_level, from_xp); return (mutations, conn, response)."""
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
    raw = await _award_xp_impl(
        ctx,
        amount,
        "milestone reached",
        db_mod=mock_db,
        mutations=mutations,
        queries=queries,
        milestones_mod=_milestones_mod(),
    )
    return mutations, mock_conn, json.loads(raw)


@pytest.mark.asyncio
async def test_l10_auto_grant_sets_extra_attack_flag_in_code():
    # L9 (2900 xp) -> L10 (3450) crosses warrior_power: the extra_attack flag is set
    # deterministically in award_xp, with no LLM resolve_milestone call.
    mutations, conn, _ = await _award_levels(from_level=9, from_xp=2900, amount=550)
    mutations.set_player_flag.assert_awaited_once_with("player_1", "extra_attack", True, conn=conn)


@pytest.mark.asyncio
async def test_multi_level_jump_still_applies_crossed_auto_grant():
    # L9 (2900) -> L11 (4050) jumps two levels, crossing L10 — the grant still fires.
    mutations, conn, _ = await _award_levels(from_level=9, from_xp=2900, amount=1150)
    mutations.set_player_flag.assert_awaited_once_with("player_1", "extra_attack", True, conn=conn)


@pytest.mark.asyncio
async def test_narrative_only_grant_writes_no_flag():
    # L14 (6000) -> L15 (6750): warrior_mastery is narrative-only (flag=None) — no flag write.
    mutations, _, _ = await _award_levels(from_level=14, from_xp=6000, amount=750)
    mutations.set_player_flag.assert_not_awaited()


@pytest.mark.asyncio
async def test_l5_specialization_fork_awards_no_auto_grant():
    # L4 (750) -> L5 (1050): the L5 fork needs a player choice — award_xp applies no auto-grant.
    mutations, _, _ = await _award_levels(from_level=4, from_xp=750, amount=300)
    mutations.set_player_flag.assert_not_awaited()


@pytest.mark.asyncio
async def test_auto_grant_surfaces_narration_in_response():
    # The DM voices the grant: award_xp's response carries the crossed auto-grant's name +
    # narration cue (concern 4bf3efecdc8a — the cue is no longer returned via resolve_milestone).
    _, _, response = await _award_levels(from_level=9, from_xp=2900, amount=550)
    assert response["milestone_grants"] == [
        {"name": "Extra Attack", "effect": "Your blade strikes twice.", "narration_cue": "cue"}
    ]


@pytest.mark.asyncio
async def test_narrative_only_grant_is_still_surfaced_for_voicing():
    # L14 -> L15: even though warrior_mastery sets no flag, its narration must reach the DM.
    _, _, response = await _award_levels(from_level=14, from_xp=6000, amount=750)
    assert response["milestone_grants"] == [
        {"name": "Indomitable", "effect": "Reroll a failed save.", "narration_cue": "cue"}
    ]


@pytest.mark.asyncio
async def test_no_milestone_crossed_surfaces_empty_grants():
    # L1 -> L2 crosses no auto-grant milestone — milestone_grants is an empty list.
    player = {**GUILD_PLAYER, "class": "artificer"}
    room = make_mock_room()
    mock_db, _ = make_db_mod()
    queries = MagicMock()
    queries.get_player = AsyncMock(return_value={**player, "xp": 250})
    mutations = MagicMock()
    mutations.update_player_xp = AsyncMock()
    mutations.set_player_flag = AsyncMock()
    ctx = make_context(room=room)
    raw = await _award_xp_impl(
        ctx, 100, "quest done", db_mod=mock_db, mutations=mutations, queries=queries, milestones_mod=_milestones_mod()
    )
    assert json.loads(raw)["milestone_grants"] == []


@pytest.mark.asyncio
async def test_l5_fork_surfaced_in_response_for_dm_cue():
    # Crossing into L5 must cue the DM to present the specialization fork in award_xp's
    # response (concern c515f47bf2c5) — symmetric to milestone_grants for auto-grant tiers.
    _, _, response = await _award_levels(from_level=4, from_xp=750, amount=300)
    assert response["specialization_fork"] is True


@pytest.mark.asyncio
async def test_non_l5_levelup_has_no_fork_cue():
    # L9 -> L10 crosses no specialization fork — the cue is False.
    _, _, response = await _award_levels(from_level=9, from_xp=2900, amount=550)
    assert response["specialization_fork"] is False


# --- _award_xp_core primitive (story-001): the shared XP/grant Resolve award_xp,
# update_quest (story-002), and select (story-003) route through. Refactor-mode:
# the wrapper tests above cover the preserved award_xp path; these reach the new
# primitive directly — including the L5-fork presentation that moved off
# resolve_milestone onto the level-up path. ---

# Patron-deferred L5 fork (Oracle/Cleric/Paladin) — resolve_milestone rejects these
# pending Phase 8, so the core must not present a choice it cannot resolve.
_PATRON_FORK_MILESTONES = [
    Milestone("oracle_identity", "oracle", "identity", 5, "specialization_fork", True, (), None, "cue"),
]


async def _core_for_levels(from_level, from_xp, amount, *, archetype="warrior", ladder=None):
    """Drive _award_xp_core directly on a caller-supplied conn; return
    (pending_events, mutations, conn, result)."""
    _, mock_conn = make_db_mod()
    player = {**GUILD_PLAYER, "class": archetype, "level": from_level, "xp": from_xp}
    mutations = MagicMock()
    mutations.update_player_xp = AsyncMock()
    mutations.set_player_flag = AsyncMock()
    session = make_context(room=make_mock_room()).userdata
    pending_events: list[tuple[str, dict]] = []
    result = await _award_xp_core(
        session=session,
        player=player,
        amount=amount,
        reason="milestone reached",
        conn=mock_conn,
        pending_events=pending_events,
        mutations=mutations,
        milestones_mod=_milestones_mod_for(ladder or _WARRIOR_MILESTONES, archetype),
    )
    return pending_events, mutations, mock_conn, result


def _event_types(pending_events):
    return [et for et, _ in pending_events]


@pytest.mark.asyncio
async def test_core_l5_fork_surfaces_pending_choice():
    # L4 (750) -> L5 (1050): the core surfaces the pending L5 choice with its options,
    # keyed by the milestone id the select verb will resolve against.
    _, _, _, result = await _core_for_levels(from_level=4, from_xp=750, amount=300)
    assert isinstance(result, AwardXpResult)
    assert isinstance(result.pending_choice, PendingChoice)
    assert result.pending_choice.choice_id == "warrior_identity"
    assert result.pending_choice.options == [
        {"id": "battle_master", "name": "Battle Master", "description": "Tactical maneuvers."},
        {"id": "berserker", "name": "Berserker", "description": "Reckless fury."},
    ]


@pytest.mark.asyncio
async def test_core_l5_fork_emits_specialization_choice_event():
    # The HUD overlay consumes SPECIALIZATION_CHOICE {milestone_id, options} (unchanged
    # from resolve_milestone's payload) — the core publishes it on the level-up path.
    pending_events, _, _, _ = await _core_for_levels(from_level=4, from_xp=750, amount=300)
    assert (
        E.SPECIALIZATION_CHOICE,
        {
            "milestone_id": "warrior_identity",
            "options": [
                {"id": "battle_master", "name": "Battle Master", "description": "Tactical maneuvers."},
                {"id": "berserker", "name": "Berserker", "description": "Reckless fury."},
            ],
        },
    ) in pending_events


@pytest.mark.asyncio
async def test_core_l5_fork_persists_nothing():
    # Presenting the fork writes no state — the choice stays unresolved until select
    # round-trips it (no flag write, no specialization persisted by the core).
    _, mutations, _, _ = await _core_for_levels(from_level=4, from_xp=750, amount=300)
    mutations.set_player_flag.assert_not_awaited()


@pytest.mark.asyncio
async def test_core_l5_fork_still_emits_xp_awarded_and_level_up():
    # The fork event is additive — XP_AWARDED and LEVEL_UP still fire, and the
    # SPECIALIZATION_CHOICE cue is ordered after LEVEL_UP.
    pending_events, _, _, _ = await _core_for_levels(from_level=4, from_xp=750, amount=300)
    types = _event_types(pending_events)
    assert E.XP_AWARDED in types
    assert E.LEVEL_UP in types
    assert types.index(E.SPECIALIZATION_CHOICE) > types.index(E.LEVEL_UP)


@pytest.mark.asyncio
async def test_core_non_fork_levelup_has_no_pending_choice():
    # L9 (2900) -> L10 (3450) crosses the auto-grant tier, not a fork — no pending choice,
    # no SPECIALIZATION_CHOICE event.
    pending_events, _, _, result = await _core_for_levels(from_level=9, from_xp=2900, amount=550)
    assert result.pending_choice is None
    assert E.SPECIALIZATION_CHOICE not in _event_types(pending_events)


@pytest.mark.asyncio
async def test_core_runs_in_caller_conn():
    # The core is a transaction participant — it mutates on the passed conn and never
    # opens its own (it has no db_mod to open one with).
    _, mutations, conn, _ = await _core_for_levels(from_level=9, from_xp=2900, amount=550)
    mutations.update_player_xp.assert_awaited_once()
    assert mutations.update_player_xp.await_args.kwargs["conn"] is conn
    mutations.set_player_flag.assert_awaited_once_with("player_1", "extra_attack", True, conn=conn)


@pytest.mark.asyncio
async def test_core_patron_deferred_fork_surfaces_no_choice():
    # An Oracle's L5 fork is patron-driven (Phase 8) — the core cannot present a choice
    # it cannot resolve, so no pending choice and no SPECIALIZATION_CHOICE event.
    pending_events, _, _, result = await _core_for_levels(
        from_level=4, from_xp=750, amount=300, archetype="oracle", ladder=_PATRON_FORK_MILESTONES
    )
    assert result.pending_choice is None
    assert E.SPECIALIZATION_CHOICE not in _event_types(pending_events)


@pytest.mark.asyncio
async def test_core_multilevel_jump_crossing_l5_surfaces_exactly_one_choice():
    # A jump from L4 spanning L5 and L10 surfaces the L5 fork exactly once AND fires the
    # L10 auto-grant — the "one choice per crossing" invariant holds across multi-level gains.
    pending_events, mutations, conn, result = await _core_for_levels(from_level=4, from_xp=750, amount=5000)
    assert result.pending_choice is not None
    assert result.pending_choice.choice_id == "warrior_identity"
    assert _event_types(pending_events).count(E.SPECIALIZATION_CHOICE) == 1
    mutations.set_player_flag.assert_awaited_once_with("player_1", "extra_attack", True, conn=conn)
