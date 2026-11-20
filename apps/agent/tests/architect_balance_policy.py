"""Fixed declarations for the level-20 Architect reference fight."""

from collections.abc import Iterable

import abilities
import architect_entomb
import architect_reshape
import combat_recharge
import spells
from combat_ability_gate import CUNNING_ACTION, DEVASTATING_STRIKE, RALLYING_SHOUT, SECOND_WIND, SHIELD_BASH
from combat_action_availability import available_actions
from combat_down import is_terminally_down
from combat_movement_cost import reachable_point
from combat_participant import CombatParticipant
from combat_spatial import distance, position, require_spatial
from combat_spatial_declarations import in_pit, movement_blocker
from combat_state import CombatState
from combat_structures import line_blocker, nearest_wall_point
from conditions import get_condition_effects, has_condition
from declaration_payloads import AbilityDecl, AttackDecl, DeclVariant, DefendDecl, ManeuverDecl, MoveDecl
from reshape_payloads import Destination, OpenFloor, ReshapeSelection

GEOMETRY = "Geometry Strike"
SLAM = "Construct Slam"
PRECISE = "rogue_precise_strike"
HEAL = "divine_heal_wounds"


def participants(state: CombatState, ids: tuple[str, ...]) -> list[CombatParticipant]:
    actors = []
    for actor_id in ids:
        actor = state.get_participant(actor_id)
        assert actor is not None, actor_id
        actors.append(actor)
    return actors


def owner_of(state: CombatState) -> CombatParticipant:
    assert state.architect_encounter is not None
    return participants(state, (state.architect_encounter["owner_id"],))[0]


def targets(players: list[CombatParticipant]) -> list[CombatParticipant]:
    standing = [p for p in players if not p.is_fallen]
    return sorted(standing, key=lambda p: p.hp_current) or [p for p in players if not is_terminally_down(p)]


def distance_between(state: CombatState, actor: CombatParticipant, target: CombatParticipant) -> float:
    spatial = require_spatial(state)
    origin = position(spatial, actor.id)
    segment = spatial["structures"].get(target.id)
    endpoint = nearest_wall_point(origin, segment) if segment else position(spatial, target.id)
    return distance(origin, endpoint)


def visible(
    state: CombatState, actor: CombatParticipant, candidates: Iterable[CombatParticipant], *, melee: bool = False
) -> Iterable[CombatParticipant]:
    return (p for p in candidates if line_blocker(state, actor.id, p.id, melee=melee) is None)


def geometry_target(
    state: CombatState, owner: CombatParticipant, candidates: list[CombatParticipant]
) -> CombatParticipant | None:
    reach = next(a["reach"] for a in owner.action_pool if a["name"] == GEOMETRY)
    return next((p for p in visible(state, owner, candidates) if distance_between(state, owner, p) <= reach), None)


def attack(
    actor: CombatParticipant,
    target: CombatParticipant,
    action: str,
    *,
    rider: str = "",
    reshape: Iterable[ReshapeSelection] = (),
) -> AttackDecl:
    return AttackDecl(
        kind="attack",
        actor_id=actor.id,
        action=action,
        target_id=target.id,
        held_item_id="",
        rider=rider,
        reshape=list(reshape),
    )


def ability(actor: CombatParticipant, action: str, target: CombatParticipant | None = None) -> AbilityDecl:
    return AbilityDecl(
        kind="ability", actor_id=actor.id, action=action, targets=[target.id] if target else [], argument_type=""
    )


def move(
    state: CombatState,
    actor: CombatParticipant,
    destination: dict,
    reshape: Iterable[ReshapeSelection] = (),
) -> MoveDecl | None:
    spatial = require_spatial(state)
    origin = position(spatial, actor.id)
    endpoint = reachable_point(spatial, actor.id, origin, destination, spatial["speeds"][actor.id])
    if movement_blocker(state, spatial, actor, origin, endpoint):
        return None
    return MoveDecl(
        kind="move",
        actor_id=actor.id,
        destination=Destination(**endpoint),
        movement_mode="ground",
        reshape=list(reshape),
    )


