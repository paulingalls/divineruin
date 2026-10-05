import dataclasses
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from sample_fixtures import (
    _WARRIOR_MILESTONES,
    GUILD_PLAYER,
    _milestones_mod_for,
    make_db_mod,
)

import event_types as E
from leveling import build_level_up_payload_for_archetype, get_level_up_rewards
from milestones import Milestone
from progression_tools import (
    AwardXpResult,
    _award_divine_favor_core,
    _award_xp_core,
)


async def _award_crossing_threshold(player):
    """Award 100 XP to a level-1 player at xp 250, crossing into level 2, and return the
    LEVEL_UP payload the Resolve buffers for the caller to release post-commit."""
    _, mock_conn = make_db_mod()
    mutations = MagicMock()
    mutations.update_player_xp = AsyncMock()
    mutations.set_player_flag = AsyncMock()
    pending_events: list[tuple[str, dict]] = []
    await _award_xp_core(
        player_id="player_1",
        player={**player, "xp": 250},
        amount=100,
        reason="quest done",
        conn=mock_conn,
        pending_events=pending_events,
        mutations=mutations,
    )
    return next((p for et, p in pending_events if et == E.LEVEL_UP), None)


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


@pytest.mark.asyncio
async def test_l10_auto_grant_sets_extra_attack_flag_in_code():
    _, mutations, conn, _ = await _core_for_levels(from_level=9, from_xp=2900, amount=550)
    mutations.set_player_flag.assert_awaited_once_with("player_1", "extra_attack", True, conn=conn)


@pytest.mark.asyncio
async def test_multi_level_jump_still_applies_crossed_auto_grant():
    _, mutations, conn, _ = await _core_for_levels(from_level=9, from_xp=2900, amount=1150)
    mutations.set_player_flag.assert_awaited_once_with("player_1", "extra_attack", True, conn=conn)


@pytest.mark.asyncio
async def test_narrative_only_grant_writes_no_flag():
    _, mutations, _, _ = await _core_for_levels(from_level=14, from_xp=6000, amount=750)
    mutations.set_player_flag.assert_not_awaited()


@pytest.mark.asyncio
async def test_auto_grant_surfaces_narration_in_response():
    _, _, _, result = await _core_for_levels(from_level=9, from_xp=2900, amount=550)
    assert result.milestone_grants == [
        {"name": "Extra Attack", "effect": "Your blade strikes twice.", "narration_cue": "cue"}
    ]


@pytest.mark.asyncio
async def test_narrative_only_grant_is_still_surfaced_for_voicing():
    _, _, _, result = await _core_for_levels(from_level=14, from_xp=6000, amount=750)
    assert result.milestone_grants == [
        {"name": "Indomitable", "effect": "Reroll a failed save.", "narration_cue": "cue"}
    ]


@pytest.mark.asyncio
async def test_no_milestone_crossed_surfaces_empty_grants():
    _, _, _, result = await _core_for_levels(from_level=1, from_xp=250, amount=100, archetype="artificer")
    assert result.milestone_grants == []


@pytest.mark.asyncio
async def test_l5_fork_surfaced_in_response_for_dm_cue():
    _, _, _, result = await _core_for_levels(from_level=4, from_xp=750, amount=300)
    assert result.result.specialization_fork is True


