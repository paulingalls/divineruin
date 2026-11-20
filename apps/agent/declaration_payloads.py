"""The sum-typed payload for the `declare_phase` verb (ADR 0008).

`declare_phase` used to take `dict[str, dict]` — a participant-id map of free-form
declaration dicts. Strict schemas reject that outright ("additionalProperties"), which is
why CombatAgent could not run strict at all. One discriminated `anyOf` of kind-tagged
variants, in a list, costs one union slot and carries the same information: the map key
becomes each variant's `actor_id`.

No optionals inside the variants (ADR 0008 rule 2): `rider` and `argument_type` are
required strings where `""` means "none", and the mapper drops them rather than passing
an empty string down. `targets` is a list because a spell may bless several allies at
once; the engine takes `target_id` OR `target_ids`, never both (spells.normalize_target_list
refuses both), so the mapper picks by length.

`to_engine_declarations` is pure and returns exactly the `dict[str, dict]`
`_declare_phase_impl` and `combat_phase.advance_combat_phase` have always taken, so the
engine, `declarations.resolve_declaration` and every capstone that drives `_impl` are
untouched by the reshape.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field

from item_effects import CONSUME_PREFIX
from reshape_payloads import Destination, ReshapeSelection

RESHAPE_DESCRIPTION = (
    "Architect only, before the action. Select create_wall, move_wall, destroy_wall, open_floor, or lower_ceiling. "
    "Use an empty list for no Reshape."
)


class AttackDecl(BaseModel):
    """Strike a target with an equipped weapon."""

    kind: Literal["attack"]
    actor_id: str = Field(description="The participant declaring this action.")
    action: str = Field(description='The EXACT name of one of the actor\'s equipped weapons, e.g. "Longsword".')
    target_id: str = Field(description="The participant being struck.")
    held_item_id: str = Field(
        description="Selected target inventory ID for a durability rider; empty when none applies."
    )
    rider: str = Field(
        description='For a Cunning Action attacker, the movement rider: "dash", "disengage" or "hide". '
        'Use "shield_bash" for the warrior ability, or an empty string for an ordinary attack.'
    )
    reshape: list[ReshapeSelection] = Field(description=RESHAPE_DESCRIPTION)


class StrikeSelection(BaseModel):
    model_config = {"extra": "forbid"}
    action: str
    target_id: str
    held_item_id: str


class MultiattackDecl(BaseModel):
    """One catalog composite; choose all ordered strike targets upfront."""

    model_config = {"extra": "forbid"}
    kind: Literal["multiattack"]
    actor_id: str
    action: str
    strikes: list[StrikeSelection]


class AbilityDecl(BaseModel):
    """Cast a spell or use an ability. This is how a caster acts IN COMBAT."""

    kind: Literal["ability"]
    actor_id: str = Field(description="The participant declaring this action.")
    action: str = Field(description='The EXACT id of a spell or ability the actor knows, e.g. "arcane_bolt".')
    targets: list[str] = Field(
        description="Who it is aimed at — one id for a single target, several for a multi-target "
        "spell, empty for a self-cast. Mass Heal selects allies automatically; pass an empty list. "
        "Areas center on named participants; lines and cones aim "
        "from the caster toward one participant. Meteor Swarm accepts up to four centers. "
        "Chain Lightning names its primary first, then optional arcs. Magic Missile repeats "
        "ids in dart order, or uses one id for every dart."
    )
    argument_type: str = Field(
        description='Only for action "de_escalate": the kind of case made this round — reason, '
        "emotion, self_interest, threat, bluff or evidence. For arcane_elemental_burst: fire, cold, or lightning. Empty string for other abilities."
    )


class InteractDecl(BaseModel):
    """Interact with the scene. For healing items, use consume."""

    kind: Literal["interact"]
    actor_id: str = Field(description="The participant declaring this action.")
    action: str = Field(description="What they interact with.")


class ConsumeDecl(BaseModel):
    """Spend the holder's action and one healing item to heal an ally."""

    kind: Literal["consume"]
    actor_id: str = Field(description="The conscious party player holding the item.")
    item_id: str = Field(description="The healing item's inventory ID from query_info.")
    target_id: str = Field(description='The ally receiving the item. Empty string ("") for the holder.')


class ManeuverDecl(BaseModel):
    """Shove, grapple or otherwise physically move a target."""

    kind: Literal["maneuver"]
    actor_id: str = Field(description="The participant declaring this action.")
    target_id: str = Field(
        description="Shove a target (contested Strength; a win knocks them prone), target yourself to stand up from prone, or target your grappler to break free."
    )


