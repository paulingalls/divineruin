"""Capstone: M4.6a Social Encounter Resolution end-to-end against a real Postgres testcontainer.

Stories 001-004 shipped the social surface in slices: the pure resolver (001), the check
mode="social" tool (002), NPC resistance content (003), and Diplomat combat de-escalation (004).
This capstone proves they COMPOSE on ONE seeded testcontainer (auto-marked `acceptance`), driving
the REAL pipeline against real DB writes:

- AC1: the check mode="social" tool reads an NPC's recorded disposition, resolves a persuasion
  check (disposition-as-DC), and PERSISTS the clamped shift back to npc_dispositions.
- AC2: a Diplomat declares de_escalate over several live combat phases; the M15 Tier-3 scene
  accumulates a per-enemy disposition shift (resolve_argument_round + DeEscalationState) and combat
  ENDS via the phase loop with outcome "deescalated" and an always-dramatic de_escalate roll on the
  HUD once the enemy crosses the +2 surrender threshold.

Determinism: the argument d20 seam is patched to face 20 (check_resolution.dice_roll). A seeded
Diplomat with charisma 18 argues a `cowardly` foe — vulnerable to a `threat` argument (-3 DC) — down
over a couple of rounds within the MAX_DEESCALATION_ROUNDS cap. (M15 replaced the single-round
CHA-vs-WIS contest, so combat_ability.dice_roll is no longer a seam.) Each test uses a distinct
player_id since the testcontainer DB is shared.
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
    """AC2: a Diplomat argues an enemy down over multiple rounds; the M15 Tier-3 scene accumulates
    a per-enemy disposition shift and combat ENDS "deescalated" once the enemy crosses +2.

    M15 (story-002) replaced the single-round contested-gate MVP with a multi-round cumulative scene
    (combat_resolution.resolve_argument_round + DeEscalationState). The Diplomat spends 3 Focus per
    round and shifts the enemy by its own resistance profile; a `cowardly` foe is VULNERABLE to a
    `threat` argument, so a forced 20 lands progress each round until it stands down within the
    MAX_DEESCALATION_ROUNDS cap. Determinism: check_resolution.dice_roll (the persuasion roll) is
    pinned to 20; there is no longer a combat_ability CHA-vs-WIS contest to patch."""
    pool = await db.get_pool()
    player_id = "cap_m46a_deesc"
    # A Diplomat with enough Focus for several rounds (3/round) and the charisma to argue well.
    await seed_player_with_pools(pool, player_id=player_id, class_="diplomat", focus_current=12)
    await _raise_charisma(pool, player_id, 18)

    # A cowardly foe is vulnerable to a `threat` argument (social_resolution.ARGUMENT_RESISTANCE),
    # so each landed round moves its disposition and the scene reliably reaches +2 within the cap.
    cultist = _enemy("cultist_1", hp=10)
    cultist.resistance_tags = ["cowardly"]
    state = _build_state("combat_cap_m46a_deesc", player_id, [cultist])
    ctx = make_context(player_id, room=make_mock_room())
    await db_mutations.save_combat_state(state.combat_id, state.to_dict(), conn=pool)
    ctx.userdata.combat_state = state
    try:
        decls = {
            player_id: {
                "type": "ability",
                "action": "de_escalate",
                "argument_type": "threat",
                "target_id": "cultist_1",
            },
            "cultist_1": {"type": "attack", "action": "Scimitar", "target_id": player_id},
        }
        # Argue round by round until the enemy surrenders (combat_turn hands back a tuple on end).
        result = None
        for _round in range(4):  # MAX_DEESCALATION_ROUNDS
            await combat_turn._declare_phase_impl(ctx, decls)
            with patch("check_resolution.dice_roll", return_value=_d20(20)):
                result = await combat_turn._resolve_phase_impl(ctx)
            if isinstance(result, tuple):
                break

        assert isinstance(result, tuple), "the accumulated de-escalation fires end_combat and hands back"
        _agent, json_str = result
        payload = json.loads(json_str)
        assert payload["outcome"] == "deescalated"

        # Each de-escalation round surfaced on the HUD as an always-dramatic de_escalate moment.
        deesc = [e for e in _dice_events(ctx.userdata.room) if e.get("roll_type") == "de_escalate"]
        assert deesc, "a de_escalate DICE_ROLL was published"
        assert deesc[0]["dramatic"] is True and deesc[0]["context"] == "de_escalate"

        # The combat SSOT was torn down.
        assert ctx.userdata.combat_state is None
        assert await pool.fetchrow("SELECT 1 FROM combat_instances WHERE combat_id = $1", state.combat_id) is None
    finally:
        await db_mutations.delete_combat_state(state.combat_id, conn=pool)