def flank(state: CombatState, actor: CombatParticipant, owner: CombatParticipant) -> MoveDecl | None:
    encounter = state.architect_encounter
    assert encounter is not None
    if state.round_number <= 1 or encounter["reaction_round"] != state.round_number - 1:
        return None
    spatial = require_spatial(state)
    origin = position(spatial, actor.id)
    if not any(
        ally.archetype_id in ("mage", "cleric")
        and not ally.is_fallen
        and distance(origin, position(spatial, ally.id)) <= 5
        for ally in state.participants
        if ally.type == "player"
    ):
        return None

    target = position(spatial, owner.id)
    dx, dy = target["x"] - origin["x"], target["y"] - origin["y"]
    if dx == dy == 0:
        return None
    side = 3 if actor.archetype_id == "warrior" else -3
    # A diagonal approach lets the melee line clear the end of the next wall.
    return move(state, actor, {**origin, "x": target["x"] - side * dy, "y": target["y"] + side * dx})


def recover(state: CombatState, actor: CombatParticipant) -> DeclVariant | None:
    if chamber := architect_entomb.source(state, actor.id):
        return ManeuverDecl(kind="maneuver", actor_id=actor.id, target_id=chamber)
    if in_pit(state, actor.id):
        return move(state, actor, position(require_spatial(state), actor.id))
    if has_condition(actor.conditions, "prone"):
        return ManeuverDecl(kind="maneuver", actor_id=actor.id, target_id=actor.id)
    return None


def player_declaration(
    state: CombatState,
    actor: CombatParticipant,
    owner: CombatParticipant,
    players: list[CombatParticipant],
    row: dict,
    damage: dict[str, int],
    rallied: bool,
    loadout: tuple[str, ...],
) -> DeclVariant:
    if recovery := recover(state, actor):
        return recovery
    melee = actor.archetype_id in ("warrior", "rogue")
    target = line_blocker(state, actor.id, owner.id, melee=melee) or owner
    if actor.archetype_id == "mage":
        for spell_id in ("arcane_disintegrate", "arcane_magic_missile"):
            if (
                spell_id in loadout
                and target is owner
                and row["focus"]["current"] >= spells.get_spell(spell_id).focus_cost
            ):
                return ability(actor, spell_id, target)
        return ability(actor, "arcane_bolt", target)
    if actor.archetype_id == "cleric":
        wounded = [
            p for p in visible(state, actor, players) if not is_terminally_down(p) and p.hp_current * 2 < p.hp_max
        ]
        if (
            len(wounded) >= 2
            and "divine_mass_heal" in loadout
            and row["focus"]["current"] >= spells.get_spell("divine_mass_heal").focus_cost
        ):
            return ability(actor, "divine_mass_heal")
        if wounded and row["focus"]["current"] >= spells.get_spell(HEAL).focus_cost:
            return ability(actor, HEAL, min(wounded, key=lambda p: p.hp_current))
        if (
            "divine_divine_judgment" in loadout
            and target is owner
            and row["focus"]["current"] >= spells.get_spell("divine_divine_judgment").focus_cost
        ):
            return ability(actor, "divine_divine_judgment", target)
        return ability(actor, "divine_sacred_flame", target)

    stamina = row["stamina"]["current"]
    weapon = actor.action_pool[0]
    reach = weapon.get("reach", 10 if "reach" in weapon.get("properties", []) else 5)
    separation = distance_between(state, actor, target)
    if actor.archetype_id == "warrior":
        allies = [p for p in visible(state, actor, players) if p.id != actor.id and not p.is_fallen]
        if (
            actor.hp_current * 2 < actor.hp_max
            and stamina >= abilities.get_ability(SECOND_WIND).cost.stamina
            and combat_recharge.available(actor, combat_recharge.SECOND_WIND_BUDGET)
        ):
            return ability(actor, SECOND_WIND)
        wounded_count = sum(not is_terminally_down(p) and p.hp_current * 2 < p.hp_max for p in players)
        if (
            not rallied
            and wounded_count >= 2
            and allies
            and stamina >= abilities.get_ability(RALLYING_SHOUT).cost.stamina
        ):
            return ability(actor, RALLYING_SHOUT, max(allies, key=lambda p: damage[p.id]))
    if target is owner and separation > reach and (approach := flank(state, actor, owner)):
        return approach
    if actor.archetype_id == "warrior":
        bash = not target.is_structure and not has_condition(target.conditions, "stunned")
        if bash and separation <= reach and stamina >= abilities.get_ability(SHIELD_BASH).cost.stamina:
            return attack(actor, target, weapon["name"], rider="shield_bash")
        charge = "warrior_unstoppable_charge"
        if (
            charge in loadout
            and target is owner
            and separation <= reach
            and not has_condition(target.conditions, "prone")
            and stamina >= abilities.get_ability(charge).cost.stamina
        ):
            return ability(actor, charge, target)
        if stamina >= abilities.get_ability(DEVASTATING_STRIKE).cost.stamina:
            return ability(actor, DEVASTATING_STRIKE, target)
        return attack(actor, target, weapon["name"])

    assert actor.archetype_id == "rogue", actor.archetype_id
    if (
        "attack" not in get_condition_effects(actor.conditions).advantage_scopes
        and stamina >= abilities.get_ability(PRECISE).cost.stamina
    ):
        return ability(actor, PRECISE)
    rider = "dash" if separation > reach else "hide"
    return attack(
        actor,
        target,
        weapon["name"],
        rider=rider if stamina >= abilities.get_ability(CUNNING_ACTION).cost.stamina else "",
    )


