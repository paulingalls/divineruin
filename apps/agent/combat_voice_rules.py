"""Condition guards at declaration and live combat resolution boundaries."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from declarations import Declaration
    from session_data import CombatParticipant, CombatState

import ability_voice_rules
import combat_grapple
import condition_voice_rules
import spells
from combat_ability_gate import declared_ability
from combat_ability_save import BENEFICIAL_CONDITIONS
from condition_sources import charm_sources, require_hostile_targets
from declarations import DeclarationType, ManeuverIntent
from encounter_actions import action_kind
from spell_voice_rules import is_area_spell, require_speech


def guard_spell(
    state: CombatState | None,
    actor_id: str,
    spell: spells.Spell,
    target_id: str | None = None,
    target_ids: list[str] | None = None,
):
    if spell.verbal:
        require_speech(state, actor_id)
    if state is None:
        return
    actor = state.get_participant(actor_id)
    if actor is None:
        raise ValueError(f"Unknown spell caster {actor_id!r}")
    sources = charm_sources(actor.conditions, {p.id for p in state.participants})
    if spell.hostile and sources:
        targets = spells.normalize_target_list(spell, target_id, target_ids) if target_ids else [target_id or actor_id]
        require_hostile_targets(state, actor, targets, area=is_area_spell(spell.id))


def guard_declaration(state: CombatState, actor: CombatParticipant, decl: Declaration):
    charm_sources(actor.conditions, {p.id for p in state.participants})
    targets = decl.target_ids or [decl.target_id or actor.id]
    if decl.type is DeclarationType.ATTACK:
        require_hostile_targets(state, actor, targets)
    elif decl.type is DeclarationType.MANEUVER:
        escape = (
            decl.maneuver_intent is ManeuverIntent.ESCAPE
            or combat_grapple.grappler_id(actor.conditions) == decl.target_id
        )
        if decl.target_id != actor.id and not escape:
            require_hostile_targets(state, actor, targets)
    elif decl.type is DeclarationType.ABILITY:
        if decl.action is None:
            raise ValueError("ability declaration missing an action")
        if actor.type == "player":
            ability = declared_ability(decl.action)
            if ability is not None:
                base, _variant = ability
                if base.spell_id is not None:
                    guard_spell(state, actor.id, spells.get_spell(base.spell_id), decl.target_id, decl.target_ids)
                else:
                    if base.applies_condition == "inspired":
                        targets = condition_voice_rules.spoken_buff_targets("inspired", state, actor.id, targets)
                    ability_voice_rules.policy(base.id)
                    if base.applies_condition != "inspired":
                        ability_voice_rules.require_ability_delivery(base.id, state, actor.id, targets)
                    if base.applies_condition not in BENEFICIAL_CONDITIONS:
                        require_hostile_targets(state, actor, targets)
                return
            if decl.action.lower() == "de_escalate":
                from combat_deescalation import eligible_argument_targets

                eligible_argument_targets(state, actor.id)
            else:
                guard_spell(state, actor.id, spells.get_spell(decl.action), decl.target_id, decl.target_ids)
        else:
            action = next((a for a in actor.action_pool if a["name"].lower() == decl.action.lower()), None)
            if action is not None and action_kind(action) not in ("healing", "prepare_attack"):
                require_hostile_targets(state, actor, targets)
