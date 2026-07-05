"""Capstone: M15 Tier-3 structured de-escalation scene, end-to-end on a real Postgres testcontainer.

Stories 001-003 shipped the scene in slices: 001 the pure per-round resolver + DeEscalationState,
002 the in-combat multi-round GROUP orchestration (per-enemy resistance profiles, whole-group +2
surrender), 003 the fallen-ally combat-end outcome (deescalated stabilizes a savable fallen ally).
This capstone proves they COMPOSE on ONE seeded testcontainer, driving the REAL phase loop:

- A Diplomat argues a 2-enemy hostile GROUP down over MULTIPLE rounds. Each enemy shifts INDEPENDENTLY
  by its own resistance profile — a `cowardly` foe (vulnerable to a `threat` argument) folds faster
  than a `greedy` one (unmoved by it, threat-neutral) — until the WHOLE living group crosses the +2 surrender
  threshold and combat ends "deescalated".
- A DOWNED savable ally, present in the party, is STABILIZED to 1 HP on that deescalated end (never
  killed), proving the story-003 combat-end outcome fires from the real phase loop.

Determinism: the argument d20 seam (check_resolution.dice_roll) is pinned to 20. The engine never
auto-rolls death saves (only the DM request_death_save tool does, never called here) and death saves
use a different seam (combat_resolution.dice_roll), so the fallen ally rolls ZERO death saves and
stays savable-fallen every round. Distinct player_ids since the testcontainer DB is shared.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from acceptance._capstone_helpers import _d20, _dice_events, _enemy, _player
from acceptance.seeds import seed_player, seed_player_with_pools
from sample_fixtures import make_context, make_mock_room

import combat_turn
import db
import db_mutations
import db_queries
from caster_state import ConcentrationState, ResonanceTrack, VeilWardState
from party_state import PartyMember
from session_data import CombatParticipant, CombatState

_PRIMARY = "cap_m15_primary"
_ALLY = "cap_m15_ally"
_ANCHOR = "millhaven"  # a real seeded settlement (present on the ally row; unused by the stabilize path)
_MAX_ROUNDS = 4  # combat_ability.MAX_DEESCALATION_ROUNDS


async def _raise_charisma(pool, player_id: str, score: int) -> None:
    await pool.execute(
        "UPDATE players SET data = jsonb_set(data, '{attributes,charisma}', $2::jsonb) WHERE player_id = $1",
        player_id,
        json.dumps(score),
    )


async def _fell_ally(pool, player_id: str) -> None:
    """Put the ally row into a downed-but-savable state (hp 0, no recorded deaths)."""
    await pool.execute(
        "UPDATE players SET data = jsonb_set(jsonb_set(data, '{hp}', $2::jsonb),"
        " '{last_rested_settlement_id}', $3::jsonb) WHERE player_id = $1",
        player_id,
        json.dumps({"current": 0, "max": 40}),
        json.dumps(_ANCHOR),
    )


def _fallen_ally_participant(player_id: str) -> CombatParticipant:
    return CombatParticipant(
        id=player_id,
        name="Bren",
        type="player",
        initiative=14,
        hp_current=0,
        hp_max=40,
        ac=14,
        is_fallen=True,
        is_dead=False,
        death_save_failures=0,  # savable — not terminally down
    )


async def test_m15_group_deescalation_stabilizes_fallen_ally(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    # Primary: a Diplomat with Focus for several rounds (3/round) and the charisma to argue.
    await seed_player_with_pools(pool, player_id=_PRIMARY, class_="diplomat", focus_current=10)
    await _raise_charisma(pool, _PRIMARY, 26)
    # Ally: a second party member, downed but savable.
    await seed_player(pool, player_id=_ALLY, class_="skirmisher")
    await _fell_ally(pool, _ALLY)

    # A GROUP of two hostile enemies with DIFFERING resistance profiles vs a `threat` argument:
    # `cowardly` = vulnerable (-3 DC, folds in one round); `greedy` = unmoved by threats (0 DC, needs
    # a second round). (A fully threat-RESISTANT foe, e.g. `honorable` at +3 DC, is unpersuadable at
    # hostile given the proficiency-mod ceiling — the reviewer's "unpersuadable enemy" assumption — so
    # the slower enemy here is threat-neutral, not threat-resistant.)
    enemy_a = _enemy("cultist_a", hp=10)
    enemy_a.resistance_tags = ["cowardly"]
    enemy_b = _enemy("cultist_b", hp=10)
    enemy_b.resistance_tags = ["greedy"]

    primary_part = _player(_PRIMARY)
    ally_part = _fallen_ally_participant(_ALLY)
    state = CombatState(
        combat_id="combat_cap_m15",
        participants=[primary_part, ally_part, enemy_a, enemy_b],
        initiative_order=[_PRIMARY, _ALLY, "cultist_a", "cultist_b"],
        round_number=1,
        current_turn_index=0,
        location_id="accord_guild_hall",
        beat="declaration",
    )

    ctx = make_context(_PRIMARY, room=make_mock_room())
    # The ally must sit in the party so _end_combat_db's per-member reconcile finds its row.
    ctx.userdata.party.members.append(
        PartyMember(
            player_id=_ALLY,
            resonance=ResonanceTrack(),
            veil_ward=VeilWardState(),
            concentration=ConcentrationState(),
        )
    )
    await db_mutations.save_combat_state(state.combat_id, state.to_dict(), conn=pool)
    ctx.userdata.combat_state = state

    try:
        decls = {
            _PRIMARY: {
                "type": "ability",
                "action": "de_escalate",
                "argument_type": "threat",
                "target_id": "cultist_a",
            },
            "cultist_a": {"type": "attack", "action": "Scimitar", "target_id": _PRIMARY},
            "cultist_b": {"type": "attack", "action": "Scimitar", "target_id": _PRIMARY},
        }

        # Argue round by round until the whole group surrenders (combat_turn hands back a tuple on end).
        result = None
        rounds = 0
        shifts_mid_scene: dict[str, int] | None = None
        for _round in range(_MAX_ROUNDS):
            await combat_turn._declare_phase_impl(ctx, decls)
            with patch("check_resolution.dice_roll", return_value=_d20(20)):
                result = await combat_turn._resolve_phase_impl(ctx)
            rounds += 1
            if isinstance(result, tuple):
                break
            # Capture per-enemy cumulative shift on the first non-ending round (state still live).
            if shifts_mid_scene is None:
                shifts_mid_scene = dict(ctx.userdata.combat_state.deescalation_scene.cumulative_shift)

        # story-002 + 001: the whole living group crossed +2 and combat ended deescalated.
        assert isinstance(result, tuple), "the accumulated group de-escalation fires end_combat"
        _agent, json_str = result
        payload = json.loads(json_str)
        assert payload["outcome"] == "deescalated"

        # Genuinely multi-round (the resistant enemy needs more than one round).
        assert rounds >= 2, f"expected a multi-round scene, ended in {rounds}"

        # story-001/002 per-enemy INDEPENDENCE: same argument, different resistance profile — the
        # vulnerable cowardly foe accumulates more than the threat-neutral greedy one mid-scene.
        assert shifts_mid_scene is not None
        assert shifts_mid_scene["cultist_a"] > shifts_mid_scene["cultist_b"], shifts_mid_scene

        # story-003: the downed savable ally is STABILIZED to 1 HP on the deescalated end (not killed).
        ally = await db_queries.get_player(_ALLY, conn=pool)
        assert ally is not None
        assert ally["hp"]["current"] == 1, "the fallen ally is stabilized to 1 HP on a deescalated end"
        # A kill (fled/defeat) would record a death via trigger_character_death; a stabilize leaves the
        # count at 0 (or absent on this seed). Either way, no death was recorded.
        assert (ally.get("death_history") or {}).get("count", 0) == 0, "stabilized, not killed"

        # M4.5: the de-escalation surfaced as an always-dramatic de_escalate moment on the HUD.
        deesc = [e for e in _dice_events(ctx.userdata.room) if e.get("roll_type") == "de_escalate"]
        assert deesc, "a de_escalate DICE_ROLL was published"
        assert deesc[0]["dramatic"] is True and deesc[0]["context"] == "de_escalate"

        # The combat SSOT was torn down.
        assert ctx.userdata.combat_state is None
        assert await pool.fetchrow("SELECT 1 FROM combat_instances WHERE combat_id = $1", state.combat_id) is None
    finally:
        await db_mutations.delete_combat_state(state.combat_id, conn=pool)
        await pool.execute("DELETE FROM players WHERE player_id = ANY($1)", [_PRIMARY, _ALLY])
