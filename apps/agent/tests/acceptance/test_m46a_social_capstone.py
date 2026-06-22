"""Capstone: M4.6a Social Encounter Resolution end-to-end against a real Postgres testcontainer.

Stories 001-004 shipped the social surface in slices: the pure resolver (001), the check
mode="social" tool (002), NPC resistance content (003), and Diplomat combat de-escalation (004).
This capstone proves they COMPOSE on ONE seeded testcontainer (auto-marked `acceptance`), driving
the REAL pipeline against real DB writes:

- AC1: the check mode="social" tool reads an NPC's recorded disposition, resolves a persuasion
  check (disposition-as-DC), and PERSISTS the clamped shift back to npc_dispositions.
- AC2: a Diplomat declares de_escalate in a live combat phase; the contested gate + argument land
  and combat ENDS via the phase loop with outcome "deescalated" and an always-dramatic de_escalate
  roll on the HUD.

Determinism: the d20 seams are patched to face 20 (check_resolution.dice_roll for the social/
argument checks; combat_ability.dice_roll for the de-escalation CHA-vs-WIS contest). A seeded
Diplomat with charisma 18 (+4) beats a hand-built enemy's WIS 10 (+0) on equal d20s, and the
forced 20 clears the hostile argument DC (15 + 6). Each test uses a distinct player_id since the
testcontainer DB is shared.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from acceptance._capstone_helpers import _build_state, _d20, _dice_events, _enemy
from acceptance.seeds import seed_player, seed_player_with_pools
from sample_fixtures import make_context, make_mock_room

import combat_turn
import db
import db_mutations
import social_tools

_NPC_ID = "guildmaster_torin"  # a real seeded NPC (content/npcs.json)


async def _raise_charisma(pool, player_id: str, score: int) -> None:
    await pool.execute(
        "UPDATE players SET data = jsonb_set(data, '{attributes,charisma}', $2::jsonb) WHERE player_id = $1",
        player_id,
        json.dumps(score),
    )


async def test_m46a_social_check_shifts_and_persists_disposition(reset_db_pool: str) -> None:
    """AC1: check(mode="social") reads the recorded disposition, resolves, and persists the shift."""
    pool = await db.get_pool()
    player_id = "cap_m46a_social"
    await seed_player(pool, player_id=player_id, class_="diplomat")
    await _raise_charisma(pool, player_id, 18)
    # Start the NPC hostile (the hardest social DC) so a landed persuasion produces a visible shift.
    await pool.execute(
        "INSERT INTO npc_dispositions (npc_id, player_id, data) VALUES ($1, $2, $3::jsonb) "
        "ON CONFLICT (npc_id, player_id) DO UPDATE SET data = $3::jsonb",
        _NPC_ID,
        player_id,
        json.dumps({"disposition": "hostile"}),
    )

    ctx = make_context(player_id, room=make_mock_room())
    with patch("check_resolution.dice_roll", return_value=_d20(20)):
        result = json.loads(await social_tools._check_social_impl(ctx, _NPC_ID, "persuasion", "easy"))

    assert result["outcome"] == "success"
    assert result["previous_disposition"] == "hostile"
    assert result["new_disposition"] != "hostile", "a landed persuasion should soften a hostile NPC"
    assert result["disposition_shift"] > 0
    assert result["narrative_cue"]

    # The clamped new disposition round-trips to the npc_dispositions SSOT.
    row = await pool.fetchrow(
        "SELECT data FROM npc_dispositions WHERE npc_id = $1 AND player_id = $2", _NPC_ID, player_id
    )
    assert row is not None
    assert json.loads(row["data"])["disposition"] == result["new_disposition"]


async def test_m46a_diplomat_deescalation_ends_combat(reset_db_pool: str) -> None:
    """AC2: a Diplomat de_escalate declaration ends an active combat via the phase loop."""
    pool = await db.get_pool()
    player_id = "cap_m46a_deesc"
    # A Diplomat with a Focus pool (de_escalate costs 3) and the charisma to win the contest.
    await seed_player_with_pools(pool, player_id=player_id, class_="diplomat", focus_current=5)
    await _raise_charisma(pool, player_id, 18)

    state = _build_state("combat_cap_m46a_deesc", player_id, [_enemy("cultist_1", hp=10)])
    ctx = make_context(player_id, room=make_mock_room())
    await db_mutations.save_combat_state(state.combat_id, state.to_dict(), conn=pool)
    ctx.userdata.combat_state = state
    try:
        decls = {
            player_id: {"type": "ability", "action": "de_escalate", "target_id": "cultist_1"},
            "cultist_1": {"type": "attack", "action": "Scimitar", "target_id": player_id},
        }
        await combat_turn._declare_phase_impl(ctx, decls)
        with (
            patch("check_resolution.dice_roll", return_value=_d20(20)),
            patch("combat_ability.dice_roll", return_value=_d20(20)),
        ):
            result = await combat_turn._resolve_phase_impl(ctx)

        assert isinstance(result, tuple), "a successful de-escalation fires end_combat and hands back"
        _agent, json_str = result
        payload = json.loads(json_str)
        assert payload["outcome"] == "deescalated"

        # The de-escalation roll surfaced on the HUD as an always-dramatic de_escalate moment.
        deesc = [e for e in _dice_events(ctx.userdata.room) if e.get("roll_type") == "de_escalate"]
        assert deesc, "a de_escalate DICE_ROLL was published"
        assert deesc[0]["dramatic"] is True and deesc[0]["context"] == "de_escalate"

        # The combat SSOT was torn down.
        assert ctx.userdata.combat_state is None
        assert await pool.fetchrow("SELECT 1 FROM combat_instances WHERE combat_id = $1", state.combat_id) is None
    finally:
        await db_mutations.delete_combat_state(state.combat_id, conn=pool)