# Patron-deferred L5 fork (Oracle/Cleric/Paladin) — `select` rejects these pending Phase 8,
# so the core must not present a choice it cannot resolve.
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
    pending_events: list[tuple[str, dict]] = []
    result = await _award_xp_core(
        player_id="player_1",
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


def test_core_result_carries_exactly_its_read_fields():
    """Selection rederives the fork under the row lock rather than trusting handoff state."""
    assert {f.name for f in dataclasses.fields(AwardXpResult)} == {"result", "milestone_grants"}


@pytest.mark.asyncio
async def test_core_l5_fork_emits_specialization_choice_event():
    # The HUD overlay consumes SPECIALIZATION_CHOICE {milestone_id, options} (unchanged
    # from resolve_milestone's payload) — the core publishes it on the level-up path.
    # player_id is the RECIPIENT (story-001): a party member's fork must reach only their
    # own client, so every payload the core emits carries whose award it is.
    pending_events, _, _, _ = await _core_for_levels(from_level=4, from_xp=750, amount=300)
    assert (
        E.SPECIALIZATION_CHOICE,
        {
            "milestone_id": "warrior_identity",
            "options": [
                {"id": "battle_master", "name": "Battle Master", "description": "Tactical maneuvers."},
                {"id": "berserker", "name": "Berserker", "description": "Reckless fury."},
            ],
            "player_id": "player_1",
        },
    ) in pending_events


@pytest.mark.asyncio
async def test_core_l5_fork_persists_nothing():
    _, mutations, _, _ = await _core_for_levels(from_level=4, from_xp=750, amount=300)
    mutations.set_player_flag.assert_not_awaited()


@pytest.mark.asyncio
async def test_core_l5_fork_still_emits_xp_awarded_and_level_up():
    pending_events, _, _, _ = await _core_for_levels(from_level=4, from_xp=750, amount=300)
    types = _event_types(pending_events)
    assert E.XP_AWARDED in types
    assert E.LEVEL_UP in types
    assert types.index(E.SPECIALIZATION_CHOICE) > types.index(E.LEVEL_UP)


@pytest.mark.asyncio
async def test_core_non_fork_levelup_surfaces_no_fork():
    pending_events, _, _, result = await _core_for_levels(from_level=9, from_xp=2900, amount=550)
    assert result.result.specialization_fork is False
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
    # The level-based fork flag IS set (L5 was crossed) — proving the absence below is the
    # patron deferral doing its job, not a level-up that never happened.
    assert result.result.specialization_fork is True
    assert E.SPECIALIZATION_CHOICE not in _event_types(pending_events)


@pytest.mark.asyncio
async def test_core_multilevel_jump_crossing_l5_surfaces_exactly_one_choice():
    pending_events, mutations, conn, _ = await _core_for_levels(from_level=4, from_xp=750, amount=5000)
    forks = [p for et, p in pending_events if et == E.SPECIALIZATION_CHOICE]
    assert len(forks) == 1
    assert forks[0]["milestone_id"] == "warrior_identity"
    mutations.set_player_flag.assert_awaited_once_with("player_1", "extra_attack", True, conn=conn)


@pytest.mark.asyncio
async def test_core_writes_the_new_xp_total():
    _, mutations, conn, result = await _core_for_levels(from_level=1, from_xp=0, amount=50)
    assert result.result.new_xp == 50
    assert result.result.leveled_up is False
    mutations.update_player_xp.assert_awaited_once_with("player_1", 50, 1, conn=conn)


@pytest.mark.asyncio
async def test_core_buffers_xp_awarded_with_the_recipient_stamp():
    # The Resolve BUFFERS rather than publishes — the caller releases post-commit, so a
    # rolled-back stage never announces XP the database does not hold. The recipient stamp
    # rides every payload (story-001): party-wide XP means each client filters on player_id.
    # Symmetric partner of test_favor_core_buffers_its_event_rather_than_publishing.
    pending_events, _, _, _ = await _core_for_levels(from_level=1, from_xp=0, amount=50)
    xp_events = [p for et, p in pending_events if et == E.XP_AWARDED]
    assert len(xp_events) == 1
    assert xp_events[0]["amount"] == 50
    assert xp_events[0]["player_id"] == "player_1"


@pytest.mark.asyncio
async def test_core_at_max_level_grants_xp_without_leveling():
    pending_events, _, _, result = await _core_for_levels(from_level=20, from_xp=355000, amount=1000)
    assert result.result.new_level == 20
    assert result.result.leveled_up is False
    assert result.result.new_xp == 356000
    assert E.LEVEL_UP not in _event_types(pending_events)


_FAVOR = {"patron": "kaelen", "level": 10, "max": 100, "last_whisper_level": 4}


def _favor_mods(favor):
    """(activities, mutations) doubles returning `favor` from get_divine_favor."""
    activities = MagicMock()
    activities.get_divine_favor = AsyncMock(return_value=favor)
    mutations = MagicMock()
    mutations.update_divine_favor = AsyncMock()
    return activities, mutations


@pytest.mark.asyncio
async def test_favor_core_writes_in_the_callers_transaction():
    """The caller's conn is used directly — the core never opens a transaction of its own,
    which is what lets a quest grant XP and favor atomically."""
    activities, mutations = _favor_mods(_FAVOR)
    conn = MagicMock()
    pending: list[tuple[str, dict]] = []

    grant = await _award_divine_favor_core(
        player_id="player_1",
        amount=5,
        reason="honored Kaelen",
        conn=conn,
        pending_events=pending,
        mutations=mutations,
        activities=activities,
    )

    assert grant is not None
    assert (grant.previous_level, grant.new_level, grant.patron_id) == (10, 15, "kaelen")
    mutations.update_divine_favor.assert_awaited_once()
    assert mutations.update_divine_favor.call_args.args == ("player_1", 15)
    assert mutations.update_divine_favor.call_args.kwargs["conn"] is conn
    assert datetime.fromisoformat(mutations.update_divine_favor.call_args.kwargs["last_served_at"]).tzinfo


@pytest.mark.asyncio
async def test_favor_core_buffers_its_event_rather_than_publishing():
    """Buffered, not published: the caller releases it post-commit, so a rolled-back
    transaction never announces favor the DB does not hold."""
    activities, mutations = _favor_mods(_FAVOR)
    pending: list[tuple[str, dict]] = []

    await _award_divine_favor_core(
        player_id="player_1",
        amount=5,
        reason="honored Kaelen",
        conn=MagicMock(),
        pending_events=pending,
        mutations=mutations,
        activities=activities,
    )

    assert [t for t, _ in pending] == [E.DIVINE_FAVOR_CHANGED]
    payload = pending[0][1]
    assert payload["new_level"] == 15
    assert payload["previous_level"] == 10
    assert payload["patron_id"] == "kaelen"
    assert payload["amount"] == 5
    assert payload["reason"] == "honored Kaelen"
    assert payload["last_whisper_level"] == 4


@pytest.mark.asyncio
async def test_favor_core_clamps_at_the_patrons_max():
    activities, mutations = _favor_mods({**_FAVOR, "level": 95})
    conn = MagicMock()
    pending: list[tuple[str, dict]] = []

    grant = await _award_divine_favor_core(
        player_id="player_1",
        amount=10,
        reason="great deed",
        conn=conn,
        pending_events=pending,
        mutations=mutations,
        activities=activities,
    )

    assert grant is not None and grant.new_level == 100
    mutations.update_divine_favor.assert_awaited_once()
    assert mutations.update_divine_favor.call_args.args == ("player_1", 100)
    assert mutations.update_divine_favor.call_args.kwargs["conn"] is conn
    assert datetime.fromisoformat(mutations.update_divine_favor.call_args.kwargs["last_served_at"]).tzinfo
    assert pending[0][1]["new_level"] == 100
    # The HUD toast reads `amount` alone. A clamped grant must publish what the bar ACTUALLY
    # moved (5), never the 10 that was asked for, or the player watches a "+10" over a bar
    # that moved half as far — and at the cap, over one that never moved at all.
    assert pending[0][1]["amount"] == 5


@pytest.mark.asyncio
async def test_favor_core_publishes_zero_amount_at_the_cap():
    """At max favor the toast must not fire: the mobile handler suppresses the overlay on
    amount <= 0, and this is the only field that tells it nothing happened."""
    activities, mutations = _favor_mods({**_FAVOR, "level": 100})
    pending: list[tuple[str, dict]] = []

    grant = await _award_divine_favor_core(
        player_id="player_1",
        amount=5,
        reason="great deed",
        conn=MagicMock(),
        pending_events=pending,
        mutations=mutations,
        activities=activities,
    )

    assert grant is not None and grant.new_level == 100
    assert pending[0][1]["amount"] == 0


@pytest.mark.asyncio
async def test_favor_core_returns_none_for_a_patronless_player():
    """None, not an exception: a party member without a patron must be SKIPPED by a quest
    grant, not abort the whole stage transaction. Every caller handles the None itself."""
    activities, mutations = _favor_mods({"patron": "none", "level": 0, "max": 100, "last_whisper_level": 0})
    pending: list[tuple[str, dict]] = []

    grant = await _award_divine_favor_core(
        player_id="player_1",
        amount=5,
        reason="test",
        conn=MagicMock(),
        pending_events=pending,
        mutations=mutations,
        activities=activities,
    )

    assert grant is None
    assert pending == []
    mutations.update_divine_favor.assert_not_awaited()


@pytest.mark.asyncio
async def test_favor_core_returns_none_when_the_player_has_no_favor_row():
    activities, mutations = _favor_mods(None)
    pending: list[tuple[str, dict]] = []

    grant = await _award_divine_favor_core(
        player_id="player_1",
        amount=5,
        reason="test",
        conn=MagicMock(),
        pending_events=pending,
        mutations=mutations,
        activities=activities,
    )

    assert grant is None
    assert pending == []
    mutations.update_divine_favor.assert_not_awaited()
