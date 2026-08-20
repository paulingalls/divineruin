"""Tests for the generic select(choice_id, option) verb (M4 story-003).

select resolves a pending player choice; today the only choice is the L5
specialization fork (absorbed from resolve_milestone's with-choice path). It is
fail-loud at the boundary: every bad input raises ToolError before the single
persist, so a rejected call never partially mutates.

Since M28 story-008 the fork is PARTY-WIDE — _award_xp_core stamps the
SPECIALIZATION_CHOICE event with the recipient's player_id, so a non-primary
member gets their own fork. These tests pin that select writes the OWNER's row,
never the primary's by default."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import _WARRIOR_MILESTONES, make_context, make_db_mod

from choice_tools import _select_impl
from milestones import Milestone
from session_data import SpecializationTap

# Patron-driven fork (Cleric/Paladin) — `select` rejects these pending Phase 8.
_CLERIC_FORK = Milestone("cleric_identity", "cleric", "identity", 5, "specialization_fork", True, (), None, "cue")

_BY_ID = {m.id: m for m in _WARRIOR_MILESTONES} | {_CLERIC_FORK.id: _CLERIC_FORK}


def _player(player_id="player_1", class_="warrior", level=5, specialization=None):
    p = {"player_id": player_id, "class": class_, "level": level}
    if specialization is not None:
        p["specialization"] = specialization
    return p


def _milestones_mod(by_id):
    """A milestones-module mock whose get_milestone resolves by id and raises
    ValueError on an unknown id (matching milestones.get_milestone)."""
    mod = MagicMock()

    def _get(milestone_id):
        if milestone_id not in by_id:
            raise ValueError(f"Unknown milestone: {milestone_id!r}")
        return by_id[milestone_id]

    mod.get_milestone = MagicMock(side_effect=_get)
    return mod


def _make_mocks(*players, by_id=_BY_ID):
    """Mock modules for _select_impl. ``players`` are player dicts; a None entry is
    skipped, standing for a member with no ``players`` row (the batch helper simply
    omits an absent id from its map)."""
    mock_db, conn = make_db_mod()
    queries = MagicMock()
    queries.get_players_for_update = AsyncMock(return_value={p["player_id"]: p for p in players if p is not None})
    persistence = MagicMock()
    persistence.set_player_specialization = AsyncMock()
    return SimpleNamespace(
        db=mock_db, conn=conn, queries=queries, persistence=persistence, milestones_mod=_milestones_mod(by_id)
    )


async def _select(m, choice_id, option, ctx=None):
    return await _select_impl(
        ctx if ctx is not None else make_context(),
        choice_id,
        option,
        db_mod=m.db,
        queries_mod=m.queries,
        persistence_mod=m.persistence,
        milestones_mod=m.milestones_mod,
    )


def _persisted_ids(m):
    """Every player_id set_player_specialization was asked to write."""
    return [call.args[0] for call in m.persistence.set_player_specialization.await_args_list]


@pytest.mark.asyncio
async def test_happy_path_persists_and_returns():
    m = _make_mocks(_player(level=5))
    raw = await _select(m, "warrior_identity", "battle_master")
    assert json.loads(raw) == {
        "choice_id": "warrior_identity",
        "chosen": "battle_master",
        "player_id": "player_1",
        "narration_cue": "cue",
    }
    m.persistence.set_player_specialization.assert_awaited_once_with("player_1", "battle_master", conn=m.conn)


@pytest.mark.asyncio
async def test_threads_locked_transaction_conn():
    # Read + write share the FOR UPDATE-locked conn so the choice commits atomically.
    # The batch helper is unconditionally FOR UPDATE (and carries the repo's ORDER BY
    # player_id lock order), so there is no for_update flag to assert — assert the call.
    m = _make_mocks(_player(level=5))
    await _select(m, "warrior_identity", "battle_master")
    m.queries.get_players_for_update.assert_awaited_once_with(["player_1"], conn=m.conn)
    assert m.persistence.set_player_specialization.await_args.kwargs["conn"] is m.conn


@pytest.mark.asyncio
async def test_unknown_player_rejects():
    m = _make_mocks(None)
    with pytest.raises(ToolError, match="player"):
        await _select(m, "warrior_identity", "battle_master")
    m.persistence.set_player_specialization.assert_not_awaited()


@pytest.mark.asyncio
async def test_already_chosen_rejects_immutably():
    m = _make_mocks(_player(level=5, specialization="berserker"))
    with pytest.raises(ToolError, match="already"):
        await _select(m, "warrior_identity", "battle_master")
    m.persistence.set_player_specialization.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_option_rejects():
    m = _make_mocks(_player(level=5))
    with pytest.raises(ToolError, match="Invalid"):
        await _select(m, "warrior_identity", "duelist")
    m.persistence.set_player_specialization.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_choice_id_rejects():
    m = _make_mocks(_player(level=5))
    with pytest.raises(ToolError, match="Unknown"):
        await _select(m, "warrior_phantom", "battle_master")
    m.persistence.set_player_specialization.assert_not_awaited()


@pytest.mark.asyncio
async def test_wrong_archetype_rejects():
    # warrior_identity belongs to the warrior, not a guardian — reject.
    m = _make_mocks(_player(class_="guardian", level=5))
    with pytest.raises(ToolError):
        await _select(m, "warrior_identity", "battle_master")
    m.persistence.set_player_specialization.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_fork_choice_id_rejects():
    # warrior_power is an auto_grant tier, not a selectable fork.
    m = _make_mocks(_player(level=10))
    with pytest.raises(ToolError):
        await _select(m, "warrior_power", "battle_master")
    m.persistence.set_player_specialization.assert_not_awaited()


@pytest.mark.asyncio
async def test_patron_deferred_rejects():
    m = _make_mocks(_player(class_="cleric", level=5))
    with pytest.raises(ToolError, match="patron"):
        await _select(m, "cleric_identity", "battle_master")
    m.persistence.set_player_specialization.assert_not_awaited()


@pytest.mark.asyncio
async def test_level_too_low_rejects():
    # A pre-L5 player (stale/replayed tap) cannot lock in the L5 fork.
    m = _make_mocks(_player(level=3))
    with pytest.raises(ToolError):
        await _select(m, "warrior_identity", "battle_master")
    m.persistence.set_player_specialization.assert_not_awaited()


@pytest.mark.asyncio
async def test_blank_choice_id_rejects_before_io():
    m = _make_mocks(_player(level=5))
    with pytest.raises(ToolError, match="Invalid"):
        await _select(m, "", "battle_master")
    m.queries.get_players_for_update.assert_not_awaited()


@pytest.mark.asyncio
async def test_blank_option_rejects_before_io():
    m = _make_mocks(_player(level=5))
    with pytest.raises(ToolError, match="Invalid"):
        await _select(m, "warrior_identity", "")
    m.queries.get_players_for_update.assert_not_awaited()


# ---------------------------------------------------------------------------
# Party-wide ownership (M28 story-008)
# ---------------------------------------------------------------------------


def _party_ctx(*, tap=None):
    ctx = make_context(party_member_ids=["player_2"])
    if tap is not None:
        ctx.userdata.pending_specialization_tap = tap
    return ctx


@pytest.mark.asyncio
async def test_non_primary_owner_resolves_own_fork():
    # AC-1: the teammate crossed L5, the primary is a different archetype. The
    # teammate's own row is written and NOTHING names the primary.
    m = _make_mocks(
        _player("player_1", class_="guardian", level=5),
        _player("player_2", class_="warrior", level=5),
    )
    raw = await _select(m, "warrior_identity", "battle_master", ctx=_party_ctx())
    assert json.loads(raw)["player_id"] == "player_2"
    m.persistence.set_player_specialization.assert_awaited_once_with("player_2", "battle_master", conn=m.conn)
    assert "player_1" not in _persisted_ids(m)


@pytest.mark.asyncio
async def test_same_archetype_tie_without_ticket_refuses():
    # AC-2: primary and teammate are both L5 warriors with no specialization. Guessing
    # would irreversibly write one member's choice onto the other's write-once row, so
    # select refuses and writes nothing — naming the tied members.
    m = _make_mocks(
        _player("player_1", class_="warrior", level=5),
        _player("player_2", class_="warrior", level=5),
    )
    with pytest.raises(ToolError) as exc:
        await _select(m, "warrior_identity", "battle_master", ctx=_party_ctx())
    assert "player_1" in str(exc.value) and "player_2" in str(exc.value)
    m.persistence.set_player_specialization.assert_not_awaited()


@pytest.mark.asyncio
async def test_the_tie_message_names_members_not_ids():
    # The DM speaks this line aloud (Golden Rule 1), so it must carry names when the rows
    # have them. The test above pins the id fallback for rows that do not.
    m = _make_mocks(
        {**_player("player_1", class_="warrior", level=5), "name": "Bran"},
        {**_player("player_2", class_="warrior", level=5), "name": "Sera"},
    )
    with pytest.raises(ToolError) as exc:
        await _select(m, "warrior_identity", "battle_master", ctx=_party_ctx())
    assert "Bran" in str(exc.value) and "Sera" in str(exc.value)
    assert "player_1" not in str(exc.value)


@pytest.mark.asyncio
async def test_no_eligible_member_refuses_without_writing():
    # The 0-eligible fallback to session.player_id must reach the raise, never the write.
    # _fork_block_reason is the same predicate the scan just ran, so a primary that was not
    # eligible is guaranteed blocked here — the safety of the fallback is a tautology, and
    # this pins it against a future edit that splits the two apart.
    m = _make_mocks(
        _player("player_1", class_="warrior", level=5, specialization="berserker"),
        _player("player_2", class_="warrior", level=5, specialization="battle_master"),
    )
    with pytest.raises(ToolError, match="already"):
        await _select(m, "warrior_identity", "battle_master", ctx=_party_ctx())
    m.persistence.set_player_specialization.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_tap_landing_mid_transaction_neither_steals_nor_is_stolen():
    # _on_data_received is a synchronous LiveKit callback, so a second tap can land at any
    # await inside _select_impl. This call must resolve against the ticket it started with,
    # and must leave the newcomer's ticket intact for its own resolution.
    m = _make_mocks(
        _player("player_1", class_="warrior", level=5),
        _player("player_2", class_="warrior", level=5),
    )
    first = SpecializationTap("player_2", "warrior_identity", "battle_master")
    later = SpecializationTap("player_1", "warrior_identity", "battle_master")
    ctx = _party_ctx(tap=first)

    rows = {"player_1": _player("player_1", class_="warrior", level=5), "player_2": _player("player_2", level=5)}

    async def _swap_ticket_mid_await(_ids, **_kw):
        ctx.userdata.pending_specialization_tap = later
        return rows

    m.queries.get_players_for_update = AsyncMock(side_effect=_swap_ticket_mid_await)

    await _select(m, "warrior_identity", "battle_master", ctx=ctx)

    # Resolved for the ORIGINAL tapper, not whoever tapped during the transaction.
    m.persistence.set_player_specialization.assert_awaited_once_with("player_2", "battle_master", conn=m.conn)
    # And the newcomer's ticket survives — clearing it would silently degrade their own
    # resolution to the ambiguous sole-claimant scan.
    assert ctx.userdata.pending_specialization_tap is later


@pytest.mark.asyncio
async def test_matching_ticket_breaks_the_tie():
    # The same tie, but the tap recorded its verified sender — resolve for them, and
    # leave the primary untouched.
    m = _make_mocks(
        _player("player_1", class_="warrior", level=5),
        _player("player_2", class_="warrior", level=5),
    )
    ctx = _party_ctx(tap=SpecializationTap("player_2", "warrior_identity", "battle_master"))
    await _select(m, "warrior_identity", "battle_master", ctx=ctx)
    m.persistence.set_player_specialization.assert_awaited_once_with("player_2", "battle_master", conn=m.conn)
    assert "player_1" not in _persisted_ids(m)


@pytest.mark.asyncio
async def test_used_ticket_is_cleared_after_commit():
    m = _make_mocks(
        _player("player_1", class_="warrior", level=5),
        _player("player_2", class_="warrior", level=5),
    )
    ctx = _party_ctx(tap=SpecializationTap("player_2", "warrior_identity", "battle_master"))
    await _select(m, "warrior_identity", "battle_master", ctx=ctx)
    assert ctx.userdata.pending_specialization_tap is None


@pytest.mark.asyncio
async def test_ticket_survives_a_failed_resolution():
    # Cleared post-commit, not on match: a transient failure must not silently degrade
    # the retry to the ambiguous sole-claimant scan.
    m = _make_mocks(
        _player("player_1", class_="warrior", level=5),
        _player("player_2", class_="warrior", level=5),
    )
    tap = SpecializationTap("player_2", "warrior_identity", "duelist")
    ctx = _party_ctx(tap=tap)
    with pytest.raises(ToolError, match="Invalid"):
        await _select(m, "warrior_identity", "duelist", ctx=ctx)
    assert ctx.userdata.pending_specialization_tap is tap


@pytest.mark.asyncio
async def test_ticket_with_mismatched_option_is_ignored():
    # A coincidental voice call must not consume someone else's ticket: honouring this
    # one would raise "already chosen" for player_2 instead of resolving player_1's fork.
    m = _make_mocks(
        _player("player_1", class_="warrior", level=5),
        _player("player_2", class_="warrior", level=5, specialization="berserker"),
    )
    ctx = _party_ctx(tap=SpecializationTap("player_2", "warrior_identity", "berserker"))
    await _select(m, "warrior_identity", "battle_master", ctx=ctx)
    m.persistence.set_player_specialization.assert_awaited_once_with("player_1", "battle_master", conn=m.conn)


@pytest.mark.asyncio
async def test_ticket_naming_a_non_member_is_ignored():
    # A stale ticket from a departed member falls back to the scan rather than writing
    # (or failing) against a player outside this session's party.
    m = _make_mocks(_player("player_1", class_="warrior", level=5))
    ctx = make_context()
    ctx.userdata.pending_specialization_tap = SpecializationTap("player_9", "warrior_identity", "battle_master")
    await _select(m, "warrior_identity", "battle_master", ctx=ctx)
    m.persistence.set_player_specialization.assert_awaited_once_with("player_1", "battle_master", conn=m.conn)


@pytest.mark.asyncio
async def test_ticket_owner_with_nothing_pending_rejects():
    # AC-3: the ticket names a member who has already chosen — reject with their reason,
    # do not silently fall back to whoever else happens to be eligible.
    m = _make_mocks(
        _player("player_1", class_="warrior", level=5),
        _player("player_2", class_="warrior", level=5, specialization="berserker"),
    )
    ctx = _party_ctx(tap=SpecializationTap("player_2", "warrior_identity", "battle_master"))
    with pytest.raises(ToolError, match="already"):
        await _select(m, "warrior_identity", "battle_master", ctx=ctx)
    m.persistence.set_player_specialization.assert_not_awaited()
