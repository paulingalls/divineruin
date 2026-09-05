"""Shared combat-capstone harness helpers for the testcontainer acceptance lane.

Extracted from the M4.x combat capstones (test_m4*_capstone.py) which each hand-built the same
CombatState / CombatParticipant scaffolding (concern 3fe548d9038a). One canonical set keeps the
capstones consistent: each test seeds a real player + combat SSOT, drives declare/resolve through
the live tools, and patches only the d20 seam (check_resolution.dice_roll) so the real resolvers
run end to end. Per-capstone result extractors (e.g. a DICE_ROLL filter vs a resolve-packet
reader) stay in their own files; this module owns only the construction + generic event helpers.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from acceptance.seeds import seed_player

import db_mutations
import event_types as E
from session_data import CombatParticipant, CombatState

_PLAYER_WEAPON = {"name": "Longsword", "damage": "1d8", "damage_type": "slashing", "properties": []}
_ENEMY_ACTION = {"name": "Scimitar", "damage": "1d6", "damage_type": "slashing", "properties": ["light"]}


def _d20(face: int):
    """A check_resolution.dice_roll stand-in that forces every d20 (attack + save) to `face`.

    _roll_d20_check reads only `.total`; damage rolls go through the separate
    check_resolution_attack.dice_roll, which this does NOT touch.
    """
    return SimpleNamespace(total=face)


def _player(player_id: str, hp: int = 100) -> CombatParticipant:
    return CombatParticipant(
        id=player_id,
        name="Kael",
        type="player",
        initiative=15,  # acts before the enemies so its reveal lands first
        hp_current=hp,
        hp_max=hp,
        ac=14,
        action_pool=[_PLAYER_WEAPON],
    )


def _enemy(enemy_id: str, hp: int) -> CombatParticipant:
    return CombatParticipant(
        id=enemy_id,
        name=enemy_id.replace("_", " ").title(),
        type="enemy",
        initiative=12,
        hp_current=hp,
        hp_max=max(hp, 7),
        ac=10,  # low AC so a forced mid d20 reliably hits
        action_pool=[_ENEMY_ACTION],
        xp_value=50,
    )


def _build_state(
    combat_id: str, player_id: str, enemies: list[CombatParticipant], *, first_attack_resolved: bool = False
) -> CombatState:
    """A declaration-beat CombatState with a player + N enemies, ready for declare/resolve."""
    participants = [_player(player_id), *enemies]
    return CombatState(
        combat_id=combat_id,
        participants=participants,
        initiative_order=[player_id, *[e.id for e in enemies]],
        round_number=1,
        current_turn_index=0,
        location_id="accord_guild_hall",
        beat="declaration",
        first_attack_resolved=first_attack_resolved,
    )


async def _start_combat(pool, player_id: str, state: CombatState, ctx) -> None:
    """Seed the real player row + persist the hand-built combat SSOT, then wire the in-memory state."""
    await seed_player(pool, player_id=player_id, location_id="accord_guild_hall")
    await db_mutations.save_combat_state(state.combat_id, state.to_dict(), conn=pool)
    ctx.userdata.combat_state = state


async def _declare_attacks(ctx, player_id: str, target_id: str, enemy_ids: list[str]) -> None:
    import combat_turn

    decls = {player_id: {"type": "attack", "action": "Longsword", "target_id": target_id}}
    for eid in enemy_ids:
        decls[eid] = {"type": "attack", "action": "Scimitar", "target_id": player_id}
    await combat_turn._declare_phase_impl(ctx, decls)


def _dice_events(room) -> list[dict]:
    out = []
    for call in room.local_participant.publish_data.call_args_list:
        payload = json.loads(call[0][0])
        if payload.get("type") == E.DICE_ROLL:
            out.append(payload)
    return out


def _player_attack_events(room) -> list[dict]:
    return [e for e in _dice_events(room) if e.get("roll_type") == "attack" and e.get("attacker") == "Kael"]


async def _resolve_round(ctx, *, max_calls: int = 64, **deps) -> Any:
    """Drive resolve_phase to the END of the round: allies, then every held enemy action, then
    the wrap (M29, story-016).

    Beat 3 holds the enemy blows behind reaction windows, so ONE resolve_phase call no longer
    resolves a whole phase — it resolves the ally band and then pauses once per window. Every
    capstone that made one call and asserted on the whole phase changes by one line: call this.

    ``max_calls`` bounds the loop rather than sizing it: a round costs one call for the ally band
    plus up to two per held enemy action plus one for the wrap, so a 10-enemy encounter is ~22.
    The bound exists to catch a pump that never terminates, not to predict the encounter.

    Typed ``Any`` rather than ``dict | tuple`` on purpose: which shape comes back is decided at
    RUNTIME by whether the round ended the fight, every caller disambiguates at its own call site
    (``isinstance(result, tuple)``), and a declared union would make ~60 correct subscripts a type
    error without catching a single real one.

    Returns the FINAL result — the loop-back JSON (as a dict) or the end-of-combat handoff tuple —
    with ``packets`` accumulated across every call. Fails loud rather than returning a
    half-resolved round: never stops with a window still open, never spins past ``max_calls``.
    """
    import combat_turn

    packets: list[dict] = []
    for _ in range(max_calls):
        result = await combat_turn._resolve_phase_impl(ctx, **deps)
        if isinstance(result, tuple):
            return result
        payload = json.loads(result)
        packets.extend(payload.get("packets", []))
        if payload.get("next", {}).get("waiting_on") is None and payload["beat"] == "declaration":
            payload["packets"] = packets
            return payload
    state = ctx.userdata.combat_state
    raise AssertionError(
        f"the round did not terminate within {max_calls} resolve_phase calls "
        f"(beat={state.beat if state else None}, "
        f"held={[h['actor_id'] for h in state.held_actions] if state else None}, "
        f"open_window={state.open_window if state else None})"
    )
