"""Settle a marshal's spoken temporary HP grant in the combat transaction."""

from types import ModuleType

import asyncpg

import combat_martial
import combat_spatial
import communication_voice_rules
import temp_hp
from combat_ability_gate import DeclaredAbility
from combat_participant import CombatParticipant
from combat_state import CombatState
from patron_synergy_combat import ORENTHEL_MARSHAL_RALLY, marshal_rally_bonus
from rules_engine import attribute_modifier


async def resolve(
    state: CombatState,
    actor: CombatParticipant,
    resolved: DeclaredAbility,
    *,
    conn: asyncpg.Connection,
    queries: ModuleType,
) -> dict:
    ability = resolved[0]
    player = await queries.get_player(actor.id, conn=conn)
    if player is None:
        raise ValueError(f"Rally marshal {actor.id} has no player row")
    bonus = marshal_rally_bonus(player)
    amount = temp_hp.validate(attribute_modifier(player["attributes"]["charisma"]) + player["level"] + bonus)

    spatial = combat_spatial.require_spatial(state)
    source = combat_spatial.position(spatial, actor.id)
    candidates = [p for p in state.participants if p.is_ally and p.id != actor.id]
    outcomes = {}
    recipients = []
    for ally in candidates:
        reason = None
        if not combat_spatial.inside(source, combat_spatial.position(spatial, ally.id), 30):
            reason = "beyond 30 ft"
        elif not communication_voice_rules.can_hear(state, ally.id):
            reason = "cannot hear"
        else:
            recipients.append(ally)
        outcomes[ally.id] = {
            "recipient_id": ally.id,
            "name": ally.name,
            "amount": 0 if reason else amount,
            "granted": 0,
            "temp_hp": ally.temp_hp,
            "reason": reason,
        }

    receipt = {
        "actor_id": actor.id,
        "resolved": bool(recipients),
        "declaration_type": "ability",
        "action": ability.id,
        "name": ability.name,
        "target_ids": [ally.id for ally in recipients],
        "effect_resolution": "engine",
        "effect": ability.effect,
        "rally_results": list(outcomes.values()),
    }
    if not recipients:
        return {
            **receipt,
            "reason": "No other ally within 30 ft can hear Rally.",
            "deducted": {"focus": 0, "stamina": 0},
        }

    await combat_martial.pay(actor.id, resolved, queries=queries, conn=conn)
    players = await queries.get_players_for_update([ally.id for ally in recipients if ally.type == "player"], conn=conn)
    for ally in recipients:
        if ally.type == "player":
            before, after = await temp_hp.grant(ally.id, players[ally.id], amount, participant=ally, conn=conn)
        else:
            before = ally.temp_hp
            ally.temp_hp = after = max(before, amount)
        outcomes[ally.id].update(granted=after - before, temp_hp=after)
    return {
        **receipt,
        "narration_cue": ability.narration_cue,
        "deducted": {"focus": ability.cost.focus, "stamina": ability.cost.stamina},
        **({"synergy_clause_id": ORENTHEL_MARSHAL_RALLY, "synergy_clause_name": "Rally at Dawn"} if bonus else {}),
    }
