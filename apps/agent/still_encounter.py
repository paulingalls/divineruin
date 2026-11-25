"""Runtime participants and discovery for the Still."""

from uuid import uuid4

import check_resolution
import combat_hollow_death
import combat_spatial
import condition_voice_rules
import conditions
import encounter_facts
import still_charm
from action_contracts_still import STILL_ZONE_KINDS
from combat_participant import CombatParticipant
from combat_recharge import action_key
from combat_recharge import initialize as initialize_action_ledger
from combat_terrain import skill_natural_terrain
from declarations import DeclarationType
from patron_location import check_first_stay

CREATURE_ID = "hollow_still"
ANCHOR_HP = (40, 40, 40, 40, 45, 45)
SEARCH_TARGET = "still_anchors"
SEARCH_ACTIONS = {"still_search_perception": "perception", "still_search_arcana": "arcana"}
SEARCH_DC = 18
MEMORIES_ID = "absorbed_memories"


def zone_radius(owner):
    return owner.hollow["corruption_aura"]


def in_zone(state, owner, target_id):
    spatial = combat_spatial.require_spatial(state)
    return combat_spatial.inside(
        combat_spatial.position(spatial, owner.id), combat_spatial.position(spatial, target_id), zone_radius(owner)
    )


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
                damage_affinities={"vulnerable": list(owner.damage_affinities["vulnerable"])},
            )
        )
        state.initiative_order.append(anchor_id)
        state.spatial["positions"][anchor_id] = {**origin, "y": origin["y"] + index - 3}
        state.spatial["speeds"][anchor_id] = 0
    owner.still_dormant = True
    initialize_action_ledger(owner, state.round_number)
    for action in owner.action_pool:
        if action.get("kind") in STILL_ZONE_KINDS:
            owner.action_ledger[action_key(action)] = {"remaining": 0, "round": state.round_number}
    state.still_encounter = {
        "owner_id": owner.id,
        "anchor_ids": ids,
        "revealed_ids": [],
        "phase": "active",
        "pending_rejection": None,
    }
    combat_spatial.require_spatial(state)
    validate(state)


def _valid_trigger(trigger, revealed):
    return (
        isinstance(trigger, dict)
        and set(trigger) == {"anchor_id", "execution_id"}
        and trigger["anchor_id"] in revealed
        and isinstance(trigger["execution_id"], str)
        and bool(trigger["execution_id"])
    )


def _validate_held_zone(state, owner, revealed):
    for head in state.held_actions:
        execution = head.get("still_zone")
        if execution is None:
            continue
        from combat_action_availability import replay_valid
        from declarations import resolve_declaration

        declaration = resolve_declaration(head["declaration"])
        from combat_ability import _find_action

        action = _find_action(owner, declaration.action)
        if (
            not isinstance(execution, dict)
            or action is None
            or action.get("kind") not in STILL_ZONE_KINDS
            or head["actor_id"] != owner.id
            or not replay_valid(state, head, owner, action, declaration)
            or set(execution) != {"targets", "trigger", "duration", "results"}
        ):
            raise ValueError("Invalid held Still zone action receipt")
        trigger = execution["trigger"]
        targets = execution["targets"]
        results = execution["results"]
        if (
            (action["kind"] == "rejection" and not _valid_trigger(trigger, revealed))
            or (action["kind"] == "final_stillness" and trigger is not None)
            or type(execution["duration"]) is not int
            or execution["duration"] < 1
            or not isinstance(targets, list)
            or any(key not in state.initiative_order for key in targets)
            or len(set(targets)) != len(targets)
            or not isinstance(results, list)
            or any(not isinstance(result, dict) for result in results)
            or [result.get("target_id") for result in results] != targets[: len(results)]
        ):
            raise ValueError("Invalid held Still zone action progress")


