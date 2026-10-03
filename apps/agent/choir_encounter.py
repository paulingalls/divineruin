"""The Choir's searchable sound and single damage owner."""

import check_resolution
import condition_voice_rules
from declarations import DeclarationType

SEARCH_TARGET = "choir_sound"
SEARCH_ACTIONS = {"choir_search_perception": "perception", "choir_search_arcana": "arcana"}


def owner(state):
    return next((p for p in state.participants if p.creature_id == "hollow_choir"), None)


def initialize(state):
    source = owner(state)
    if source is not None:
        state.choir_encounter = {"owner_id": source.id, "phase": "search", "aura_receipts": {}}


def validate(state):
    source = owner(state)
    record = state.choir_encounter
    if source is not None and record is None and state.encounter_id == "":
        return
    if source is None:
        if record is not None:
            raise ValueError("Choir state without source")
        return
    if not isinstance(record, dict) or record.get("owner_id") != source.id:
        raise ValueError("Choir source identity missing")
    if set(record) != {"owner_id", "phase", "aura_receipts"}:
        raise ValueError("invalid Choir state fields")
    if record["phase"] not in {"search", "exposed", "destroyed"}:
        raise ValueError("invalid Choir phase")
    if (record["phase"] == "destroyed") != (source.hp_current == 0 and source.hollow_death_resolved):
        raise ValueError("Choir phase disagrees with owner destruction")
    if not isinstance(record["aura_receipts"], dict) or any(
        actor not in state.initiative_order or type(turn) is not int or not 1 <= turn <= state.round_number
        for actor, turn in record["aura_receipts"].items()
    ):
        raise ValueError("invalid Choir aura receipts")


def facts(state):
    if state.choir_encounter is None:
        return None
    validate(state)
    source = owner(state)
    assert source is not None
    phase = state.choir_encounter["phase"]
    result = {
        "phase": phase,
        "cue": "Every voice may be false. The hum carries familiar voices, each a little wrong.",
        "targeting_guidance": "Memory Predator favors strong fear, grief, love, or rage. The DM chooses; speak Stolen Melody in the stolen voice.",
    }
    if phase == "search":
        result.update(
            search_target_id=SEARCH_TARGET,
            search_actions=[
                {"type": "interact", "action": action, "target_id": SEARCH_TARGET, "skill": skill, "dc": 18}
                for action, skill in SEARCH_ACTIONS.items()
            ],
        )
    elif phase == "exposed":
        result.update(
            core_id=source.id,
            engine_damage_spell_ids=["arcane_bolt"],
            core_defenses={
                "ac": 18,
                "hp_pool": 200,
                "allowed_damage": ["psychic", "radiant", "thunder", "force"],
                "vulnerable_to": ["psychic", "radiant"],
                "no_touch_grapple_restraint": True,
            },
            cue=exposure_cue(state, source),
        )
    else:
        result["cue"] = source.catalog_narration["death_cue"]
    return result


def exposure_cue(state, source):
    from combat_spatial import position

    listener = next(p for p in state.participants if p.type == "player")
    origin, core = position(state.spatial, listener.id), position(state.spatial, source.id)
    directions = []
    for axis, positive, negative in (("x", "east", "west"), ("y", "north", "south"), ("z", "above", "below")):
        delta = core[axis] - origin[axis]
        if delta:
            directions.append(f"{abs(delta):g} feet {positive if delta > 0 else negative}")
    direction = ", ".join(directions) or "at your position"
    return f"The layered voices converge on one pulsing note, {direction}. Strike the exposed resonance core."


def guard_declaration(state, actor_id, declaration):
    source = owner(state)
    if source is None or state.choir_encounter is None or actor_id == source.id:
        return
    targets = declaration.target_ids or [declaration.target_id]
    if declaration.type is DeclarationType.INTERACT and declaration.action in SEARCH_ACTIONS:
        if declaration.target_id != SEARCH_TARGET or state.choir_encounter["phase"] != "search":
            raise ValueError("Choir search requires its visible sound in Search")
        return
    if any(target in {source.id, SEARCH_TARGET, f"{source.id}_core"} for target in targets):
        if declaration.type is DeclarationType.MANEUVER:
            raise ValueError("The Choir has no physical form to grapple, restrain or shove")
        if state.choir_encounter["phase"] != "exposed" or SEARCH_TARGET in targets:
            raise ValueError("The hidden Choir core must first be discovered with a declared search")
        if declaration.type is DeclarationType.ABILITY and declaration.action in {
            "arcane_frost_touch",
            "divine_revivify",
            "primal_healing_touch",
        }:
            raise ValueError("The Choir cannot be targeted by touch spells")


