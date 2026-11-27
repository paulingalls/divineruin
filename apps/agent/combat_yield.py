"""Party surrender for the lifetime of a combat encounter."""

from combat_participant import CombatParticipant


def resolve(actor: CombatParticipant) -> dict:
    actor.yielded = True
    return {
        "actor_id": actor.id,
        "resolved": True,
        "declaration_type": "yield",
        "yielded": True,
        "dm_cue": f"{actor.name} spends their action to yield.",
    }


def end(actor: CombatParticipant) -> dict:
    if not actor.yielded:
        return {}
    actor.yielded = False
    return {"yield_ended": True, "yielded": False, "dm_cue": f"{actor.name} breaks their surrender."}