class MoveDecl(BaseModel):
    """Move to an explicit point in feet, consuming the phase action."""

    kind: Literal["move"]
    actor_id: str
    destination: Destination
    movement_mode: Literal["ground", "flying"] = Field(
        description="Choose ground for ordinary movement. Flying adds ceiling restrictions and grants no flight capability."
    )
    reshape: list[ReshapeSelection] = Field(description=RESHAPE_DESCRIPTION)


class DefendDecl(BaseModel):
    """Make no attack and gain +2 AC until the next phase."""

    kind: Literal["defend"]
    actor_id: str = Field(description="The participant declaring this action.")
    reshape: list[ReshapeSelection] = Field(description=RESHAPE_DESCRIPTION)


class RetreatDecl(BaseModel):
    """Withdraw from the fight."""

    kind: Literal["retreat"]
    actor_id: str = Field(description="The participant declaring this action.")


DeclVariant = Union[
    MultiattackDecl, AttackDecl, AbilityDecl, InteractDecl, ConsumeDecl, ManeuverDecl, MoveDecl, DefendDecl, RetreatDecl
]
DeclPayload = Annotated[DeclVariant, Field(discriminator="kind")]

DECL_VARIANTS: tuple[type[BaseModel], ...] = (
    AttackDecl,
    MultiattackDecl,
    AbilityDecl,
    InteractDecl,
    ConsumeDecl,
    ManeuverDecl,
    MoveDecl,
    DefendDecl,
    RetreatDecl,
)


def _raw(decl: DeclVariant) -> dict:
    if isinstance(decl, MultiattackDecl):
        return {
            "type": "multiattack",
            "action": decl.action,
            "strikes": [{k: v for k, v in s.model_dump().items() if k != "held_item_id" or v} for s in decl.strikes],
        }
    if isinstance(decl, AttackDecl):
        raw = {"type": "attack", "action": decl.action, "target_id": decl.target_id}
        if decl.held_item_id:
            raw["held_item_id"] = decl.held_item_id
        if decl.rider:
            raw["rider"] = decl.rider
        return raw
    if isinstance(decl, AbilityDecl):
        raw: dict = {"type": "ability", "action": decl.action}
        # target_id XOR target_ids: spells.normalize_target_list refuses both at the
        # declare-gate, so the list length is what picks between them.
        if len(decl.targets) == 1:
            raw["target_id"] = decl.targets[0]
        elif len(decl.targets) > 1:
            raw["target_ids"] = decl.targets
        if decl.argument_type:
            raw["argument_type"] = decl.argument_type
        return raw
    if isinstance(decl, ConsumeDecl):
        return {
            "type": "interact",
            "action": f"{CONSUME_PREFIX}{decl.item_id}",
            "target_id": decl.target_id or decl.actor_id,
        }
    if isinstance(decl, InteractDecl):
        import choir_encounter
        import still_encounter

        raw = {"type": "interact", "action": decl.action}
        if decl.action in choir_encounter.SEARCH_ACTIONS:
            raw["target_id"] = choir_encounter.SEARCH_TARGET
        elif decl.action in still_encounter.SEARCH_ACTIONS:
            raw["target_id"] = still_encounter.SEARCH_TARGET
        return raw
    if isinstance(decl, MoveDecl):
        return {
            "type": "maneuver",
            "action": "move",
            "target_id": decl.actor_id,
            "destination": decl.destination.model_dump(),
            "movement_mode": decl.movement_mode,
        }
    if isinstance(decl, ManeuverDecl):
        return {"type": "maneuver", "target_id": decl.target_id}
    if isinstance(decl, DefendDecl):
        return {"type": "defend"}
    if isinstance(decl, RetreatDecl):
        return {"type": "retreat"}
    # Not a fallthrough: an unmapped variant that inherited the last branch would reach the engine
    # as some OTHER actor's action, and the round-trip test would pass because both sides read the
    # same wrong type. A new variant fails here instead.
    raise ValueError(f"no engine mapping for declaration variant {type(decl).__name__}")


def to_engine_declarations(declarations: list[DeclVariant]) -> dict[str, dict]:
    """Map the declared list onto the participant-keyed dict the engine has always taken.

    Raises ``ValueError`` — the one exception the tool layer translates — when one actor
    declares twice. The old dict shape made that unrepresentable; a list does not, and a
    silent last-wins collapse would drop a combatant's whole round.
    """
    engine: dict[str, dict] = {}
    for decl in declarations:
        if decl.actor_id in engine:
            raise ValueError(f"{decl.actor_id} declared more than once — one declaration per participant per phase")
        raw = _raw(decl)
        if isinstance(decl, (AttackDecl, MoveDecl, DefendDecl)) and decl.reshape:
            raw["reshape"] = [operation.model_dump() for operation in decl.reshape]
        engine[decl.actor_id] = raw
    return engine
