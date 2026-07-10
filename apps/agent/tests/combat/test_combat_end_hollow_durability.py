"""Combat-end weapon durability reads the party's LIVE hollow-zone corruption, not a stale copy.

corruption_level is location-derived, never DB-persisted (participant_lifecycle's own note): the
party is co-located, so one value covers everyone. But a joiner's PartyMember.corruption_level was
snapshotted once at join and never refreshed -- movement writes only session.corruption_level, which
the SessionData facade routes to party.primary. Travel into a hollow zone and the joiner's weapon
accrued single wear while the primary's (and everyone's armor) correctly doubled.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

import combat_end
from session_data import CombatParticipant, CombatState

from ._end_multiplayer_helpers import _run_end_combat_db, _two_pc_session

_HOLLOW = 2  # is_hollow_zone threshold: corruption_level >= 2


def _armed(session, player_id: str) -> None:
    """Mark the member as having swung this encounter -- the gate combat_end's weapon loop reads."""
    member = session.party.member(player_id)
    assert member is not None
    member.weapon_used = True


def _player(pid: str) -> CombatParticipant:
    return CombatParticipant(id=pid, name=pid, type="player", initiative=10, hp_current=20, hp_max=20, ac=14)


def _two_pc_fight() -> CombatState:
    return CombatState(
        combat_id="c1",
        participants=[_player("p1"), _player("p2")],
        initiative_order=["p1", "p2"],
        location_id="loc1",
    )


async def _hollow_verdicts(session, monkeypatch) -> dict[str, bool]:
    """Drive combat-end and capture the is_hollow_zone verdict it accrued each member's weapon with."""
    seen: dict[str, bool] = {}

    async def _spy(_session, player_id, _item, _hits, *, is_hollow_zone, conn=None, sink=None):
        seen[player_id] = is_hollow_zone
        return {}

    monkeypatch.setattr(combat_end, "_accrue_durability", _spy)
    monkeypatch.setattr(
        combat_end,
        "_find_equipped",
        lambda _inv, kind: {"id": "longsword", "durability_tier": "standard"} if kind == "weapon" else None,
    )

    await _run_end_combat_db(
        session,
        _two_pc_fight(),
        "victory",
        save_mock=AsyncMock(),
        queries_overrides={"get_player_inventory": AsyncMock(return_value=[])},
    )
    return seen


@pytest.mark.asyncio
async def test_a_joiner_who_travelled_into_a_hollow_zone_takes_doubled_weapon_wear(monkeypatch):
    """The joiner's stale corruption_level (0, from a safe-location join) must not spare their
    weapon. Both members swung in the same hollow zone; the zone belongs to the party."""
    session = _two_pc_session()
    _armed(session, "p1")
    _armed(session, "p2")
    # The party travelled into a hollow zone. movement_tools does exactly this write, and the
    # SessionData facade lands it on the primary alone -- p2's copy stays at the 0 it joined with.
    session.corruption_level = _HOLLOW
    stale = session.party.member("p2")
    assert stale is not None and stale.corruption_level == 0  # the stale copy, still there

    seen = await _hollow_verdicts(session, monkeypatch)

    # Before the fix p2's verdict was False: its weapon took 1 hit where the zone mandates 2.
    assert seen == {"p1": True, "p2": True}


@pytest.mark.asyncio
async def test_outside_a_hollow_zone_no_member_takes_doubled_wear(monkeypatch):
    """Non-vacuity: the same drive at corruption 0 yields False for both, so the test above pins the
    zone rather than merely that _accrue_durability is reached twice."""
    session = _two_pc_session()
    _armed(session, "p1")
    _armed(session, "p2")
    session.corruption_level = 0

    seen = await _hollow_verdicts(session, monkeypatch)

    assert seen == {"p1": False, "p2": False}
