"""Typed combat declaration model (M4.2, story-002).

The spec's action economy is "one declaration per phase per participant" across the
six categories in gm_combat §Action Economy (L99-106). ``resolve_declaration`` turns a
raw declaration dict (what the DM emits into ``declare_phase``) into a typed
``Declaration``, or raises ``ValueError`` on a bad shape. It performs no IO or mutation.
The tool layer (``combat_turn``) translates that error to ``ToolError``.

A REACTION was a seventh category until story-017 made a reaction an INTERRUPT against an
open Beat-3 window (decision 46). It is not a declaration: it costs no phase action, and the
window it answers is a fact the declaration beat could not yet know.

Resolution of each category lives downstream in orchestration: Attack resolves via
``check_resolution_attack.resolve_attack``; Defend's ``ac_bonus`` is applied as a phase-scoped
``CombatState.ac_modifiers`` entry. ABILITY is modelled here as a first-class category
(unified-declaration-path decision, supersedes cea4ff06ea31) but its in-combat
resolution lands in story-007; MANEUVER resolves as stand, shove, or escape, while INTERACT/RETREAT remain
modelled for later work.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from reshape_payloads import parse_operations

# Defend grants +2 AC until the next phase (gm_combat:105).
DEFEND_AC_BONUS = 2


class DeclarationType(StrEnum):
    """The six declaration categories. StrEnum so members serialize transparently and
    compare equal to their wire strings."""

    ATTACK = "attack"
    MULTIATTACK = "multiattack"
    ABILITY = "ability"
    INTERACT = "interact"
    MANEUVER = "maneuver"
    DEFEND = "defend"
    RETREAT = "retreat"


class ManeuverIntent(StrEnum):
    ESCAPE = "escape"


@dataclass(frozen=True)
class Declaration:
    """One phase action, with an optional declaration enhancer carried in its rider."""

    type: DeclarationType
    action: str | None = None
    target_id: str | None = None
    # M4.8 story-012: a multi-target spell declaration (e.g. Bless on up to three allies) names
    # several ally participants at once; None for a single-target/self declaration. The cap is
    # enforced at the declare-gate (combat_packet) via spells.normalize_target_list, not here.
    target_ids: list[str] | None = None
    destination: dict | None = None
    ac_bonus: int = 0
    rider: str | None = None
    # M15 story-002: the Tier-3 argument category a de_escalate ABILITY makes (one of
    # social_resolution.ARGUMENT_TYPES — reason/emotion/self_interest/threat/bluff/evidence). Carried
    # verbatim here (shape-only); the value is validated at the packet boundary (combat_ability),
    # not in this pure classifier. None for every non-de_escalate declaration.
    argument_type: str | None = None
    # story-074: which maneuver this is. Only the declare gate (combat_phase.advance_combat_phase)
    # can set it — it has the actor and the state this pure classifier does not — and resolution
    # reads it instead of re-deriving it there, where the hold may already have ended.
    maneuver_intent: ManeuverIntent | None = None
    strikes: list[dict] | None = None
    held_item_id: str | None = None
    reshape: list[dict] | None = None
    movement_mode: str = "ground"


def resolve_declaration(raw: dict) -> Declaration:
    """Classify and validate one raw declaration dict into a typed ``Declaration``.

    Raises ``ValueError`` — and only ``ValueError``, the one exception the tool layer
    translates — when ``type`` is missing/unknown or a category's required fields are
    absent or malformed (Attack needs action+target_id;
    Ability/Interact need action; Maneuver needs target_id; Defend/Retreat need neither).
    """
    raw_type = raw.get("type")
    if not raw_type:
        raise ValueError("declaration requires a 'type'")
    try:
        decl_type = DeclarationType(str(raw_type).lower())
    except ValueError as e:
        raise ValueError(f"unknown declaration type: {raw_type!r}") from e

    action = raw.get("action")
    target_id = raw.get("target_id")

    if decl_type is DeclarationType.MULTIATTACK:
        strikes = raw.get("strikes")
        if not isinstance(action, str) or not action or not isinstance(strikes, list) or not strikes:
            raise ValueError("multiattack requires action and nonempty strikes")
        for strike in strikes:
            if (
                not isinstance(strike, dict)
                or not {"action", "target_id"} <= set(strike) <= {"action", "target_id", "held_item_id"}
                or not all(isinstance(value, str) and value for value in strike.values())
            ):
                raise ValueError("multiattack strikes require action and target_id, with optional held_item_id")
    if decl_type is DeclarationType.ATTACK:
        if not action:
            raise ValueError("attack declaration requires an 'action'")
        if not target_id:
            raise ValueError("attack declaration requires a 'target_id'")
    elif decl_type in (DeclarationType.ABILITY, DeclarationType.INTERACT):
        if not action:
            raise ValueError(f"{decl_type} declaration requires an 'action'")
    elif decl_type is DeclarationType.MANEUVER and not target_id:
        raise ValueError("maneuver declaration requires a 'target_id'")
    is_move = decl_type is DeclarationType.MANEUVER and action == "move"
    is_shadow_step = False
    if decl_type is DeclarationType.ABILITY and isinstance(action, str):
        from combat_ability_gate import SHADOW_STEP, declared_ability

        resolved = declared_ability(action)
        is_shadow_step = action == SHADOW_STEP or (resolved is not None and resolved[0].id == SHADOW_STEP)
    if is_move or is_shadow_step:
        from combat_spatial import point

        point(raw.get("destination"))
    elif "destination" in raw:
        raise ValueError("destination is only valid for move or Shadow Step")
    if "held_item_id" in raw and (
        not isinstance(raw["held_item_id"], str) or not raw["held_item_id"] or decl_type is not DeclarationType.ATTACK
    ):
        raise ValueError("held_item_id requires an attack and a nonempty string")
    movement_mode = raw.get("movement_mode", "ground")
    if "movement_mode" in raw and (not is_move or movement_mode not in ("ground", "flying")):
        raise ValueError("movement_mode must be ground or flying on a move")
    reshape = None
    if "reshape" in raw:
        if not (is_move or decl_type in (DeclarationType.ATTACK, DeclarationType.DEFEND)):
            raise ValueError("reshape requires an attack, move or defend declaration")
        reshape = parse_operations(raw["reshape"])
    ac_bonus = DEFEND_AC_BONUS if decl_type is DeclarationType.DEFEND else 0
    raw_maneuver_intent = raw.get("maneuver_intent")
    maneuver_intent = ManeuverIntent(raw_maneuver_intent) if raw_maneuver_intent is not None else None
    return Declaration(
        type=decl_type,
        reshape=reshape,
        movement_mode=movement_mode,
        strikes=raw.get("strikes"),
        held_item_id=raw.get("held_item_id"),
        destination=raw.get("destination"),
        action=action,
        target_id=target_id,
        target_ids=raw.get("target_ids"),
        ac_bonus=ac_bonus,
        rider=raw.get("rider"),
        argument_type=raw.get("argument_type"),
        maneuver_intent=maneuver_intent,
    )
