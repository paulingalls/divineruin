from __future__ import annotations

import asyncio
import dataclasses
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from combat._helpers import _make_combat_state
from livekit.agents.llm import ToolError
from sample_fixtures import make_context, make_db_mod

import abilities
import reaction_spend
import reaction_windows
from ability_tools import _request_ability_activation_impl
from combat_phase import PhaseBeat


def _row(player_id: str, *, stamina: int = 10, class_: str = "guardian") -> dict:
    return {
        "player_id": player_id,
        "name": player_id,
        "class": class_,
        "level": 5,
        "stamina": {"current": stamina, "max": 10},
        "focus": {"current": 10, "max": 10},
    }


def _context():
    ctx = make_context(party_member_ids=["player_2"])
    state = _make_combat_state()
    first = state.get_participant("player_1")
    assert first is not None
    first.has_reaction_ability = True
    first.reaction_ids = ["guardian_intercept"]
    state.participants.append(
        dataclasses.replace(first, id="player_2", name="player_2", reaction_ids=["guardian_intercept"])
    )
    state.beat = PhaseBeat.NARRATION
    state.held_actions = [
        {
            "seq": 4,
            "actor_id": "goblin_scout_1",
            "initiative": 12,
            "declaration": {"type": "attack", "action": "Scimitar", "target_id": "player_1"},
            "roll": None,
            "opened": ["pre_roll", "post_roll"],
        }
    ]
    state.open_window = reaction_windows.open_window_for(
        round_number=1,
        seq=4,
        stage=reaction_windows.POST_ROLL,
        actor_id="goblin_scout_1",
        target_id="player_1",
        action_kind="attack",
        triggers=reaction_windows.post_roll_triggers({}, hit=True),
    )
    state.reactions_available = {"player_1": reaction_spend.unspent(), "player_2": reaction_spend.unspent()}
    ctx.userdata.combat_state = state
    return ctx


def _deps(rows: dict[str, dict]):
    db_mod, conn = make_db_mod()
    queries = MagicMock()

    async def lock(ids, *, conn):
        return {player_id: rows[player_id] for player_id in ids if player_id in rows}

    queries.get_players_for_update = AsyncMock(side_effect=lock)
    persistence = MagicMock(
        owns_elective=AsyncMock(return_value=False),
        get_active_variant=AsyncMock(return_value=None),
        update_player_resources=AsyncMock(),
    )
    return db_mod, conn, queries, persistence


async def _activate(ctx, rows, *, actor="player_2", generation=7, validator=None, **overrides):
    db_mod, conn, queries, persistence = _deps(rows)
    validator = validator or MagicMock()
    with ctx.userdata._bind_authenticated_actor(actor, generation, validator):
        result = await _request_ability_activation_impl(
            ctx,
            "guardian_intercept",
            db_mod=db_mod,
            queries_mod=queries,
            persistence_mod=persistence,
            **overrides,
        )
    return result, conn, queries, persistence, validator


async def test_bound_speaker_owns_locks_debits_and_records_their_reaction() -> None:
    ctx = _context()
    primary = ctx.userdata.combat_state.get_participant("player_1")
    assert primary is not None
    primary.reaction_ids = []
    rows = {"player_1": _row("player_1"), "player_2": _row("player_2")}

    _result, conn, queries, persistence, validator = await _activate(ctx, rows)

    assert validator.call_args_list == [(("player_2", 7),), (("player_2", 7),)]
    queries.get_players_for_update.assert_awaited_once_with(["player_2"], conn=conn)
    persistence.update_player_resources.assert_awaited_once_with("player_2", stamina=7, focus=None, conn=conn)
    assert rows["player_1"]["stamina"]["current"] == 10
    assert not reaction_spend.is_spent(ctx.userdata.combat_state.reactions_available["player_1"])
    assert reaction_spend.is_spent(ctx.userdata.combat_state.reactions_available["player_2"])


def test_authenticated_binding_supplies_actor_property_and_restores_it() -> None:
    ctx = _context()

    with ctx.userdata._bind_authenticated_actor("player_2", 7, lambda *_args: None):
        assert ctx.userdata.actor_player_id == "player_2"
        assert ctx.userdata.require_reaction_actor().generation == 7
    with pytest.raises(RuntimeError, match="No actor"):
        _ = ctx.userdata.actor_player_id


@pytest.mark.parametrize("failure", ["ownership", "funds"])
async def test_refused_second_speaker_does_not_change_the_first_or_spend_their_reaction(failure: str) -> None:
    ctx = _context()
    rows = {"player_1": _row("player_1"), "player_2": _row("player_2", stamina=0 if failure == "funds" else 10)}
    await _activate(ctx, rows, actor="player_1", generation=3)
    if failure == "ownership":
        participant = ctx.userdata.combat_state.get_participant("player_2")
        assert participant is not None
        participant.reaction_ids = []
    db_mod, conn, queries, persistence = _deps(rows)

    with ctx.userdata._bind_authenticated_actor("player_2", 7, MagicMock()):
        with pytest.raises(ToolError) as refusal:
            await _request_ability_activation_impl(
                ctx, "guardian_intercept", db_mod=db_mod, queries_mod=queries, persistence_mod=persistence
            )

    # WHOSE refusal it is, not merely that one happened: a primary-player fallback ALSO raises
    # ToolError here — player_1 already spent — so every assertion below except these two holds
    # against the defect this test exists to catch.
    if failure == "ownership":
        assert "'player_2'" in str(refusal.value)
    else:
        queries.get_players_for_update.assert_awaited_once_with(["player_2"], conn=conn)
    persistence.update_player_resources.assert_not_awaited()
    assert reaction_spend.is_spent(ctx.userdata.combat_state.reactions_available["player_1"])
    assert not reaction_spend.is_spent(ctx.userdata.combat_state.reactions_available["player_2"])


