"""Registered combat drivers for rally receipts."""

from test_encounter_facts_damage import GOBLIN, Fight, goblin_strike

CLAUSE = "zhael_moment_to_rally"
INTERCEDE = "marshal_interceding_order"


def bonus(source: str, ally: str) -> dict:
    return {"clause_id": CLAUSE, "marshal_id": source, "ally_id": ally, "bonus": 1}


def save_action(fight: Fight, ally: str, *, save: str = "WIS") -> dict:
    enemy = fight.session.combat_state.get_participant(GOBLIN)
    assert enemy is not None
    enemy.action_pool = [
        *[action for action in enemy.action_pool if action["name"] != "Rally Test Save"],
        {
            "name": "Rally Test Save",
            "save": save,
            "dc": 11,
            "damage": "1d4",
            "damage_type": "cold",
            "half_on_success": True,
        },
    ]
    return {**goblin_strike(GOBLIN, ally), "action": "Rally Test Save"}


def pending(state, ally: str, *sources: str) -> None:
    state.encounter_facts["once_spent"][CLAUSE] = list(sources)
    state.encounter_facts["rally_pending"].update(dict.fromkeys(sources, ally))


def ability(actor_id: str, action: str, *targets: str) -> dict:
    return {
        "kind": "ability",
        "actor_id": actor_id,
        "action": action,
        "targets": list(targets),
        "argument_type": "",
        "reshape": [],
    }
