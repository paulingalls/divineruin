from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

import event_types as E
from progression_tools import _award_divine_favor_core


@pytest.mark.parametrize(
    "level, amount, expected, delta, refresh",
    [(95, 10, 100, 5, True), (100, 5, 100, 0, False), (10, -3, 7, -3, False), (2, -5, 0, -2, False)],
)
async def test_resolve_persists_real_delta_and_only_refreshes_on_gain(level, amount, expected, delta, refresh):
    prior = "2026-09-01T00:00:00+00:00"
    activities = MagicMock()
    activities.get_divine_favor = AsyncMock(
        return_value={
            "patron": "kaelen",
            "level": level,
            "max": 100,
            "last_whisper_level": 4,
            "last_served_at": prior,
        }
    )
    mutations = MagicMock()
    mutations.update_divine_favor = AsyncMock()
    conn = MagicMock()
    pending = []
    before = datetime.now(UTC)

    grant = await _award_divine_favor_core(
        "player_1",
        amount,
        "test",
        conn=conn,
        pending_events=pending,
        mutations=mutations,
        activities=activities,
    )

    after = datetime.now(UTC)
    assert grant is not None and grant.new_level == expected
    mutations.update_divine_favor.assert_awaited_once()
    assert mutations.update_divine_favor.call_args.args == ("player_1", expected)
    kwargs = mutations.update_divine_favor.call_args.kwargs
    assert kwargs["conn"] is conn
    if refresh:
        assert before <= datetime.fromisoformat(kwargs["last_served_at"]) <= after
    else:
        assert "last_served_at" not in kwargs
    assert pending[0][0] == E.DIVINE_FAVOR_CHANGED
    payload = pending[0][1]
    assert set(payload) == {
        "new_level",
        "previous_level",
        "patron_id",
        "last_whisper_level",
        "amount",
        "reason",
        "max",
        "player_id",
    }
    assert payload["amount"] == delta
    assert payload["new_level"] == expected