def open_floors(
    state: CombatState,
    owner: CombatParticipant,
    candidates: list[CombatParticipant],
) -> list[ReshapeSelection]:
    spatial = require_spatial(state)
    origin = position(spatial, owner.id)
    floors: list[ReshapeSelection] = []
    seen = set()
    allowance = architect_reshape.remaining(state, owner)
    for target in candidates:
        if len(floors) >= allowance:
            break
        if in_pit(state, target.id) or architect_entomb.source(state, target.id) or target.is_fallen:
            continue
        point = position(spatial, target.id)
        center = (point["x"], point["y"], point["z"])
        if center in seen:
            continue
        low = {**point, "x": point["x"] - 0.1, "y": point["y"] - 0.1}
        high = {**point, "x": point["x"] + 0.1, "y": point["y"] + 0.1}
        if any(
            distance(origin, {**point, "x": x, "y": y}) > architect_reshape.MAX_RANGE_FT
            for x in (low["x"], high["x"])
            for y in (low["y"], high["y"])
        ):
            continue
        floors.append(OpenFloor(kind="open_floor", min=Destination(**low), max=Destination(**high)))
        seen.add(center)
    return floors


def owner_declaration(
    state: CombatState,
    owner: CombatParticipant,
    candidates: list[CombatParticipant],
) -> DeclVariant:
    if recovery := recover(state, owner):
        return recovery
    if not candidates:
        return DefendDecl(kind="defend", actor_id=owner.id, reshape=[])
    actions = {a["name"]: a for a in available_actions(owner)}
    reshape = open_floors(state, owner, candidates)
    if "Cathedral" in actions and state.round_number == 1:
        return attack(owner, candidates[0], "Cathedral", reshape=reshape)
    if "Summon Constructs" in actions and state.round_number >= 2:
        return ability(owner, "Summon Constructs")
    if "Entomb" in actions:
        eligible = next(
            (
                p
                for p in visible(state, owner, candidates)
                if not p.is_fallen
                and architect_entomb.source(state, p.id) is None
                and architect_entomb.range_refusal(state, owner, actions["Entomb"], p.id) is None
            ),
            None,
        )
        if eligible:
            return attack(owner, eligible, "Entomb", reshape=reshape)
    for target in visible(state, owner, candidates, melee=True):
        if distance_between(state, owner, target) <= actions[SLAM]["reach"]:
            return attack(owner, target, SLAM, reshape=reshape)
    if target := geometry_target(state, owner, candidates):
        return attack(owner, target, GEOMETRY, reshape=reshape)
    wall = line_blocker(state, owner.id, candidates[0].id, melee=True)
    if wall is not None and wall.id in require_spatial(state)["structures"]:
        return attack(owner, wall, SLAM, reshape=reshape)
    return DefendDecl(kind="defend", actor_id=owner.id, reshape=reshape)


def construct_declaration(
    state: CombatState,
    actor: CombatParticipant,
    candidates: list[CombatParticipant],
) -> DeclVariant:
    if recovery := recover(state, actor):
        return recovery
    ordered = (
        candidates
        if candidates and candidates[0].is_fallen
        else sorted(candidates, key=lambda p: distance_between(state, actor, p))
    )
    if target := next(iter(visible(state, actor, ordered, melee=True)), None):
        return attack(actor, target, "Slam")
    return DefendDecl(kind="defend", actor_id=actor.id, reshape=[])
