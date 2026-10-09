import pytest
from test_reaction_actor import _context, _deps, _row

from ability_tools import _request_ability_activation_unlocked


async def test_reaction_checkpoint_refuses_to_save_without_the_session_lock() -> None:
    ctx = _context()
    rows = {"player_2": _row("player_2")}
    db_mod, conn, queries, persistence = _deps(rows)
    with ctx.userdata._bind_authenticated_actor("player_2", 7, lambda *_args: None):
        actor = ctx.userdata.require_reaction_actor()
        with pytest.raises(RuntimeError, match="combat_state_lock"):
            await _request_ability_activation_unlocked(
                ctx,
                "guardian_intercept",
                db_mod=db_mod,
                queries_mod=queries,
                persistence_mod=persistence,
                player_id="player_2",
                reaction_actor=actor,
                prepared_spend={"ability_id": "guardian_intercept"},
            )
    conn.execute.assert_not_awaited()
