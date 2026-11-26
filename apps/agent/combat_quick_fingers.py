"""Quick Fingers checks and pocket transfers inside the combat transaction."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

import abilities
import ability_persistence
import check_resolution
import combat_martial
import combat_melee_approach
import condition_voice_rules
import conditions
import db_content_queries
import db_mutations
import db_mutations_inventory
import dice
import durability
import event_types as E
import inventory_refresh
import thyra_seasons
from asset_utils import compute_item_image_url
from combat_ability import _gate_ability_condition, _with_variant
from combat_ability_gate import QUICK_FINGERS, QUICK_FINGERS_RIDER, declared_ability
from combat_terrain import skill_natural_terrain
from declarations import Declaration, resolve_declaration
from patron_location import check_first_stay
from rules_engine import attribute_modifier
from tool_support import build_item_acquired_payload

if TYPE_CHECKING:
    import asyncpg

    from combat_events import EventSink
    from combat_fate_rolls import PacketRolls
    from combat_participant import CombatParticipant
    from combat_state import CombatState
    from session_data import SessionData


class Wary(TypedDict):
    attack_pending: bool


def inventory_selector(item_id: str, *, tainted: bool) -> str:
    return f"{'tainted' if tainted else 'clean'}:{item_id}"


def require_target(target: CombatParticipant | None, weapon: dict | None) -> None:
    if weapon is None or not combat_melee_approach.is_melee(weapon):
        raise ValueError("Quick Fingers requires an equipped melee weapon.")
    if target is None or target.type != "enemy" or not combat_martial.standing_foe(target):
        raise ValueError("Quick Fingers requires a standing enemy.")


async def _definition(item_id: str, *, conn: asyncpg.Connection | None) -> dict:
    item = await db_content_queries.get_item(item_id, conn=conn)
    material = await db_content_queries.get_material_definition(item_id, conn=conn)
    if item is not None and material is None:
        return item
    if item is None and material is not None:
        return material
    raise ValueError(f"Quick Fingers item {item_id!r} must have exactly one item or material definition.")


async def _plant_row(player_id: str, selector: str, *, queries, conn: asyncpg.Connection | None = None) -> dict:
    stack, _, item_id = selector.partition(":")
    if stack not in ("clean", "tainted") or not item_id:
        raise ValueError("Choose a Quick Fingers item selector from the rogue's own inventory.")
    tainted = stack == "tainted"
    row = await queries.get_inventory_item(player_id, item_id, tainted=tainted, conn=conn, for_update=conn is not None)
    if row is None or row["quantity"] < 1:
        raise ValueError("The rogue no longer carries the selected Quick Fingers item.")
    definition = await _definition(item_id, conn=conn)
    name = definition["name"]
    if row.get("equipped"):
        raise ValueError(f"Unequip {name} before using Quick Fingers to plant it.")
    if (hits := row.get("current_hits")) is not None and hits < durability.max_hits(definition["durability_tier"]):
        raise ValueError(f"{name} is worn. Quick Fingers can only plant an item at full durability.")
    return {"item_id": item_id, "name": name, "quantity": 1, "tainted": tainted}


async def preflight(state: CombatState, *, queries) -> None:
    for actor_id, raw in state.pending_declarations.items():
        if raw.get("rider") != QUICK_FINGERS_RIDER:
            continue
        decl = resolve_declaration(raw)
        ability = abilities.get_ability(QUICK_FINGERS)
        player = await queries.get_player(actor_id)
        if player is None:
            raise ValueError(f"Unknown player: {actor_id}")
        owned = await ability_persistence.owns_elective(actor_id, ability.id)
        if not abilities.owns_ability(player.get("class"), player["level"], ability, owns_elective=owned):
            raise ValueError("This rogue hasn't learned Quick Fingers.")
        variant = await combat_martial.active_rider_variant(actor_id, ability.id, conn=None)
        _gate_ability_condition(player, ability, variant)
        if decl.quick_fingers_item is not None:
            await _plant_row(actor_id, decl.quick_fingers_item, queries=queries)


def take_advantage(state: CombatState, attacker: CombatParticipant, target: CombatParticipant) -> bool:
    wary = state.quick_fingers_wary.get(attacker.id, {}).get(target.id)
    if wary is None or not wary["attack_pending"]:
        return False
    wary["attack_pending"] = False
    return True


async def _plant(actor_id: str, pocket: list[dict], plant: dict, *, conn: asyncpg.Connection) -> None:
    await db_mutations_inventory.transact_inventory(actor_id, plant["item_id"], -1, tainted=plant["tainted"], conn=conn)
    pocket.append({key: plant[key] for key in ("item_id", "quantity", "tainted")})


async def _steal(
    session: SessionData, actor_id: str, pocket: list[dict], index: int, *, conn: asyncpg.Connection, sink: EventSink
) -> dict:
    drop = pocket.pop(index)
    item_id = drop["item_id"]
    definition = await _definition(item_id, conn=conn)
    await db_mutations.add_inventory_item(actor_id, item_id, drop["quantity"], tainted=drop["tainted"], conn=conn)
    await sink.emit(
        session.room,
        E.ITEM_ACQUIRED,
        build_item_acquired_payload(
            definition,
            item_id=item_id,
            image_url=compute_item_image_url(definition),
            quantity=drop["quantity"],
            source=QUICK_FINGERS_RIDER,
            player_id=actor_id,
        ),
        event_bus=session.event_bus,
    )
    return {**drop, "name": definition["name"]}


async def _transfer(
    session: SessionData,
    target: CombatParticipant,
    actor_id: str,
    mode: str,
    plant: dict | None,
    *,
    queries,
    conn: asyncpg.Connection,
    sink: EventSink,
) -> tuple[dict | None, bool]:
    pocket = target.carried_items
    assert pocket is not None, f"Enemy {target.id} has uninitialized carried items"
    stealing = mode in ("steal", "swap")
    count = len(pocket)
    index = None
    if stealing and count:
        index = dice.roll(f"1d{count}").total - 1 if count > 1 else 0
    if plant is not None:
        await _plant(actor_id, pocket, plant, conn=conn)
    stolen = None
    if index is not None:
        stolen = await _steal(session, actor_id, pocket, index, conn=conn, sink=sink)
    if plant is not None or stolen is not None:
        inventory = await inventory_refresh.inventory_payload(actor_id, conn=conn, queries=queries)
        await sink.emit(session.room, E.INVENTORY_UPDATED, inventory, event_bus=session.event_bus)
    return stolen, stealing and count == 0


async def resolve(
    session: SessionData,
    state: CombatState,
    actor: CombatParticipant,
    target: CombatParticipant,
    decl: Declaration,
    cursor: dict,
    *,
    queries,
    conn: asyncpg.Connection,
    sink: EventSink,
    progress: PacketRolls | None,
) -> dict | None:
    if "quick_fingers" in cursor:
        return cursor["quick_fingers"]
    if conn is None or sink is None:
        raise RuntimeError("Quick Fingers requires a combat transaction and event buffer.")
    mode = decl.quick_fingers_mode
    assert mode is not None
    dc = 10 + attribute_modifier(target.attributes.get("wisdom", 10))
    receipt = {"mode": mode, "planted": None, "stolen": None, "total": None, "dc": dc, "success": False, "wary": False}
    already_wary = bool(state.quick_fingers_wary.get(target.id))

    try:
        plant = None
        if decl.quick_fingers_item is not None and not already_wary:
            plant = await _plant_row(actor.id, decl.quick_fingers_item, queries=queries, conn=conn)
    except ValueError as error:
        if progress is not None:
            progress.take_skill()
        return {"reason": str(error), "refused": True}

    if already_wary:
        receipt.update(wary=True, reason=f"{target.name} is wary. Quick Fingers fails without a roll.")
    else:
        player = await queries.get_player(actor.id, conn=conn, for_update=True)
        if player is None:
            raise ValueError(f"Unknown player: {actor.id}")

        async def roll() -> check_resolution.SkillCheckResult:
            skill = "sleight_of_hand"
            return check_resolution.resolve_skill_check_dc(
                condition_voice_rules.roll_data(player, state, actor.id),
                skill,
                dc,
                ally_present=session.allies_present_for(actor.id),
                natural_terrain=await skill_natural_terrain(session, player, skill, combat_state=state),
                hearing_only=False,
                season=await thyra_seasons.skill_season(player, skill, conn=conn),
                first_stay=await check_first_stay(player, session, skill, player_id=actor.id, conn=conn),
            )

        result = await progress.skill(session, actor.id, roll) if progress is not None else await roll()
        if result is None:
            return None
        actor.conditions = conditions.remove_conditions(actor.conditions, result.consumed_conditions)
        receipt.update(total=result.total, success=result.success, wary=not result.success)
        if result.success:
            stolen, empty = await _transfer(
                session, target, actor.id, mode, plant, queries=queries, conn=conn, sink=sink
            )
            receipt.update(planted=plant, stolen=stolen, pouch_empty=empty)
            if empty:
                receipt["reason"] = f"{target.name}'s pouch was empty."
        else:
            state.quick_fingers_wary.setdefault(target.id, {})[actor.id] = {"attack_pending": True}

    resolved = declared_ability(QUICK_FINGERS)
    assert resolved is not None
    variant = await combat_martial.pay(actor.id, resolved, queries=queries, conn=conn)
    cursor["quick_fingers"] = receipt
    cursor["variant_receipt"] = _with_variant({}, variant)
    return receipt
