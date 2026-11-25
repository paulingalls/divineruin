"""The shared atomic declaration gate, including each selected composite strike."""

from dataclasses import replace
from typing import TYPE_CHECKING

import abilities
import architect_constructs
import architect_encounter
import architect_entomb
import combat_grapple
import combat_martial
import combat_melee_approach
import combat_spatial_declarations
import combat_voice_rules
import still_encounter
from action_contracts_still import STILL_ZONE_KINDS
from combat_ability import _find_action
from combat_ability_gate import (
    CUNNING_ACTION,
    DEVASTATING_STRIKE,
    ELECTIVE_ATTACK_RIDERS,
    SHIELD_BASH,
    combat_ability,
    declared_ability,
)
from combat_action_availability import require_available
from combat_structures import THORNWALL, action_has_direct_line, blocked_reason, line_blocker, require_line
from condition_restrictions import cannot_act, declaration_costs, required_attack_sources, speed_zero
from declarations import Declaration, DeclarationType, ManeuverIntent
from encounter_actions import action_kind

if TYPE_CHECKING:
    from combat_participant import CombatParticipant
    from combat_state import CombatState


def _require_taunt_target(state: "CombatState", actor: "CombatParticipant", declaration: Declaration) -> None:
    targets = declaration.target_ids or [declaration.target_id]
    for source in required_attack_sources(actor.conditions):
        taunter = state.get_participant(source)
        if taunter is None:
            raise ValueError(f"Taunt source {source!r} is not a combat participant")
        if taunter.is_fallen or source in targets:
            continue
        # Check the retargeted attack against the same rules that would validate its redeclaration.
        try:
            validate_declaration(
                state, actor.id, replace(declaration, target_id=source, target_ids=None, reshape=None), {}
            )
        except ValueError:
            continue
        raise ValueError(f"{actor.name} is under Taunt and must attack {taunter.name} ({source}).")


def validate_declaration(
    next_state: "CombatState",
    actor_id: str,
    declaration: Declaration,
    persisted_declarations: dict,
    *,
    queued: bool = False,
) -> None:
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
            validate_declaration(next_state, actor_id, child, persisted_declarations, queued=queued)
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
        strikes_thornwall = declaration.type is DeclarationType.ATTACK and target.structure_kind == THORNWALL
        if not (self_stand or construct_slam or strikes_thornwall) and target.is_ally == actor.is_ally:
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
    if declaration.type is DeclarationType.ATTACK and not queued:
        _require_taunt_target(next_state, actor, declaration)
    pool_action = _find_action(actor, declaration.action)
    martial = combat_martial.attack_ability(declaration)
    if declaration.type is DeclarationType.ATTACK and declaration.rider and martial is None:
        raise ValueError(f"Unknown attack rider {declaration.rider!r}.")
    if martial is not None and martial in ELECTIVE_ATTACK_RIDERS.values() and actor.type != "player":
        raise ValueError(f"{actor.name} hasn't learned {abilities.get_ability(martial).name}.")
    if martial in (CUNNING_ACTION, SHIELD_BASH):
        ability = abilities.get_ability(martial)
        if actor.type != "player" or not abilities.owns_ability(
            actor.archetype_id, actor.level, ability, owns_elective=False
        ):
            raise ValueError(f"{actor.name} hasn't learned {ability.name}.")
        if martial == SHIELD_BASH and (pool_action is None or not combat_melee_approach.is_melee(pool_action)):
            raise ValueError("Shield Bash requires an equipped melee weapon.")
    if pool_action is not None and declaration.type in (DeclarationType.ATTACK, DeclarationType.ABILITY):
        require_available(actor, pool_action)
        if action_kind(pool_action) == architect_constructs.KIND:
            if not architect_encounter.is_owner(next_state, actor.id):
                raise ValueError("Summon Constructs requires the Architect")
            if declaration.type is not DeclarationType.ABILITY or declaration.target_ids or declaration.target_id:
                raise ValueError("Summon Constructs requires a targetless ability declaration")
            return
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

        assert declaration.action is not None
        try:
            spell = spells.get_spell(declaration.action)
        except ValueError:
            spell = None
        if spell is not None:
            combat_spell_profile.validate_target(next_state, actor, declaration, spell)
        resolved_ability = declared_ability(declaration.action)
        if resolved_ability is not None:
            ability, _variant = resolved_ability
            if ability.spell_id is not None:
                raise ValueError(f"{declaration.action} is an ability alias; declare {ability.spell_id} in combat")
            if not combat_ability(ability):
                raise ValueError(f"{declaration.action} is not declarable in combat")
            combat_martial.require_targets(next_state, actor, declaration, ability)
            if ability.id == DEVASTATING_STRIKE:
                # A weapon strike, not a ranged line: check its target by melee reach to the wall's nearest point.
                require_line(next_state, actor.id, declaration.target_id, melee=True)
                return
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
    melee = pool_action is not None and combat_melee_approach.is_melee(pool_action)
    physical = melee or declaration.type is DeclarationType.MANEUVER
    wall = line_blocker(next_state, actor.id, declaration.target_id, melee=physical)
    if wall is not None and (not melee or actor.is_ally or wall.structure_kind != THORNWALL):
        raise ValueError(blocked_reason(wall))
