"""Ordered catalog references expand into independent ordinary held attacks."""

from combat_ability import _find_action
from declarations import Declaration, DeclarationType, resolve_declaration


def expand_declaration(actor, declaration):
    sequence = actor.multiattack_sequence
    if actor.is_ally or sequence is None or declaration.action != sequence["name"]:
        raise ValueError(f"{actor.id}: unknown multiattack {declaration.action!r}")
    strikes = declaration.strikes
    if strikes is None or len(strikes) != len(sequence["attacks"]):
        raise ValueError("multiattack requires exactly the authored strike selections")
    children = []
    for reference, selection in zip(sequence["attacks"], strikes, strict=True):
        action = _find_action(actor, reference)
        if action is None or selection["action"] != action["name"]:
            raise ValueError("multiattack strike action must match the ordered catalog reference")
        children.append(
            Declaration(type=DeclarationType.ATTACK, action=action["name"], target_id=selection["target_id"])
        )
    return children


def held_declarations(state, packet):
    declaration = resolve_declaration(state.pending_declarations[packet.actor_id])
    if declaration.type is not DeclarationType.MULTIATTACK:
        return [(dict(state.pending_declarations.get(packet.actor_id, {})), {})]
    actor = state.get_participant(packet.actor_id)
    return [
        (
            {"type": "attack", "action": child.action, "target_id": child.target_id},
            {"composite": declaration.action, "strike_index": index},
        )
        for index, child in enumerate(expand_declaration(actor, declaration))
    ]


def strike_summary(head, summary):
    if "composite" in head:
        summary.update(
            composite=head["composite"],
            strike_index=head["strike_index"],
            held_seq=head["seq"],
            execution_id=head["execution_id"],
            action=head["declaration"]["action"],
            target_id=head["declaration"]["target_id"],
        )
    return summary
