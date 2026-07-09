"""Multiplayer combat-END fallen allies and echo stabilization (story-004).

Echo-primary fate and fallen-ally stabilization across victory outcome.

Fast-lane, mock-DI (no real DB): drives the victory path with mocked content/pricing/queries.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from session_data import CombatParticipant, CombatState

from ._end_multiplayer_helpers import (
    FakeRng,
    _player_participant,
    _restore_condition_module,  # noqa: F401
    _run_victory,
    _two_pc_session,
)


async def test_victory_stabilizes_fallen_ally_without_mortaen(monkeypatch):
    # story-004: a merely-fallen (savable, not is_dead, non-echo) ally on a VICTORY is STABILIZED
    # (revived to 1 HP), not Mortaen-killed. Mortaen is reserved for the truly dead, so a savable
    # ally on a won fight never triggers resurrection.
    import resurrection

    resurrect = AsyncMock(return_value=[])
    monkeypatch.setattr(resurrection, "resurrect_party_on_defeat", resurrect)

    session = _two_pc_session()
    cs = CombatState(
        combat_id="c1",
        participants=[
            _player_participant("p1", "Kael", []),  # primary, alive
            CombatParticipant(
                id="p2", name="Bren", type="player", initiative=12, hp_current=0, hp_max=20, ac=14, is_fallen=True
            ),  # dying but savable
            CombatParticipant(
                id="g1", name="Goblin", type="enemy", initiative=8, hp_current=0, hp_max=7, ac=13, is_fallen=True
            ),
        ],
        initiative_order=["p1", "p2", "g1"],
        round_number=2,
        current_turn_index=0,
        location_id="loc1",
    )
    _end, mutations, _q, _sink = await _run_victory(session, cs, rng=FakeRng(), drops=[])

    hp_calls = [(c.args[0], c.args[1]) for c in mutations.update_player_hp.await_args_list]
    assert ("p2", 1) in hp_calls  # fallen ally comes to at 1 HP
    resurrect.assert_not_awaited()  # NOT Mortaen-killed on a won fight


async def test_victory_resurrects_destroyed_echo_primary_only(monkeypatch):
    # story-004 (the character-loss fix): a destroyed temporary_hollowed echo-primary IS Mortaen-
    # resurrected on VICTORY (an echo is a dead player, resurrected regardless of outcome), while a
    # merely-fallen ally on the same victory is stabilized — only the echo lands in the dead-life set.
    import resurrection

    resurrect = AsyncMock(return_value=[{"anchor": "anchor_x", "revive_hp": 20, "hollow_killed": True}])
    monkeypatch.setattr(resurrection, "resurrect_party_on_defeat", resurrect)

    session = _two_pc_session()  # primary p1
    cs = CombatState(
        combat_id="c1",
        participants=[
            CombatParticipant(
                id="p1",
                name="Kael",
                type="temporary_hollowed",
                initiative=15,
                hp_current=0,
                hp_max=20,
                ac=14,
                is_fallen=True,
            ),  # destroyed echo-primary
            CombatParticipant(
                id="p2", name="Bren", type="player", initiative=12, hp_current=0, hp_max=20, ac=14, is_fallen=True
            ),  # dying ally (savable)
            CombatParticipant(
                id="g1", name="Goblin", type="enemy", initiative=8, hp_current=0, hp_max=7, ac=13, is_fallen=True
            ),
        ],
        initiative_order=["p1", "p2", "g1"],
        round_number=2,
        current_turn_index=0,
        location_id="loc1",
    )
    end_data, mutations, _q, _sink = await _run_victory(session, cs, rng=FakeRng(), drops=[])

    resurrect.assert_awaited_once()
    assert resurrect.await_args is not None
    rows = resurrect.await_args.args[0]
    assert len(rows) == 1  # only the destroyed echo-primary, NOT the savable fallen ally
    hp_calls = [(c.args[0], c.args[1]) for c in mutations.update_player_hp.await_args_list]
    assert ("p2", 1) in hp_calls  # the ally is stabilized, not resurrected
    assert end_data.get("death_context") is not None  # the primary's death context is surfaced


async def test_victory_resurrects_death_save_failed_ally_not_stabilized(monkeypatch):
    # story-004 (concern 8cdb51bd0ef5): an ally who DIED on the death-save grind (3 failures — the
    # 2-flag model leaves is_dead False) is TRULY DEAD, so on a VICTORY it is Mortaen-resurrected, NOT
    # stabilized for free. This matches _wrap's terminally-down predicate (is_dead OR dsf >= limit).
    import resurrection

    resurrect = AsyncMock(return_value=[{"anchor": "anchor_x"}])
    monkeypatch.setattr(resurrection, "resurrect_party_on_defeat", resurrect)

    session = _two_pc_session()
    cs = CombatState(
        combat_id="c1",
        participants=[
            _player_participant("p1", "Kael", []),  # primary, alive
            CombatParticipant(
                id="p2",
                name="Bren",
                type="player",
                initiative=12,
                hp_current=0,
                hp_max=20,
                ac=14,
                is_fallen=True,
                death_save_failures=3,
            ),  # died on the death-save grind (is_dead stays False)
            CombatParticipant(
                id="g1", name="Goblin", type="enemy", initiative=8, hp_current=0, hp_max=7, ac=13, is_fallen=True
            ),
        ],
        initiative_order=["p1", "p2", "g1"],
        round_number=2,
        current_turn_index=0,
        location_id="loc1",
    )
    _end, mutations, _q, _sink = await _run_victory(session, cs, rng=FakeRng(), drops=[])

    resurrect.assert_awaited_once()
    assert resurrect.await_args is not None
    assert len(resurrect.await_args.args[0]) == 1  # p2 is the only dead life
    hp_calls = [(c.args[0], c.args[1]) for c in mutations.update_player_hp.await_args_list]
    assert ("p2", 1) not in hp_calls  # NOT stabilized — it truly died
