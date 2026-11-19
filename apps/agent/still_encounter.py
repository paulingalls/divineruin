"""Runtime participants and discovery for the Still."""

import check_resolution
import combat_hollow_death
import combat_spatial
import condition_voice_rules
import conditions
from combat_participant import CombatParticipant
from combat_terrain import skill_natural_terrain
from declarations import DeclarationType
from patron_location import check_first_stay

CREATURE_ID = "hollow_still"
ANCHOR_HP = (40, 40, 40, 40, 45, 45)
SEARCH_TARGET = "still_anchors"
SEARCH_ACTIONS = {"still_search_perception": "perception", "still_search_arcana": "arcana"}
SEARCH_DC = 18
MEMORIES_ID = "absorbed_memories"


def anchor_ids(owner_id):
    return [f"{owner_id}_anchor_{index}" for index in range(1, len(ANCHOR_HP) + 1)]


def initialize(state):
    owners = [p for p in state.participants if p.creature_id == CREATURE_ID]
    if not owners:
        return
    (owner,) = owners
    if owner.hp_max != sum(ANCHOR_HP):
        raise ValueError("Still owner HP must equal the six anchor maxima")
    ids = anchor_ids(owner.id)
    if any(state.get_participant(anchor_id) is not None for anchor_id in ids):
        raise ValueError("Still anchor identity collides with another participant")
    origin = state.spatial["positions"][owner.id]
    for index, (anchor_id, hp) in enumerate(zip(ids, ANCHOR_HP, strict=True), 1):
        state.participants.append(
            CombatParticipant(
                id=anchor_id,
                name=f"Anchor {index}",
                type="enemy",
                initiative=0,
                hp_current=hp,
                hp_max=hp,
                ac=20,
                tier=owner.tier,
                loot_table_id="loot_still_anchor",
            )
        )
        state.initiative_order.append(anchor_id)
        state.spatial["positions"][anchor_id] = {**origin, "y": origin["y"] + index - 3}
        state.spatial["speeds"][anchor_id] = 0
    state.still_encounter = {"owner_id": owner.id, "anchor_ids": ids, "revealed_ids": [], "phase": "active"}
    combat_spatial.require_spatial(state)
    validate(state)


def validate(state):
    owners = [p for p in state.participants if p.creature_id == CREATURE_ID]
    record = state.still_encounter
    if not owners and record is None and state.encounter_id != CREATURE_ID:
        return
    if (
        len(owners) != 1
        or not isinstance(record, dict)
        or set(record) != {"owner_id", "anchor_ids", "revealed_ids", "phase"}
    ):
        raise ValueError("Invalid Still snapshot owner or record")
    (owner,) = owners
    ids = anchor_ids(owner.id)
    if record["owner_id"] != owner.id or record["anchor_ids"] != ids:
        raise ValueError("Invalid Still anchor identities")
    revealed = record["revealed_ids"]
    if not isinstance(revealed, list) or any(key not in ids for key in revealed) or len(set(revealed)) != len(revealed):
        raise ValueError("Invalid Still revealed anchors")
    anchors = [p for p in state.participants if p.id in ids]
    if sorted(p.id for p in anchors) != ids:
        raise ValueError("Missing or duplicate Still anchor participant")
    for key, hp in zip(ids, ANCHOR_HP, strict=True):
        anchor = state.get_participant(key)
        if (
            anchor.type != "enemy"
            or anchor.hp_max != hp
            or type(anchor.hp_current) is not int
            or not 0 <= anchor.hp_current <= hp
            or anchor.is_fallen != (anchor.hp_current == 0)
            or (anchor.is_fallen and key not in revealed)
        ):
            raise ValueError("Invalid Still anchor HP or fallen state")
    total = sum(anchor.hp_current for anchor in anchors)
    destroyed = total == 0
    if (
        owner.type != "enemy"
        or owner.hp_max != sum(ANCHOR_HP)
        or owner.hp_current != total
        or owner.is_fallen != destroyed
        or owner.is_dead != destroyed
        or owner.hollow_death_resolved != destroyed
        or record["phase"] != ("destroyed" if destroyed else "active")
    ):
        raise ValueError("Still phase disagrees with owner HP or destruction")


def hidden_ids(state):
    record = state.still_encounter
    return set(record["anchor_ids"]) - set(record["revealed_ids"]) if record else set()


