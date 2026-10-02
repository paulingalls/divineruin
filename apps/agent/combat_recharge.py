"""Persisted action budgets; the phase transaction owns all mutations."""

from action_contracts import validate_action_extensions, validate_recharge
from dice import roll


def action_key(action):
    return action["name"].casefold()


def capacity(action):
    spec = action["recharge"]
    return 1 if spec["kind"] == "roll" else spec["uses"]


def initialize(actor, round_number=1):
    for action in actor.action_pool:
        validate_action_extensions(action, f"{actor.id}.{action['name']}")
    names = [action_key(action) for action in actor.action_pool]
    if len(names) != len(set(names)):
        raise ValueError(f"{actor.id}: duplicate action names")
    limited = {action_key(a): a for a in actor.action_pool if "recharge" in a}
    if actor.action_ledger.keys() - limited.keys():
        raise ValueError(f"{actor.id}: unknown action ledger entry")
    for key, action in limited.items():
        validate_recharge(action["recharge"], f"{actor.id}.{key}.recharge")
        if key not in actor.action_ledger:
            actor.action_ledger[key] = {"remaining": capacity(action), "round": round_number}
        entry = actor.action_ledger[key]
        if (
            not isinstance(entry, dict)
            or type(entry.get("remaining")) is not int
            or not 0 <= entry["remaining"] <= capacity(action)
            or type(entry.get("round")) is not int
            or entry["round"] < 1
        ):
            raise ValueError(f"{actor.id}.{key}: malformed action ledger")


def available(actor, action):
    initialize(actor)
    return "recharge" not in action or actor.action_ledger[action_key(action)]["remaining"] > 0


def spend(actor, action, round_number):
    initialize(actor, round_number)
    if not available(actor, action):
        raise ValueError(f"{actor.id}: action {action['name']!r} unavailable")
    if "recharge" in action:
        actor.action_ledger[action_key(action)]["remaining"] -= 1
        actor.action_ledger[action_key(action)]["round"] = round_number


def recharge_round(state):
    for actor in state.participants:
        initialize(actor, state.round_number)
        if actor.is_fallen or actor.is_dead:
            continue
        for action in actor.action_pool:
            if "recharge" not in action:
                continue
            spec = action["recharge"]
            entry = actor.action_ledger[action_key(action)]
            if spec["kind"] == "encounter" or entry["round"] >= state.round_number:
                continue
            entry["round"] = state.round_number
            if spec["kind"] == "round":
                entry["remaining"] = capacity(action)
            elif entry["remaining"] == 0 and roll(f"1d{spec['die']}").total >= spec["threshold"]:
                entry["remaining"] = 1
