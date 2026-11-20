"""Apply the Wildmother's terrain-typed gift through normal combat damage."""

from copy import deepcopy

from asyncpg import Connection
from livekit.agents.llm import ToolError

import combat_damage
import dice
import still_encounter
from combat_damage_results import AutomaticDamageResult
from combat_events import EventSink
from combat_participant import CombatParticipant
from combat_state import CombatState
from combat_terrain import resolve_terrain
from patron_combat_edges import WILDMOTHERS_WRATH, require_complete_round
from session_data import SessionData
from terrain import WRATH_DAMAGE_TYPES, TerrainType, is_natural


def _living(participant: CombatParticipant) -> bool:
    return participant.hp_current > 0 and not participant.is_fallen and not participant.is_dead


def _recipients(state: CombatState) -> tuple[list[CombatParticipant], list[str]]:
    hidden = still_encounter.hidden_ids(state)
    still = still_encounter.protected_ids(state)
    choir = state.choir_encounter
    targets = []
    spared = []
    hidden_count = 0
    for foe in state.participants:
        if foe.is_ally or not _living(foe):
            continue
        if foe.id in still:
            if foe.id in hidden:
                hidden_count += 1
            else:
                spared.append(f"{foe.name} is protected by the Still's anchors.")
        elif choir is not None and foe.id == choir["owner_id"] and choir["phase"] != "exposed":
            spared.append(f"{foe.name} is protected until its core is exposed.")
        else:
            targets.append(foe)
    if hidden_count:
        spared.append(f"The Still shelters {hidden_count} unrevealed anchor{'' if hidden_count == 1 else 's'}.")
    return targets, spared


async def wildmothers_wrath(
    session: SessionData, actor_id: str, *, conn: Connection, sink: EventSink
) -> tuple[CombatState, dict]:
    state = session.combat_state
    if state is None:
        raise ToolError("Wildmother's Wrath can only be used in combat.")
    require_complete_round(state, WILDMOTHERS_WRATH)
    working = deepcopy(state)
    actor = working.get_participant(actor_id)
    if actor is None or actor.type != "player" or not _living(actor):
        raise ToolError("Wildmother's Wrath requires a living acting player in this fight.")
    terrain = await resolve_terrain(session, combat_state=working)
    if not is_natural(terrain):
        raise ToolError(f"Wildmother's Wrath requires natural ground. The fight is in {terrain} terrain.")

    targets, spared = _recipients(working)
    if not targets:
        raise ToolError("Wildmother's Wrath has no living unprotected foe. " + " ".join(spared))

    damage_type = WRATH_DAMAGE_TYPES[TerrainType(terrain)]
    roll = dice.roll("3d8")
    action = {"name": "Wildmother's Wrath", "magical": True}
    blow = AutomaticDamageResult(roll.total, damage_type)
    receipts = []
    narration = [
        f"Narrate the land rising in {terrain.replace('_', ' ')}. {roll.notation} rolled {roll.total} {damage_type}."
    ]
    for foe in targets:
        receipt = await combat_damage.apply_attack_result(
            session, actor, action, foe, blow, foe.ac, combat_state=working, conn=conn, sink=sink, publish_roll=False
        )
        damage = receipt["damage"]
        fallen = receipt["target_fallen"]
        receipts.append(
            {"id": foe.id, "name": foe.name, "damage": damage, "target_fallen": fallen, "target_dead": foe.is_dead}
        )
        outcome = "dies" if foe.is_dead else "falls" if fallen else "stays standing"
        narration.append(f"{foe.name} takes {damage} {damage_type} and {outcome}.")
    narration.extend(spared)
    if not any(not foe.is_ally and _living(foe) for foe in working.participants):
        narration.append("No foe is left standing.")
    return working, {
        "terrain": terrain,
        "damage_type": damage_type,
        "roll": {"notation": roll.notation, "total": roll.total},
        "targets": receipts,
        "spared": spared,
        "dm_cue": " ".join(narration),
    }
