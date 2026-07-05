"""Typed combat declaration model (M4.2, story-002).

The spec's action economy is "one declaration per phase per participant" across six
categories (gm_combat §Action Economy, L99-106). ``resolve_declaration`` is a PURE
classify+validate function: it turns a raw declaration dict (what the DM emits into
``declare_phase``) into a typed ``Declaration``, or raises ``ValueError`` on a bad
shape. The pure-engine boundary raises ``ValueError``; the tool layer
(``combat_turn``) translates it to ``ToolError`` (the established idiom).

Resolution of each category lives downstream in orchestration: Attack resolves via
``check_resolution_attack.resolve_attack``; Defend's ``ac_bonus`` is applied as a phase-scoped
``CombatState.ac_modifiers`` entry. ABILITY is modelled here as a first-class category
(unified-declaration-path decision, supersedes cea4ff06ea31) but its in-combat
resolution lands in story-007; INTERACT/MANEUVER/RETREAT are modelled now and resolved
in later M4.x work.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

# Defend grants +2 AC until the next phase (gm_combat:105).
DEFEND_AC_BONUS = 2


class DeclarationType(StrEnum):
    """The six declaration categories. StrEnum so members serialize transparently and
    compare equal to their wire strings."""

    ATTACK = "attack"
    ABILITY = "ability"
    INTERACT = "interact"
    MANEUVER = "maneuver"
    DEFEND = "defend"
    RETREAT = "retreat"


@dataclass(frozen=True)
class Declaration:
    """A validated, typed declaration produced by ``resolve_declaration``.

    ``action`` names the weapon/ability/item (Attack/Ability/Interact); ``target_id``
    is the declaration's target (required for Attack/Maneuver). ``ac_bonus`` carries
    the static per-category outcome — only Defend is non-zero today. ``rider`` carries
    an optional chosen enhancer modifier (e.g. Cunning Action's dash/disengage/hide),
    consumed by enhancer resolution (M4.2, story-004); ``None`` when no rider was chosen.
    """

    type: DeclarationType
    action: str | None = None
    target_id: str | None = None
    # M4.8 story-012: a multi-target spell declaration (e.g. Bless on up to three allies) names
    # several ally participants at once; None for a single-target/self declaration. The cap is
    # enforced at the declare-gate (combat_packet) via spells.normalize_target_list, not here.
    target_ids: list[str] | None = None
    ac_bonus: int = 0
    rider: str | None = None
    # M15 story-002: the Tier-3 argument category a de_escalate ABILITY makes (one of
    # social_resolution.ARGUMENT_TYPES — reason/emotion/self_interest/threat/bluff/evidence). Carried
    # verbatim here (shape-only); the value is validated at the packet boundary (combat_ability),
    # not in this pure classifier. None for every non-de_escalate declaration.
    argument_type: str | None = None


def resolve_declaration(raw: dict) -> Declaration:
    """Classify and validate one raw declaration dict into a typed ``Declaration``.

    Pure. Raises ``ValueError`` when ``type`` is missing/unknown or a category's
    required fields are absent (Attack needs action+target_id; Ability/Interact need
    action; Maneuver needs target_id; Defend/Retreat need neither).
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

    if decl_type is DeclarationType.ATTACK:
        if not action:
            raise ValueError("attack declaration requires an 'action'")
        if not target_id:
            raise ValueError("attack declaration requires a 'target_id'")
    elif decl_type in (DeclarationType.ABILITY, DeclarationType.INTERACT):
        if not action:
            raise ValueError(f"{decl_type} declaration requires an 'action'")
    elif decl_type is DeclarationType.MANEUVER:
        if not target_id:
            raise ValueError("maneuver declaration requires a 'target_id'")

    ac_bonus = DEFEND_AC_BONUS if decl_type is DeclarationType.DEFEND else 0
    return Declaration(
        type=decl_type,
        action=action,
        target_id=target_id,
        target_ids=raw.get("target_ids"),
        ac_bonus=ac_bonus,
        rider=raw.get("rider"),
        argument_type=raw.get("argument_type"),
    )
