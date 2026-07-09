"""Tests for session_hydration.hydrate_session_state (story-004, M3.5).

The composer rehydrates resonance/concentration from players.data onto SessionData and the veil
ward from the session's location scope (M24: the ward is scope-owned, never on the player row),
increments the player session_count once (story-002), and sets + persists the session-gated
Thessyn flickering_bonus (story-003 gate + story-001 persist). Inject mock *_mod modules for the
DB read/persist/counter (the DI seam); use the REAL racial_resonance for the gate — the autouse
racial fixture (tests/conftest.py) seeds the table so compute_flickering_bonus resolves the +1.
The composed real-PG path is proven at the story-006 capstone.
"""

from unittest.mock import AsyncMock, MagicMock

import racial_resonance
import session_hydration
from session_data import SessionData
from veil_ward import WardScope


def _mods(*, current=0, persisted_bonus=0, active=False, source=None, spell_id=None, count=1):
    """Build the injected mock modules with the given persisted reads + counter return."""
    res_mod = MagicMock()
    res_mod.read_player_resonance = AsyncMock(
        return_value={"current": current, "flickering_bonus": persisted_bonus, "state": "stable"}
    )
    res_mod.update_player_flickering_bonus = AsyncMock()
    ward_mod = MagicMock()
    # Scope-keyed read (story-003): a live ward row, or None when the scope is unwarded.
    ward_mod.read_active_ward = AsyncMock(
        return_value={"source": source, "expires_at": None, "dismissible": True} if active else None
    )
    conc_mod = MagicMock()
    conc_mod.read_player_concentration = AsyncMock(return_value={"spell_id": spell_id})
    ps_mod = MagicMock()
    ps_mod.hydrate_player_session = AsyncMock(return_value=count)
    return res_mod, ward_mod, conc_mod, ps_mod


async def _hydrate(session, player, mods):
    res_mod, ward_mod, conc_mod, ps_mod = mods
    await session_hydration.hydrate_session_state(
        session,
        player,
        resonance_mutations_mod=res_mod,
        veil_ward_mutations_mod=ward_mod,
        concentration_mutations_mod=conc_mod,
        player_session_mod=ps_mod,
        racial_mod=racial_resonance,
    )


class TestHydrateSessionState:
    async def test_hydrates_the_ward_from_the_session_location_scope(self):
        # story-003: the ward is read from the LOCATION scope, never from the player row.
        session = SessionData(player_id="p1", location_id="thornwatch_keep")
        mods = _mods(active=True, source="cleric")
        await _hydrate(session, {"race": "human"}, mods)
        _res, ward_mod, _conc, _ps = mods
        scope = ward_mod.read_active_ward.call_args.args[0]
        assert scope == WardScope.location("thornwatch_keep")

    async def test_unwarded_scope_hydrates_to_no_ward(self):
        session = SessionData(player_id="p1", location_id="loc")
        await _hydrate(session, {"race": "human"}, _mods(active=False))
        assert session.veil_ward.active is False
        assert session.veil_ward.source is None

    async def test_rehydrates_all_three_persisted_states_not_defaults(self):
        # AC1: the SessionData reflects the persisted current/active/spell_id, not the defaults.
        session = SessionData(player_id="p1", location_id="loc")
        mods = _mods(current=7, active=True, source="druid", spell_id="frost", count=3)
        await _hydrate(session, {"race": "human"}, mods)
        assert session.resonance.current == 7
        assert session.veil_ward.active is True
        assert session.veil_ward.source == "druid"
        assert session.concentration.spell_id == "frost"

    async def test_thessyn_at_threshold_sets_and_persists_bonus_1(self):
        # AC2: a Thessyn reaching session_count 10 gets flickering_bonus 1, set AND persisted.
        session = SessionData(player_id="p1", location_id="loc")
        mods = _mods(current=9, count=10)
        await _hydrate(session, {"race": "thessyn"}, mods)
        assert session.resonance.flickering_bonus == 1
        mods[0].update_player_flickering_bonus.assert_awaited_once_with("p1", 1, conn=None)

    async def test_thessyn_below_threshold_bonus_0(self):
        # AC3: a <10-session Thessyn gets flickering_bonus 0 (in-memory). The persisted value is
        # already 0, so the redundant UPDATE is SKIPPED (write-on-change), still satisfying the
        # single-derivation invariant — the read path and the session both derive band 0.
        session = SessionData(player_id="p1", location_id="loc")
        mods = _mods(count=9)
        await _hydrate(session, {"race": "thessyn"}, mods)
        assert session.resonance.flickering_bonus == 0
        mods[0].update_player_flickering_bonus.assert_not_awaited()

    async def test_thessyn_steady_above_threshold_skips_redundant_write(self):
        # A Thessyn already past the gate (persisted bonus 1, still computing 1) skips the write —
        # write-on-change persists only the Deep-Adaptation crossing, not every steady session-init.
        session = SessionData(player_id="p1", location_id="loc")
        mods = _mods(persisted_bonus=1, count=20)
        await _hydrate(session, {"race": "thessyn"}, mods)
        assert session.resonance.flickering_bonus == 1
        mods[0].update_player_flickering_bonus.assert_not_awaited()

    async def test_non_thessyn_never_gets_bonus(self):
        # A non-Thessyn at any session_count gets 0 (the gate short-circuits before the lookup), and
        # because the persisted bonus is already 0 the redundant UPDATE is SKIPPED — the common path.
        session = SessionData(player_id="p1", location_id="loc")
        mods = _mods(count=50)
        await _hydrate(session, {"race": "human"}, mods)
        assert session.resonance.flickering_bonus == 0
        mods[0].update_player_flickering_bonus.assert_not_awaited()

    async def test_session_counter_ticks_exactly_once(self):
        # The player session_count is incremented exactly once per fresh session.
        session = SessionData(player_id="p1", location_id="loc")
        mods = _mods(count=2)
        await _hydrate(session, {"race": "human"}, mods)
        mods[3].hydrate_player_session.assert_awaited_once_with("p1", conn=None)

    async def test_missing_race_is_treated_as_non_thessyn(self):
        # A player with no race set takes no racial branch -> bonus 0, no crash.
        session = SessionData(player_id="p1", location_id="loc")
        mods = _mods(count=50)
        await _hydrate(session, {}, mods)
        assert session.resonance.flickering_bonus == 0
