"""Combat-end XP is a party-wide Resolve, not an LLM tool call (M28 story-001).

Until M28 _end_combat_db only CALCULATED xp_total and the response told the LLM to "call award_xp
with the xp_total". story-003 removed award_xp from the tool surface, so without this in-transaction grant every
combat reward would silently vanish. The grant rides the same seat_order the loot and currency passes
walk, shares the party curve with coin, and buffers its events into the caller's sink so a rolled-back
phase un-grants the XP and drops the unflushed event.

Fast lane. Mostly mock-DI (the victory path with mocked content/pricing/queries); the closing
test is real-PG (dev_db_pool) because "granted exactly once, committed with the phase" is a claim
only a real transaction can settle.
"""

from __future__ import annotations

import json
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from combat._helpers import _damage_resolver
from sample_fixtures import GUILD_PLAYER

import archetypes
import combat_turn
import db_mutations
import db_mutations_conditions
import db_queries
import event_types as E
import milestones
from combat_end import _end_combat_db, _end_combat_finish
from combat_events import EventSink
from milestones import Grant, Milestone, SpecializationOption
from session_data import CombatParticipant, CombatState, SessionData

from ._end_multiplayer_helpers import (
    FakeRng,
    _member,
    _restore_condition_module,  # noqa: F401
)