def validate(state):
    owners = [p for p in state.participants if p.creature_id == CREATURE_ID]
    record = state.still_encounter
    if not owners and record is None and state.encounter_id != CREATURE_ID:
        return
    if (
        len(owners) != 1
        or not isinstance(record, dict)
        or not {"owner_id", "anchor_ids", "revealed_ids", "phase"} <= record.keys()
        or record.keys() - {"owner_id", "anchor_ids", "revealed_ids", "phase", "pending_rejection", "illusion"}
    ):
        raise ValueError("Invalid Still snapshot owner or record")
    (owner,) = owners
    ids = anchor_ids(owner.id)
    if record["owner_id"] != owner.id or record["anchor_ids"] != ids:
        raise ValueError("Invalid Still anchor identities")
    revealed = record["revealed_ids"]
    if not isinstance(revealed, list) or any(key not in ids for key in revealed) or len(set(revealed)) != len(revealed):
        raise ValueError("Invalid Still revealed anchors")
    pending = record.get("pending_rejection")
    if type(owner.still_dormant) is not bool or (
        pending is not None and (owner.still_dormant or not _valid_trigger(pending, revealed))
    ):
        raise ValueError("Invalid Still pending Rejection")
    _validate_held_zone(state, owner, revealed)
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
    for action in owner.action_pool:
        if "recharge" in action and action_key(action) not in owner.action_ledger:
            raise ValueError("Missing Still action budget")
    initialize_action_ledger(owner, state.round_number)
    for action in owner.action_pool:
        remaining = owner.action_ledger.get(action_key(action), {}).get("remaining")
        if (
            action.get("kind") == "final_stillness"
            and remaining
            and (sum(anchor.is_fallen for anchor in anchors) < action["minimum_destroyed_anchors"])
        ):
            raise ValueError("Final Stillness armed before enough Still anchors fell")
        if action.get("kind") == "rejection" and remaining and pending is None:
            raise ValueError("Still Rejection armed without a pending attack")
    if record.get("illusion") is not None:
        from still_illusions import validate as validate_illusion

        validate_illusion(state, record["illusion"])
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


def record_attack(state, attacker, target, action):
    if state is None:
        return
    record = state.still_encounter
    if record and attacker.is_ally and target.id in record["revealed_ids"] and not target.is_fallen:
        if "spell_id" in action:
            from spells import get_spell

            if not get_spell(action["spell_id"]).hostile:
                return
        state.get_participant(record["owner_id"]).still_dormant = False
        record["pending_rejection"] = {"anchor_id": target.id, "execution_id": uuid4().hex}


def owner_alias(state, participant_id):
    record = state.still_encounter if state is not None else None
    return record["owner_id"] if record and participant_id in record["anchor_ids"] else participant_id


def is_owner(state, participant_id):
    record = state.still_encounter if state is not None else None
    return record is not None and record["owner_id"] == participant_id


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
    if record and (
        actor_id in record["anchor_ids"]
        or (actor_id == record["owner_id"] and state.get_participant(actor_id).still_dormant)
    ):
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
        "charmed_player_ids": [
            p.id
            for p in state.participants
            if p.type == "player" and any(c["type"] == "charmed" and c["source"] == owner.id for c in p.conditions)
        ],
        "revealed_anchor_ids": record["revealed_ids"],
        "pending_rejection_anchor_id": pending["anchor_id"] if (pending := record.get("pending_rejection")) else None,
        "illusion": record.get("illusion"),
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
            first_stay=await check_first_stay(player, session, skill, player_id=actor.id, conn=conn),
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


async def after_damage(session, state, target, *, conn, queries, was_fallen) -> list[dict]:
    if state is None or state.still_encounter is None:
        return []
    record = state.still_encounter
    if target.id not in record["anchor_ids"]:
        return []
    owner = state.get_participant(record["owner_id"])
    before = owner.hp_current
    counted_before = encounter_facts.counted_death(owner)
    anchors = [state.get_participant(key) for key in record["anchor_ids"]]
    owner.hp_current = sum(anchor.hp_current for anchor in anchors)
    if target.is_fallen and not was_fallen:
        destroyed = sum(anchor.is_fallen for anchor in anchors)
        for action in owner.action_pool:
            if action.get("kind") == "final_stillness" and destroyed == action["minimum_destroyed_anchors"]:
                owner.action_ledger[action_key(action)]["remaining"] = 1
    if before > 0 and owner.hp_current == 0:
        from combat_damage import _handle_hp_zero

        was_fallen, resolved_before = owner.is_fallen, owner.hollow_death_resolved
        _handle_hp_zero(session, state, owner, overkill=0, was_fallen=was_fallen, hp_status="fallen", sounds=[])
        record["phase"] = "destroyed"
        await still_charm.end_instance(state, owner.id, session.party.member_ids, queries=queries, conn=conn)
        if combat_hollow_death.new_destruction(owner, resolved_before, was_fallen, before):
            await combat_hollow_death.accrue_death(session, state, owner, conn=conn, queries=queries)
        return await encounter_facts.renew_on_death(state, owner, counted_before, queries=queries, conn=conn)
    return []
