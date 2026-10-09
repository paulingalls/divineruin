"""The shared atomic declaration gate, including each selected composite strike."""

import combat_grapple
import combat_spatial_declarations
import combat_voice_rules
from combat_ability import _find_action, condition_ability
from combat_ability_gate import declared_ability
from combat_action_availability import require_available
from condition_restrictions import cannot_act, declaration_costs, speed_zero
from declarations import DeclarationType, ManeuverIntent
from encounter_actions import action_kind


def validate_declaration(next_state, actor_id, declaration, persisted_declarations):
    actor = next_state.get_participant(actor_id)
    if actor is None:
        participant_ids = [participant.id for participant in next_state.participants]
        raise ValueError(f"Unknown actor {actor_id!r}; participants: {participant_ids}")
    if declaration.type is DeclarationType.MULTIATTACK:
        from combat_multiattack import expand_declaration

        for child in expand_declaration(actor, declaration):
            validate_declaration(next_state, actor_id, child, persisted_declarations)
        return
    import choir_encounter

    choir_encounter.guard_declaration(next_state, actor_id, declaration)
    combat_voice_rules.guard_declaration(next_state, actor, declaration)
    if combat_spatial_declarations.is_move(declaration):
        combat_spatial_declarations.validate_move(next_state, actor_id, declaration)
        return
    if blocked := cannot_act(actor.conditions):
        raise ValueError(f"{actor.name} ({actor.id}) is {blocked[0]}; omit that actor and narrate the helplessness")
    if declaration.type is DeclarationType.RETREAT and (blocked := speed_zero(actor.conditions)):
        raise ValueError(f"{actor.name} ({actor.id}) is {blocked[0]} and cannot retreat")
    if declaration.type in (DeclarationType.ATTACK, DeclarationType.MANEUVER):
        target = next_state.get_participant(declaration.target_id) if declaration.target_id else None
        if target is None:
            raise ValueError(f"Unknown target {declaration.target_id!r} for {actor.name} ({actor.id})")
        # Only the stand MANEUVER may name its own actor: a self-targeted ATTACK resolves
        # as a real swing against the actor's own AC and damage (combat_packet attack path).
        self_stand = declaration.type is DeclarationType.MANEUVER and target.id == actor.id
        if not self_stand and target.is_ally == actor.is_ally:
            raise ValueError(
                f"{actor.name} ({actor.id}) cannot target {target.name} ({target.id}) with {declaration.type}"
            )
        if declaration.type is DeclarationType.MANEUVER and combat_grapple.grappler_id(actor.conditions) == target.id:
            persisted_declarations[actor_id]["maneuver_intent"] = ManeuverIntent.ESCAPE
    if (
        declaration.type is DeclarationType.MANEUVER
        and declaration.target_id == actor.id
        and "prone" not in declaration_costs(actor.conditions)
    ):
        raise ValueError(f"{actor.name} ({actor.id}) is not prone and cannot stand")
    if declaration.type is DeclarationType.ATTACK and _find_action(actor, declaration.action) is None:
        available = [action["name"] for action in actor.action_pool]
        raise ValueError(
            f"Unknown attack action {declaration.action!r} for {actor.name} ({actor.id}); "
            f"available actions: {available}"
        )
    pool_action = _find_action(actor, declaration.action)
    if pool_action is not None and declaration.type in (DeclarationType.ATTACK, DeclarationType.ABILITY):
        require_available(actor, pool_action)
    if declaration.type is DeclarationType.ABILITY and actor.type == "player":
        resolved_ability = declared_ability(declaration.action)
        if resolved_ability is not None and condition_ability(resolved_ability) is None:
            ability, _variant = resolved_ability
            if ability.spell_id is not None:
                raise ValueError(f"{declaration.action} is an ability alias; declare {ability.spell_id} in combat")
            raise ValueError(f"{declaration.action} is not declarable in combat")
    if declaration.type is DeclarationType.ABILITY and actor.type != "player":
        pool_action = _find_action(actor, declaration.action)
        if (
            actor.is_ally
            or pool_action is None
            or (
                not pool_action.get("applies_condition")
                and action_kind(pool_action) not in ("healing", "prepare_attack", "charm", "silence")
            )
        ):
            available = [action["name"] for action in actor.action_pool]
            raise ValueError(
                f"{actor.name} ({actor.id}) cannot declare ability {declaration.action!r}: only players "
                f"cast abilities, and an enemy only its condition actions; declare an attack from {available}"
            )
