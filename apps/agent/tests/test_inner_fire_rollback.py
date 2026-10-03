from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from sample_fixtures import make_mock_room
from test_draethar_inner_fire import _combat_ctx, _hollowed, _mocks, _player

from draethar_inner_fire import _inner_fire_impl


@pytest.mark.parametrize(
    "failure,hollowed",
    [("hp", False), ("combat", False), ("concentration", False), ("commit", False), ("combat", True), ("commit", True)],
)
async def test_failed_inner_fire_restores_live_state_and_allows_one_retry(failure, hollowed):
    ctx = _combat_ctx(hp_current=3, room=make_mock_room(), player_conditions=_hollowed(2) if hollowed else [])
    session = ctx.userdata
    original = session.combat_state
    before = original.to_dict()
    session.concentration.spell_id = "divine_bless"
    database, queries, hp, resonance, events, dice = _mocks(_player(hp_current=3), roll_total=6)
    conn = object()
    fail_now = True

    @asynccontextmanager
    async def transaction():
        yield conn
        if fail_now and failure == "commit":
            raise RuntimeError("injected commit failure")

    database.transaction = transaction

    async def write(*args, **kwargs):
        assert kwargs["conn"] is conn
        if fail_now:
            raise RuntimeError("injected write failure")

    if failure in {"hp", "combat"}:
        getattr(hp, "update_player_hp" if failure == "hp" else "save_combat_state").side_effect = write

    async def concentration(*args, **kwargs):
        assert kwargs["conn"] is conn
        assert kwargs["combat_state"] is not original
        session.concentration.spell_id = None
        if fail_now and failure == "concentration":
            raise RuntimeError("injected concentration failure")
        return "divine_bless"

    break_mod = MagicMock(break_concentration_on_damage=AsyncMock(side_effect=concentration))
    deps = dict(
        db_mod=database,
        queries_mod=queries,
        hp_mutations_mod=hp,
        resonance_mutations_mod=resonance,
        resonance_events_mod=events,
        dice_mod=dice,
        concentration_break_mod=break_mod,
    )
    with pytest.raises(RuntimeError, match="injected"):
        await _inner_fire_impl(ctx, **deps)
    assert session.combat_state is original and original.to_dict() == before
    assert session.resonance.current == 9
    assert session.concentration.spell_id == "divine_bless"
    assert session.party.primary.draethar_inner_fire_used is False
    events.publish_resonance_changed.assert_not_awaited()
    session.room.local_participant.publish_data.assert_not_awaited()

    fail_now = False
    await _inner_fire_impl(ctx, **deps)
    assert original.to_dict() == before
    assert session.combat_state is not original
    assert session.resonance.current == 6 and session.party.primary.draethar_inner_fire_used
    assert hp.save_combat_state.await_args.kwargs["conn"] is conn
    events.publish_resonance_changed.assert_awaited_once()