# A warrior ladder mirroring content/archetype_milestones.json: the L5 fork with options, and the
# L10 auto-grant whose extra_attack flag must be written inside the combat-end transaction.
_WARRIOR_LADDER = {
    "warrior_identity": Milestone(
        "warrior_identity",
        "warrior",
        "identity",
        5,
        "specialization_fork",
        False,
        (
            SpecializationOption("battle_master", "Battle Master", "Tactical maneuvers."),
            SpecializationOption("berserker", "Berserker", "Reckless fury."),
        ),
        None,
        "cue",
    ),
    "warrior_power": Milestone(
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
}


@pytest.fixture
def warrior_ladder():
    prior = dict(milestones._milestones)
    milestones.set_milestones(_WARRIOR_LADDER)
    yield
    milestones.set_milestones(prior)


def _xp_enemy(pid: str, xp_value: int) -> CombatParticipant:
    """A defeated, currency-less enemy worth ``xp_value`` — isolates XP from the coin pass."""
    return CombatParticipant(
        id=pid, name=pid, type="enemy", initiative=8, hp_current=0, hp_max=7, ac=13, is_fallen=True, xp_value=xp_value
    )


def _cs(enemies: list[CombatParticipant], players: list[str]) -> CombatState:
    parts = [
        CombatParticipant(id=pid, name=pid, type="player", initiative=15, hp_current=20, hp_max=20, ac=14)
        for pid in players
    ] + enemies
    return CombatState(
        combat_id="c1",
        participants=parts,
        initiative_order=[p.id for p in parts],
        round_number=2,
        current_turn_index=0,
        location_id="loc1",
    )


def _session(player_ids: list[str]) -> SessionData:
    session = SessionData(player_id=player_ids[0], location_id="loc1", room=None)
    for pid in player_ids[1:]:
        session.party.members.append(_member(pid))
    return session


async def _run(session, cs, outcome="victory", *, players_by_id=None, conn=None, monkeypatch=None):
    """Drive _end_combat_db with mock DI. Returns (end_data, mutations, queries, sink, conn).

    ``players_by_id`` supplies each participant's players.data row (xp/level/class); the default is
    a fresh level-1 warrior for every seat.
    """
    if outcome != "victory" and monkeypatch is not None:
        import resurrection

        monkeypatch.setattr(resurrection, "resurrect_party_on_defeat", AsyncMock(return_value=[]))
        monkeypatch.setattr(
            resurrection, "resurrect_on_defeat", AsyncMock(return_value={"anchor": "anchor_x", "revive_hp": 10})
        )
    db_mutations_conditions.read_player_conditions = AsyncMock(return_value=[])  # type: ignore[assignment]
    db_mutations_conditions.save_player_conditions = AsyncMock()  # type: ignore[assignment]

    def _row(pid: str) -> dict | None:
        # An EXPLICIT None means "no players.data row for this seat" — distinct from "not
        # supplied", which still gets the default level-1 warrior.
        if players_by_id is not None and pid in players_by_id:
            return players_by_id[pid]
        return {**GUILD_PLAYER, "player_id": pid, "class": "warrior"}

    mutations = AsyncMock()
    queries = AsyncMock()
    queries.get_player = AsyncMock(side_effect=lambda pid, conn=None, for_update=False: _row(pid))
    queries.get_player_inventory = AsyncMock(return_value=[])
    sink = EventSink()
    conn = conn or MagicMock()
    end_data = await _end_combat_db(
        session,
        cs,
        outcome,
        mutations=mutations,
        queries=queries,
        conn=conn,
        sink=sink,
        content=MagicMock(),
        pricing=MagicMock(),
        rng=FakeRng(),
    )
    return end_data, mutations, queries, sink, conn


def _xp_events(sink: EventSink) -> list[dict]:
    return [e.payload for e in sink.captured if e.event_type == E.XP_AWARDED]


def _xp_grants(mutations) -> dict[str, int]:
    """{player_id: new_xp} from the update_player_xp writes."""
    return {c.args[0]: c.args[1] for c in mutations.update_player_xp.await_args_list}


# --- AC1: a solo victory grants the full total in the end transaction ---


async def test_solo_victory_grants_the_full_total():
    # Solo N=1 -> multiplier 1.0, one seat: the primary receives the whole encounter total, exactly
    # what the LLM used to be told to hand out by hand.
    session = _session(["p1"])
    end_data, mutations, _q, sink, _c = await _run(session, _cs([_xp_enemy("g1", 50)], ["p1"]))

    assert end_data["xp_total"] == 50
    assert end_data["xp_granted"] == 50
    assert _xp_grants(mutations) == {"p1": 50}
    assert [e["amount"] for e in _xp_events(sink)] == [50]
    assert _xp_events(sink)[0]["player_id"] == "p1"


async def test_solo_victory_response_carries_no_award_xp_note():
    # The DM narrates the granted XP from the tool response; there is no longer a second tool call
    # to cue, so the note is gone (story-003 removes award_xp entirely).
    session = _session(["p1"])
    cs = _cs([_xp_enemy("g1", 50)], ["p1"])
    end_data, _m, _q, _sink, _c = await _run(session, cs)
    _agent, raw = _end_combat_finish(session, cs, "victory", end_data)
    response = json.loads(raw)

    assert "note" not in response
    assert response["xp_granted"] == 50
    assert session.session_xp_earned == 50


async def test_finish_summary_reports_the_granted_share_not_the_raw_total():
    # The handoff line the DM voices must be what the player actually received. In a party the
    # share is smaller than the encounter total; narrating the total would over-promise.
    session = _session(["p1", "p2"])
    cs = _cs([_xp_enemy("g1", 100)], ["p1", "p2"])
    end_data, _m, _q, _sink, _c = await _run(session, cs)
    agent, _raw = _end_combat_finish(session, cs, "victory", end_data)

    summary = " ".join(str(item.content) for item in agent.chat_ctx.items)
    assert "XP earned: 75." in summary  # int(100 * 1.5 / 2)
    assert "XP earned: 100." not in summary


# --- AC2: a multiplayer victory splits on the shared party curve, in seat order ---


async def test_mp_victory_grants_each_participant_the_party_share():
    # XP rides the SAME curve as coin (decision 91967897c88c): total * multiplier(N) / N. For 2 PCs
    # that is 100 * 1.5 / 2 = 75 each — the party earns more than a solo, without N x farming.
    session = _session(["p1", "p2"])
    _end, mutations, _q, sink, _c = await _run(session, _cs([_xp_enemy("g1", 100)], ["p1", "p2"]))

    assert _xp_grants(mutations) == {"p1": 75, "p2": 75}
    assert [(e["player_id"], e["amount"]) for e in _xp_events(sink)] == [("p1", 75), ("p2", 75)]


async def test_mp_victory_locks_player_rows_in_ascending_seat_order():
    # Every FOR UPDATE read-modify-write in the end tx walks ascending player_id — the deadlock-free
    # lock order (SSOT 5da95d657255) the loot and currency passes already obey.
    session = _session(["p2", "p1"])  # primary is p2; seat order is still p1, p2
    _end, _m, queries, _sink, _c = await _run(session, _cs([_xp_enemy("g1", 100)], ["p2", "p1"]))

    lock_order = [c.args[0] for c in queries.get_player.await_args_list if c.kwargs.get("for_update")]
    assert lock_order == ["p1", "p2"]


async def test_mp_victory_end_data_carries_the_primarys_own_share():
    # end_data.xp_granted is the PRIMARY's share (matching primary_currency_gold), because the
    # single-session response and session_xp_earned are the primary's own, never the party sum.
    session = _session(["p2", "p1"])  # primary p2
    end_data, _m, _q, _sink, _c = await _run(session, _cs([_xp_enemy("g1", 100)], ["p1", "p2"]))

    assert end_data["xp_total"] == 100
    assert end_data["xp_granted"] == 75


async def test_a_share_that_rounds_to_zero_grants_nothing_rather_than_erroring():
    # int(1 * 2.0 / 3) == 0. _award_xp_core has no positivity guard, but a zero-amount XP_AWARDED is
    # a "+0 XP" toast for nobody — skip the pass rather than publish it (or raise).
    session = _session(["p1", "p2", "p3"])
    _end, mutations, _q, sink, _c = await _run(session, _cs([_xp_enemy("g1", 1)], ["p1", "p2", "p3"]))

    mutations.update_player_xp.assert_not_awaited()
    assert _xp_events(sink) == []


async def test_a_seat_with_no_player_row_is_skipped():
    # combat_rewards skips a seat whose players.data row is missing rather than aborting the whole
    # end-of-combat transaction over a non-critical reward — symmetric with the currency pass's
    # tolerance. The OTHER seats must still be paid: one absent row cannot cost the party its XP.
    session = _session(["p1", "p2"])
    _end, mutations, _q, sink, _c = await _run(
        session, _cs([_xp_enemy("g1", 100)], ["p1", "p2"]), players_by_id={"p2": None}
    )

    assert _xp_grants(mutations) == {"p1": 75}
    assert [(e["player_id"], e["amount"]) for e in _xp_events(sink)] == [("p1", 75)]


async def test_empty_seat_order_grants_nothing(monkeypatch):
    # concern ab4ced4c2110: a MANUAL end_combat('victory') can leave NO player participant (a solo
    # primary risen as an echo). No player-life is left to receive the XP — skip, don't divide by zero.
    import resurrection

    monkeypatch.setattr(resurrection, "resurrect_party_on_defeat", AsyncMock(return_value=[{"anchor": "a"}]))
    session = _session(["p1"])
    cs = CombatState(
        combat_id="c1",
        participants=[
            CombatParticipant(
                id="p1", name="Kael", type="temporary_hollowed", initiative=15, hp_current=0, hp_max=20, ac=14
            ),
            _xp_enemy("g1", 50),
        ],
        initiative_order=["p1", "g1"],
        round_number=2,
        current_turn_index=0,
        location_id="loc1",
    )
    end_data, mutations, _q, sink, _c = await _run(session, cs)

    assert end_data["xp_granted"] == 0
    mutations.update_player_xp.assert_not_awaited()
    assert _xp_events(sink) == []


# --- story-011: a malformed member row must not trap the party in combat ---


async def test_a_classless_member_leveling_up_is_skipped_others_paid_and_end_commits(warrior_ladder):
    # Pre-fix, player["class"] is indexed unguarded inside the level-up branch of
    # _award_xp_core (progression_tools.py) -> KeyError: 'class', raised INSIDE the combat-end
    # transaction, rolling back loot/coin/XP/durability/resurrection and the combat-row delete
    # for the WHOLE party. The malformed seat must forfeit its own share, not trap everyone else's.
    # 2-seat party: party_reward_multiplier(2) = 1.5 -> int(200 * 1.5 / 2) = 150 each;
    # 3300 + 150 == 3450 == XP_FOR_LEVEL[10], an exact boundary landing.
    session = _session(["p1", "p2"])
    classless_row = {k: v for k, v in GUILD_PLAYER.items() if k != "class"}
    classless_row = {**classless_row, "player_id": "p1", "level": 9, "xp": 3300}
    _end, mutations, _q, sink, _c = await _run(
        session,
        _cs([_xp_enemy("g1", 200)], ["p1", "p2"]),
        players_by_id={"p1": classless_row},
    )

    assert _xp_grants(mutations) == {"p2": 150}  # p1's forfeited share is not redistributed
    assert [e["player_id"] for e in _xp_events(sink)] == ["p2"]


async def test_a_member_with_unknown_class_leveling_up_is_skipped_others_paid_and_end_commits(warrior_ladder):
    # Present but not a loaded archetype fails a DIFFERENT way: build_level_up_payload_for_archetype
    # -> calculate_max_hp -> get_archetype_chassis raises ValueError("Unknown archetype: ...")
    # inside the same transaction. The predicate is "a chassis we can build a level-up from", not
    # "the key exists" — a guard that only checks presence leaves this route open.
    session = _session(["p1", "p2"])
    bad_class_row = {**GUILD_PLAYER, "player_id": "p1", "class": "not_a_real_archetype", "level": 9, "xp": 3300}
    _end, mutations, _q, sink, _c = await _run(
        session,
        _cs([_xp_enemy("g1", 200)], ["p1", "p2"]),
        players_by_id={"p1": bad_class_row},
    )

    assert _xp_grants(mutations) == {"p2": 150}
    assert [e["player_id"] for e in _xp_events(sink)] == ["p2"]


async def test_the_skip_is_logged_with_the_player_id(caplog):
    # The skip must be observable, not silent — a silent skip converts a hard failure into a
    # member who quietly stops earning, which is harder to diagnose than the crash was.
    session = _session(["p1", "p2"])
    classless_row = {**{k: v for k, v in GUILD_PLAYER.items() if k != "class"}, "player_id": "p1"}
    with caplog.at_level(logging.WARNING):
        await _run(session, _cs([_xp_enemy("g1", 50)], ["p1", "p2"]), players_by_id={"p1": classless_row})

    assert any("p1" in record.getMessage() for record in caplog.records)


async def test_a_classless_member_not_leveling_up_is_still_skipped_and_earns_nothing():
    # Accepted consequence, pinned: a classless row that ISN'T crossing a level boundary used to
    # be paid (no error path was ever hit — xp/level are read with .get() defaults). After the fix
    # it earns nothing: XP on a row that cannot level is progression that will never resolve,
    # matching the missing-row precedent of paying nothing rather than something unresolvable.
    session = _session(["p1", "p2"])
    classless_row = {**{k: v for k, v in GUILD_PLAYER.items() if k != "class"}, "player_id": "p1"}
    _end, mutations, _q, _sink, _c = await _run(
        session, _cs([_xp_enemy("g1", 50)], ["p1", "p2"]), players_by_id={"p1": classless_row}
    )

    assert _xp_grants(mutations) == {"p2": 37}  # int(50 * 1.5 / 2); p1 skipped despite no level crossing


async def test_registry_not_loaded_does_not_silently_void_every_members_xp():
    # If the archetype registry isn't loaded at all, every class would read as "unknown" — the
    # membership half of the guard must gate on is_loaded() so a startup bug doesn't turn into
    # every member's XP silently vanishing, which is strictly worse than the crash this fixes.
    # A combat-end test, not a predicate test: is_known's own empty-registry unit test proves the
    # predicate, not the fall-through — deleting the is_loaded gate would leave THAT suite green.
    archetypes.set_archetypes({})
    session = _session(["p1", "p2"])
    _end, mutations, _q, _sink, _c = await _run(session, _cs([_xp_enemy("g1", 100)], ["p1", "p2"]))

    assert _xp_grants(mutations) == {"p1": 75, "p2": 75}


# --- AC4: a level crossing resolves in the same transaction ---


async def test_level_crossing_publishes_level_up_and_applies_the_auto_grant(warrior_ladder):
    # L9 (2900xp) + 550 -> L10: the auto-grant tier. The extra_attack flag write is part of THIS
    # transaction — the single deterministic leveling chokepoint, not an LLM tool call.
    session = _session(["p1"])
    row = {**GUILD_PLAYER, "player_id": "p1", "class": "warrior", "level": 9, "xp": 2900}
    end_data, mutations, _q, sink, conn = await _run(
        session, _cs([_xp_enemy("g1", 550)], ["p1"]), players_by_id={"p1": row}
    )

    assert E.LEVEL_UP in [e.event_type for e in sink.captured]
    mutations.set_player_flag.assert_awaited_once_with("p1", "extra_attack", True, conn=conn)
    assert [g["name"] for g in end_data["milestone_grants"]] == ["Extra Attack"]


async def test_l5_crossing_surfaces_the_specialization_fork_in_the_response(warrior_ladder):
    # The L5 fork stays a pending-choice CUE (the generic select verb resolves it, story-003) — the
    # combat-end response carries the flag so the DM voices the fork, and the HUD gets its overlay.
    session = _session(["p1"])
    row = {**GUILD_PLAYER, "player_id": "p1", "class": "warrior", "level": 4, "xp": 750}
    cs = _cs([_xp_enemy("g1", 300)], ["p1"])
    end_data, _m, _q, sink, _c = await _run(session, cs, players_by_id={"p1": row})
    _agent, raw = _end_combat_finish(session, cs, "victory", end_data)

    assert json.loads(raw)["specialization_fork"] is True
    fork_events = [e.payload for e in sink.captured if e.event_type == E.SPECIALIZATION_CHOICE]
    assert [e["player_id"] for e in fork_events] == ["p1"]


# --- AC5: only a victory pays ---


@pytest.mark.parametrize("outcome", ["defeat", "fled"])
async def test_non_victory_grants_no_xp(outcome, monkeypatch):
    session = _session(["p1"])
    _end, mutations, _q, sink, _c = await _run(
        session, _cs([_xp_enemy("g1", 50)], ["p1"]), outcome=outcome, monkeypatch=monkeypatch
    )

    mutations.update_player_xp.assert_not_awaited()
    assert _xp_events(sink) == []


# --- AC6: the grant is a transaction participant, its events are rollback-safe ---


async def test_xp_is_written_on_the_callers_conn_and_its_events_only_buffered():
    # The write joins the CALLER's transaction (the phase tx or end_combat's own), so a rollback
    # un-grants it; the events sit in the sink unflushed, so a rollback drops them unsent. Nothing
    # reaches the room until the caller flushes post-commit.
    session = _session(["p1"])
    _end, mutations, _q, sink, conn = await _run(session, _cs([_xp_enemy("g1", 50)], ["p1"]))

    assert mutations.update_player_xp.await_args.kwargs["conn"] is conn
    assert E.XP_AWARDED in [e.event_type for e in sink.captured]  # buffered, not published
    assert sink.captured[0].room is None  # SessionData(room=None): nothing was published directly


# --- AC7: end-to-end through the live phase path, against real Postgres ---


async def test_resolve_phase_victory_persists_exactly_one_grant(dev_db_pool):
    """The live exit path (resolve_phase -> wrap -> _end_combat_db in the PHASE transaction) writes
    the XP to players.data once. Mock-conn tests can't see this: the grant only counts if it commits
    with the phase, and a second grant would show up as double XP on the persisted row."""
    pool = dev_db_pool
    player_id = "m28_s001_xp_phase_player"
    combat_id = "combat_m28_s001_xp"
    await pool.execute(
        "INSERT INTO players (player_id, data) VALUES ($1, $2::jsonb) "
        "ON CONFLICT (player_id) DO UPDATE SET data = $2::jsonb",
        player_id,
        json.dumps(
            {"player_id": player_id, "class": "warrior", "level": 3, "xp": 500, "hp": {"current": 25, "max": 25}}
        ),
    )
    enemy_id = "m28_s001_xp_enemy"
    cs = CombatState(
        combat_id=combat_id,
        participants=[
            CombatParticipant(
                id=player_id,
                name="Kael",
                type="player",
                initiative=15,
                hp_current=25,
                hp_max=25,
                ac=14,
                action_pool=[{"name": "Longsword", "damage": "1d8", "damage_type": "slashing", "properties": []}],
            ),
            CombatParticipant(
                id=enemy_id,
                name="Goblin",
                type="enemy",
                initiative=12,
                hp_current=3,  # one fixed 3-damage hit from death -> the wrap sees victory
                hp_max=7,
                ac=13,
                action_pool=[{"name": "Scimitar", "damage": "1d6", "damage_type": "slashing"}],
                xp_value=50,
            ),
        ],
        initiative_order=[player_id, enemy_id],
        beat="resolution",
        pending_declarations={player_id: {"type": "attack", "action": "Longsword", "target_id": enemy_id}},
    )

    ctx = MagicMock()
    ctx.session.current_agent = None
    ctx.userdata = SessionData(player_id=player_id, location_id="accord_guild_hall", room=None)
    ctx.userdata.combat_state = cs
    queries = MagicMock(get_player_inventory=AsyncMock(return_value=[]))  # no equipped items -> no durability
    queries.get_player = db_queries.get_player  # the grant needs the REAL row read
    break_mod = MagicMock(break_concentration_on_damage=AsyncMock(return_value=None))

    try:
        result = await combat_turn._resolve_phase_impl(
            ctx, queries=queries, resolver=_damage_resolver(3), concentration_break_mod=break_mod
        )
        assert json.loads(result[1])["outcome"] == "victory"

        row = await pool.fetchrow("SELECT (data->>'xp')::int AS xp FROM players WHERE player_id = $1", player_id)
        assert row["xp"] == 550  # 500 seeded + the solo encounter's whole 50, granted exactly once
    finally:
        await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)
        await db_mutations.delete_combat_state(combat_id, conn=pool)