def protected_ids(state):
    return hidden_ids(state) | {state.still_encounter["owner_id"]} if state.still_encounter else set()


def guard_target(state, target_id):
    if state is None or state.still_encounter is None:
        return
    if target_id == state.still_encounter["owner_id"]:
        raise ValueError("The Still cannot be targeted directly. Strike its revealed anchors.")
    if target_id in hidden_ids(state):
        raise ValueError("An unrevealed Still anchor requires a declared search before it can be targeted.")


def guard_declaration(state, actor_id, declaration):
    record = state.still_encounter
    if record and actor_id in [record["owner_id"], *record["anchor_ids"]]:
        raise ValueError("The Still and its anchors take no actions.")
    if declaration.type is DeclarationType.INTERACT and declaration.action in SEARCH_ACTIONS:
        if record is None or declaration.target_id != SEARCH_TARGET:
            raise ValueError("Still searches require the Still's surfaced search target.")
        return
    for target_id in [declaration.target_id, *(declaration.target_ids or [])]:
        guard_target(state, target_id)


def facts(state):
    record = state.still_encounter
    if record is None:
        return None
    owner = state.get_participant(record["owner_id"])
    return {
        "phase": record["phase"],
        "revealed_anchor_ids": record["revealed_ids"],
        "search_actions": [
            {"type": "interact", "action": action, "target_id": SEARCH_TARGET, "skill": skill, "dc": SEARCH_DC}
            for action, skill in SEARCH_ACTIONS.items()
        ]
        if hidden_ids(state)
        else [],
        "cue": (
            owner.catalog_narration["death_cue"]
            if record["phase"] == "destroyed"
            else "Search for the anchors. Strike only revealed anchors."
        ),
    }


def settlement_facts(state, loot_pool):
    details = facts(state)
    if details is None:
        return None
    for drop in loot_pool:
        if drop["item_id"] == MEMORIES_ID:
            details["absorbed_memories"] = drop["quantity"]
            details["cue"] += f" The Still releases {drop['quantity']} of the memories it absorbed."
    return details


async def search(session, state, actor, declaration, *, queries, conn, progress=None):
    hidden = hidden_ids(state)
    if not hidden:
        return {"actor_id": actor.id, "resolved": False, "reason": "All six Still anchors have been found."}
    skill = SEARCH_ACTIONS[declaration.action]

    async def roll():
        player = await queries.get_player(actor.id, conn=conn, for_update=True)
        if player is None:
            raise ValueError(f"Missing Still search actor {actor.id!r}")
        return check_resolution.resolve_skill_check_dc(
            condition_voice_rules.roll_data(player, state, actor.id),
            skill,
            SEARCH_DC,
            ally_present=session.allies_present_for(actor.id),
            natural_terrain=await skill_natural_terrain(session, player, skill, combat_state=state),
            hearing_only=skill == "perception",
            first_stay=await check_first_stay(player, session, skill, conn=conn),
        )

    result = await progress.skill(session, actor.id, roll) if progress is not None else await roll()
    if result is None:
        return {}
    actor.conditions = conditions.remove_conditions(actor.conditions, result.consumed_conditions)
    if result.success:
        record = state.still_encounter
        record["revealed_ids"].append(next(key for key in record["anchor_ids"] if key in hidden))
    return {
        "actor_id": actor.id,
        "resolved": True,
        "declaration_type": "interact",
        "action": declaration.action,
        "skill": skill,
        "dc": result.dc,
        "roll": result.roll,
        "modifier": result.modifier,
        "total": result.total,
        "success": result.success,
        "auto_fail": result.auto_fail,
        "still": facts(state),
        **({"gift_name": result.gift_name} if result.gift_name else {}),
    }


async def after_damage(session, state, target, *, conn, queries):
    if state is None or state.still_encounter is None:
        return
    record = state.still_encounter
    if target.id not in record["anchor_ids"]:
        return
    owner = state.get_participant(record["owner_id"])
    before = owner.hp_current
    owner.hp_current = sum(state.get_participant(key).hp_current for key in record["anchor_ids"])
    if before > 0 and owner.hp_current == 0:
        combat_hollow_death.mark_destroyed(owner)
        owner.is_fallen = True
        record["phase"] = "destroyed"
        await combat_hollow_death.accrue_death(session, state, owner, conn=conn, queries=queries)