def stale_reason(state, actor_id, declaration):
    source = owner(state)
    if source is None or state.choir_encounter is None or actor_id == source.id:
        return None
    if (
        declaration.type is DeclarationType.INTERACT
        and declaration.action in SEARCH_ACTIONS
        and declaration.target_id == SEARCH_TARGET
        and state.choir_encounter["phase"] != "search"
    ):
        return "The Choir search was already completed"
    targets = declaration.target_ids or [declaration.target_id]
    if state.choir_encounter["phase"] == "destroyed" and source.id in targets:
        return "The Choir core was already destroyed"
    return None


async def search(session, state, actor, declaration, *, queries, conn):
    guard_declaration(state, actor.id, declaration)
    skill = SEARCH_ACTIONS[declaration.action]
    player = await queries.get_player(actor.id, conn=conn, for_update=True)
    if player is None:
        raise ValueError(f"Missing Choir search actor {actor.id!r}")
    result = check_resolution.resolve_skill_check_dc(
        condition_voice_rules.roll_data(player, state, actor.id),
        skill,
        18,
        ally_present=session.ally_present_for(actor.id),
        hearing_only=skill == "perception",
    )
    import conditions

    actor.conditions = conditions.remove_conditions(actor.conditions, result.consumed_conditions)
    if result.success:
        state.choir_encounter["phase"] = "exposed"
    packet = {
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
        "choir": facts(state),
    }
    return packet


def damage(target, amount, damage_type):
    if target.creature_id != "hollow_choir":
        return amount
    if damage_type not in {"psychic", "radiant", "thunder", "force"}:
        return 0
    return amount * (2 if damage_type in {"psychic", "radiant"} else 1)


def destroyed(state):
    source = owner(state)
    if source is None or not source.hollow_death_resolved:
        return
    state.choir_encounter["phase"] = "destroyed"
    silences = {key: effect for key, effect in state.choir_silences.items() if effect["source_id"] == source.id}
    for zone_id, effect in silences.items():
        state.spatial["zones"].pop(zone_id)
        state.spatial["locations"].pop(effect["center_id"])
        del state.choir_silences[zone_id]
    state.spatial["zones"] = {
        key: zone for key, zone in state.spatial["zones"].items() if zone.get("center_id") != source.id
    }
    source.choir_suppression = None
    source.choir_silence_exposed = False
    for actor in state.participants:
        actor.conditions = [condition for condition in actor.conditions if condition.get("source") != source.id]


async def turn_start(session, state, actor, *, conn, concentration_break_mod):
    if state.choir_encounter is None or state.choir_encounter["phase"] == "destroyed":
        return None
    from condition_restrictions import cannot_act

    source = owner(state)
    assert source is not None
    if actor is None or actor.id == source.id or actor.is_fallen or actor.is_dead or cannot_act(actor.conditions):
        return None
    receipts = state.choir_encounter["aura_receipts"]
    if receipts.get(actor.id) == state.round_number:
        return None
    import check_resolution_save
    import combat_spatial

    receipts[actor.id] = state.round_number
    if not combat_spatial.inside(
        combat_spatial.position(state.spatial, source.id),
        combat_spatial.position(state.spatial, actor.id),
        600,
    ):
        return None
    save = check_resolution_save.roll_participant_save(
        actor,
        "wisdom",
        15,
        "Aura of Lost Voices",
        bonus_dice_eligible=False,
    )
    broken = None
    if (
        not save.success
        and actor.type == "player"
        and session.member_state(actor.id).concentration.spell_id is not None
    ):
        broken = await concentration_break_mod.end_concentration(session, actor.id, combat_state=state, conn=conn)
    return {
        "actor_id": actor.id,
        "save_type": "wisdom",
        "dc": 15,
        "success": save.success,
        "concentration_broken": broken,
        "cue": "Lost voices tug at your focus.",
    }
