"""Multiplayer combat-END reconcile (M18 story-003).

Per-member reconciliation: persistent conditions, beneficial dice, non-primary store merges.
Fast-lane, mock-DI (no real DB): patches the condition read/save round-trip and asserts each
player participant reconciles into its OWN players.data row.

Solo behavior (a 1-member party) is covered byte-identically by the existing single-player
combat-end suites; this suite adds the >1-member assertions.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from session_data import CombatParticipant, CombatState

from ._end_multiplayer_helpers import (
    _cond,
    _player_participant,
    _restore_condition_module,  # noqa: F401
    _run_end_combat_db,
    _two_pc_session,
)


async def test_victory_reconciles_persistent_conditions_per_member():
    # p1 acquired Wounded, p2 acquired Exhausted. Each must persist into its OWN players.data row.
    session = _two_pc_session()
    cs = CombatState(
        combat_id="c1",
        participants=[
            _player_participant("p1", "Kael", [_cond("wounded")]),
            _player_participant("p2", "Bren", [_cond("exhausted")]),
            CombatParticipant(id="g1", name="Goblin", type="enemy", initiative=8, hp_current=0, hp_max=7, ac=13),
        ],
        initiative_order=["p1", "p2", "g1"],
        round_number=2,
        current_turn_index=0,
        location_id="loc1",
    )
    save = AsyncMock()
    await _run_end_combat_db(session, cs, "victory", save_mock=save)

    saved = {call.args[0]: call.args[1] for call in save.await_args_list}
    assert set(saved) == {"p1", "p2"}
    assert [c["type"] for c in saved["p1"]] == ["wounded"]
    assert [c["type"] for c in saved["p2"]] == ["exhausted"]


async def test_victory_reconciles_beneficial_dice_per_member():
    # p1 keeps a surviving Blessed die, p2 an Inspired die — each lands on its own row.
    session = _two_pc_session()
    cs = CombatState(
        combat_id="c1",
        participants=[
            _player_participant("p1", "Kael", [_cond("blessed")]),
            _player_participant("p2", "Bren", [_cond("inspired")]),
            CombatParticipant(id="g1", name="Goblin", type="enemy", initiative=8, hp_current=0, hp_max=7, ac=13),
        ],
        initiative_order=["p1", "p2", "g1"],
        round_number=2,
        current_turn_index=0,
        location_id="loc1",
    )
    save = AsyncMock()
    await _run_end_combat_db(session, cs, "victory", save_mock=save)

    saved = {call.args[0]: call.args[1] for call in save.await_args_list}
    assert [c["type"] for c in saved["p1"]] == ["blessed"]
    assert [c["type"] for c in saved["p2"]] == ["inspired"]


async def test_victory_drops_consumed_beneficial_die_from_row():
    # Complement of test_victory_reconciles_beneficial_dice_per_member (the surviving direction):
    # p1's STORED row carries a Blessed die, but the participant CONSUMED it in combat (M4.8 consume
    # path — no longer on participant.conditions). The combat-end reconcile must DROP the consumed
    # buff from the row, not re-persist it (AC "a consumed die is not re-persisted"). A stored
    # non-buff (Wounded) on the same row must SURVIVE that reconcile — pins that the buff-vs-non-buff
    # partition, not a blanket wipe, is what drops the die.
    session = _two_pc_session()
    cs = CombatState(
        combat_id="c1",
        participants=[
            _player_participant("p1", "Kael", []),  # consumed the buff mid-combat: no live buff
            _player_participant("p2", "Bren", []),
            CombatParticipant(id="g1", name="Goblin", type="enemy", initiative=8, hp_current=0, hp_max=7, ac=13),
        ],
        initiative_order=["p1", "p2", "g1"],
        round_number=2,
        current_turn_index=0,
        location_id="loc1",
    )
    save = AsyncMock()
    await _run_end_combat_db(
        session,
        cs,
        "victory",
        save_mock=save,
        read_side_effect=lambda pid, conn=None: [_cond("blessed"), _cond("wounded")] if pid == "p1" else [],
    )

    saved = {call.args[0]: call.args[1] for call in save.await_args_list}
    p1_types = [c["type"] for c in saved["p1"]]
    assert "blessed" not in p1_types  # consumed in combat -> dropped from the row, not re-persisted
    assert "wounded" in p1_types  # stored non-buff survives the same reconcile


async def test_non_primary_reconcile_reads_its_own_store():
    # The existing-store read is keyed on the member id, so a non-primary member's prior Wounded
    # merges with its own combat-gained Exhausted — not the primary's store.
    session = _two_pc_session()
    cs = CombatState(
        combat_id="c1",
        participants=[
            _player_participant("p1", "Kael", []),
            _player_participant("p2", "Bren", [_cond("exhausted", stacks=2)]),
            CombatParticipant(id="g1", name="Goblin", type="enemy", initiative=8, hp_current=0, hp_max=7, ac=13),
        ],
        initiative_order=["p1", "p2", "g1"],
        round_number=2,
        current_turn_index=0,
        location_id="loc1",
    )

    def _read(pid, conn=None):
        return [_cond("wounded")] if pid == "p2" else []

    save = AsyncMock()
    await _run_end_combat_db(session, cs, "victory", save_mock=save, read_side_effect=_read)

    saved = {call.args[0]: call.args[1] for call in save.await_args_list}
    # p1's store was empty and it gained nothing -> unchanged -> no write.
    assert "p1" not in saved
    # p2 merges its own prior Wounded with the combat-gained Exhausted.
    assert {c["type"] for c in saved["p2"]} == {"wounded", "exhausted"}