async def test_reaction_requires_a_current_authenticated_binding() -> None:
    ctx = _context()
    rows = {"player_1": _row("player_1"), "player_2": _row("player_2")}
    db_mod, _conn, queries, persistence = _deps(rows)

    with pytest.raises(RuntimeError, match="authenticated"):
        await _request_ability_activation_impl(
            ctx, "guardian_intercept", db_mod=db_mod, queries_mod=queries, persistence_mod=persistence
        )
    stale = MagicMock(side_effect=RuntimeError("stale authenticated actor"))
    with ctx.userdata._bind_authenticated_actor("player_2", 7, stale):
        with pytest.raises(RuntimeError, match="stale"):
            await _request_ability_activation_impl(
                ctx, "guardian_intercept", db_mod=db_mod, queries_mod=queries, persistence_mod=persistence
            )
    queries.get_players_for_update.assert_not_awaited()
    persistence.update_player_resources.assert_not_awaited()


async def test_revocation_while_row_lock_waits_cannot_write_or_record() -> None:
    ctx = _context()
    rows = {"player_1": _row("player_1"), "player_2": _row("player_2")}
    db_mod, _conn, queries, persistence = _deps(rows)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def blocked_lock(ids, *, conn):
        entered.set()
        await release.wait()
        return {player_id: rows[player_id] for player_id in ids}

    queries.get_players_for_update.side_effect = blocked_lock
    current = True

    def validate(_player_id, _generation):
        if not current:
            raise RuntimeError("stale authenticated actor")

    async def invoke():
        with ctx.userdata._bind_authenticated_actor("player_2", 7, validate):
            return await _request_ability_activation_impl(
                ctx, "guardian_intercept", db_mod=db_mod, queries_mod=queries, persistence_mod=persistence
            )

    task = asyncio.create_task(invoke())
    await asyncio.wait_for(entered.wait(), 1)
    current = False
    release.set()
    with pytest.raises(RuntimeError, match="stale"):
        await task

    persistence.update_player_resources.assert_not_awaited()
    assert not reaction_spend.is_spent(ctx.userdata.combat_state.reactions_available["player_2"])


async def test_revocation_while_variant_lookup_waits_cannot_debit() -> None:
    ctx = _context()
    rows = {"player_1": _row("player_1"), "player_2": _row("player_2")}
    db_mod, _conn, queries, persistence = _deps(rows)
    entered = asyncio.Event()
    release = asyncio.Event()
    authorized = True
    variant_id = "guardian_intercept_test_variant"

    async def blocked_variant(*_args, **_kwargs):
        entered.set()
        await release.wait()
        return variant_id

    def validate(_player_id, _generation):
        if not authorized:
            raise RuntimeError("stale authenticated actor")

    persistence.get_active_variant.side_effect = blocked_variant
    base = abilities.get_ability("guardian_intercept")
    variant = SimpleNamespace(
        cost=base.cost,
        narration_cue=base.narration_cue,
        effect=base.effect,
        cultural_attribution="test",
    )
    variants = MagicMock(get_variant=MagicMock(return_value=variant))

    async def invoke():
        with ctx.userdata._bind_authenticated_actor("player_2", 7, validate):
            return await _request_ability_activation_impl(
                ctx,
                "guardian_intercept",
                variant_id=variant_id,
                db_mod=db_mod,
                queries_mod=queries,
                persistence_mod=persistence,
                variants_mod=variants,
            )

    task = asyncio.create_task(invoke())
    await asyncio.wait_for(entered.wait(), 1)
    authorized = False
    release.set()
    with pytest.raises(RuntimeError, match="stale"):
        await task

    persistence.update_player_resources.assert_not_awaited()
    assert not reaction_spend.is_spent(ctx.userdata.combat_state.reactions_available["player_2"])


async def test_out_of_combat_condition_names_bound_speaker_as_caster() -> None:
    ctx = make_context(party_member_ids=["player_2"])
    synthetic = dataclasses.replace(abilities.get_ability("guardian_intercept"), applies_condition="inspired")
    catalog = MagicMock(get_ability=MagicMock(return_value=synthetic), owns_ability=MagicMock(return_value=True))
    producer = MagicMock(
        lock_ooc_caster_and_targets=AsyncMock(return_value=({"player_2": _row("player_2")}, _row("player_2"))),
        produce_ooc_condition=AsyncMock(return_value=["player_2"]),
    )
    rows = {"player_1": _row("player_1"), "player_2": _row("player_2")}

    await _activate(ctx, rows, abilities_mod=catalog, condition_produce_mod=producer)

    assert producer.lock_ooc_caster_and_targets.await_args.kwargs["player_id"] == "player_2"
    assert producer.produce_ooc_condition.await_args.kwargs["caster_id"] == "player_2"


async def test_nonreaction_without_binding_still_uses_primary_player() -> None:
    ctx = make_context(party_member_ids=["player_2"])
    rows = {"player_1": _row("player_1", class_="warrior"), "player_2": _row("player_2")}
    db_mod, conn, queries, persistence = _deps(rows)

    await _request_ability_activation_impl(
        ctx,
        "warrior_devastating_strike",
        db_mod=db_mod,
        queries_mod=queries,
        persistence_mod=persistence,
    )

    queries.get_players_for_update.assert_awaited_once_with(["player_1"], conn=conn)
    persistence.update_player_resources.assert_awaited_once_with("player_1", stamina=7, focus=None, conn=conn)
