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

from acceptance.seeds import seed_player, seed_player_with_pools
from combat import _helpers as _combat_helpers

import db_mutations
import event_types as E
from combat_init import class_reaction_ids
from session_data import CombatParticipant, CombatState

_PLAYER_WEAPON = {"name": "Longsword", "damage": "1d8", "damage_type": "slashing", "properties": []}
_ENEMY_ACTION = {"name": "Scimitar", "damage": "1d6", "damage_type": "slashing", "properties": ["light"]}


def _d20(face: int):
    """A check_resolution.dice_roll stand-in that forces every d20 (attack + save) to `face`.

    _roll_d20_check reads only `.total`; damage rolls go through the separate
    check_resolution_attack.dice_roll, which this does NOT touch.
    """
    return SimpleNamespace(total=face)


def _damage_die(total: int):
    """A check_resolution_attack.dice_roll stand-in that forces every DAMAGE die to `total`.

    The other half of the seam `_d20` names: resolve_attack reads only `.total` off it. Needed
    where a test asserts a HALVED figure — a real 1d6 can roll 1, and `1 // 2 == 0` makes "halved"
    indistinguishable from "missed", so the guard could not red against its target defect.
    """
    return SimpleNamespace(total=total)


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


async def _start_combat(pool, player_id: str, state: CombatState, ctx, *, player_class: str | None = None) -> None:
    """Seed the real player row + persist the hand-built combat SSOT, then wire the in-memory state.

    Pass ``player_class`` for a scenario whose player must OWN an archetype ability and PAY for it:
    ``abilities.owns_ability`` gates a core/reaction ability on ``players.data.class`` matching the
    ability's archetype, and the activation deducts Stamina/Focus the default seed has no pools for.
    It seeds through ``seed_player_with_pools`` in the SAME call rather than topping the pools up
    afterwards, because ``seed_player`` replaces ``data`` wholesale. Omitted, the seed is unchanged.
    The class also gives the participant its reaction ids, as ``start_combat`` does; without them no
    window names a reaction the DM can pass.
    """
    if player_class is not None:
        player = state.get_participant(player_id)
        assert player is not None, f"{player_id!r} is not in the hand-built combat"
        player.reaction_ids = class_reaction_ids(player_class, player.level)
        player.has_reaction_ability = bool(player.reaction_ids)
        await seed_player_with_pools(pool, player_id=player_id, class_=player_class)
    else:
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


# The Beat-3 round driver is the SAME loop the fast lane uses (combat/_helpers), imported rather
# than copied: two copies of a stepping loop over a machine that is still growing stages is exactly
# the drift the sprint-046 helper extraction removed. `tests` is on pythonpath for both lanes
# (pyproject), and several capstones already import from combat._helpers.
_resolve_round = _combat_helpers._resolve_round
