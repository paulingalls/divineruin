"""The shared atomic declaration gate, including each selected composite strike."""

import architect_encounter
import architect_entomb
import combat_grapple
import combat_melee_approach
import combat_spatial_declarations
import combat_voice_rules
import still_encounter
from action_contracts_still import STILL_ZONE_KINDS
from combat_ability import _find_action, condition_ability
from combat_ability_gate import declared_ability
from combat_action_availability import require_available
from combat_structures import action_has_direct_line, require_line
from condition_restrictions import cannot_act, declaration_costs, speed_zero
from declarations import DeclarationType, ManeuverIntent
from encounter_actions import action_kind


def validate_declaration(next_state, actor_id, declaration, persisted_declarations):
    if declaration.reshape:
        from architect_reshape import proposed_state

        next_state = proposed_state(next_state, actor_id, declaration.reshape)
    actor = next_state.get_participant(actor_id)
    if actor is None:
        participant_ids = [participant.id for participant in next_state.participants]
        raise ValueError(f"Unknown actor {actor_id!r}; participants: {participant_ids}")
    if actor.is_structure:
        raise ValueError(f"{actor.name} ({actor.id}) is a structure and cannot act")
    still_encounter.guard_declaration(next_state, actor_id, declaration)
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
        construct_slam = (
            declaration.type is DeclarationType.ATTACK
            and (declaration.action or "").casefold() == architect_encounter.CONSTRUCT_SLAM.casefold()
            and target.is_structure
            and architect_encounter.is_owner(next_state, actor.id)
        )
        if not (self_stand or construct_slam) and target.is_ally == actor.is_ally:
            raise ValueError(
                f"{actor.name} ({actor.id}) cannot target {target.name} ({target.id}) with {declaration.type}"
            )
        if declaration.type is DeclarationType.MANEUVER:
            own_chamber = architect_entomb.source(next_state, actor.id) == target.id
            if target.is_structure and not own_chamber:
                raise ValueError(f"{target.name} ({target.id}) is a structure and cannot be maneuvered")
            if own_chamber or combat_grapple.grappler_id(actor.conditions) == target.id:
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
        if architect_entomb.matches(actor, pool_action) and (
            reason := architect_entomb.range_refusal(next_state, actor, pool_action, declaration.target_id)
        ):
            raise ValueError(reason)
        if still_encounter.is_owner(next_state, actor.id):
            from still_actions import range_refusal

            if reason := range_refusal(next_state, actor, pool_action, declaration):
                raise ValueError(reason)
        if pool_action.get("shape") == "cone":
            from choir_actions import require_targets

            require_targets(next_state, actor, pool_action, declaration)
    spell = None
    if declaration.type is DeclarationType.ABILITY and actor.type == "player":
        import combat_spell_profile
        import spells

        try:
            spell = spells.get_spell(declaration.action)
        except ValueError:
            spell = None
        if spell is not None:
            combat_spell_profile.validate_target(next_state, actor, declaration, spell)
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
                and action_kind(pool_action) not in ("healing", "prepare_attack", "charm", "silence", *STILL_ZONE_KINDS)
            )
        ):
            available = [action["name"] for action in actor.action_pool]
            raise ValueError(
                f"{actor.name} ({actor.id}) cannot declare ability {declaration.action!r}: only players "
                f"cast abilities, and an enemy only its condition actions; declare an attack from {available}"
            )

    if declaration.type not in (DeclarationType.ATTACK, DeclarationType.ABILITY, DeclarationType.MANEUVER):
        return
    if pool_action is not None and not action_has_direct_line(pool_action):
        return
    if spell is not None and spell.combat_damage and spell.combat_damage.get("recipients"):
        return
    require_line(
        next_state,
        actor.id,
        declaration.target_id,
        melee=pool_action is not None and combat_melee_approach.is_melee(pool_action),
    )
