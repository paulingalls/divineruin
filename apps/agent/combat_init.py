"""Combat initialization — _start_combat_impl, the combat-entry handoff behind
enter_mode(mode="combat") (mode_tools.py). Rolls initiative, persists CombatState,
and hands off to CombatAgent."""

import json
import logging
import uuid

from livekit.agents.llm import ToolError
from livekit.agents.voice import RunContext

import check_resolution_save
import combat_enhancers
import combat_resolution
import conditions
import db_content_queries
import db_mutations
import db_queries
import event_types as E
import rules_engine
from combat_support import _participant_summary, _publish_sounds
from combat_ui_update import build_combat_ui_update
from companion_profiles import get_companion_profile
from companion_scaling import (
    companion_attacks_to_action_pool,
    scale_companion_stats_to_player_level,
)
from db_errors import validated_player_conditions
from encounter_roles import derive_role_stats
from encounter_stance import resolve_encounter_stance
from game_events import publish_game_event
from region_types import REGION_CITY
from session_data import CombatParticipant, CombatState, SessionData
from tool_support import SOUND_COMBAT_START

logger = logging.getLogger("divineruin.tools")


def _validate_enemy_action_conditions(enemies: list[dict]) -> None:
    """Fail loud if any enemy condition action is malformed — the load-boundary strict guard.

    Encounter templates have no strict loader (unlike spells.json / archetype_abilities.json,
    whose loaders fail-loud on applies_condition), so this closes that gap at combat start. For any
    action that declares ``applies_condition`` it requires: (1) the condition is in CONDITION_CATALOG;
    (2) ``save`` is a valid save key — full name OR 3-letter abbrev, matching what the resolver
    accepts (check_resolution_save.is_valid_save_key, one SSOT so the load-gate and runtime agree);
    (3) ``dc`` is an int; (4) ``damage`` is absent or "0" — M13 condition actions are save-based, and
    the resolver does not apply damage, so a damage-bearing condition action would silently deal none
    (debt 5b18023ef5a5) until the combined to-hit+save+damage model lands. Validating HERE turns a
    would-be mid-fight KeyError / silent damage-drop into a fail-loud error at combat entry."""
    for enemy in enemies:
        for action in enemy.get("action_pool", []):
            cond = action.get("applies_condition")
            if cond is None:
                continue
            label = f"enemy {enemy.get('id')!r} action {action.get('name')!r}"
            conditions.assert_known_condition(cond, label)
            if not check_resolution_save.is_valid_save_key(action.get("save")):
                raise ValueError(
                    f"{label} applies_condition needs a valid 'save' attribute, got {action.get('save')!r}"
                )
            if not isinstance(action.get("dc"), int):
                raise ValueError(f"{label} applies_condition needs an int 'dc', got {action.get('dc')!r}")
            if action.get("damage") not in (None, "", "0", 0):
                raise ValueError(
                    f"{label} condition action must be save-based (damage absent or '0') until the "
                    f"combined damage+condition model lands (debt 5b18023ef5a5), got damage {action.get('damage')!r}"
                )


async def _start_combat_impl(
    context: RunContext[SessionData],
    encounter_id: str,
    encounter_description: str,
    *,
    mutations=db_mutations,
    queries=db_queries,
    content=db_content_queries,
) -> str | tuple:
    logger.info("start_combat called: encounter_id=%s", encounter_id)
    session: SessionData = context.userdata

    if session.in_combat:
        raise ToolError("Already in combat. End the current combat first.")

    encounter = await content.get_encounter_template(encounter_id)
    if encounter is None:
        raise ToolError(f"Encounter template '{encounter_id}' not found.")

    player = await queries.get_player(session.player_id)
    if player is None:
        raise ToolError(f"Player '{session.player_id}' not found.")

    # Stance gate (story-008): a gated encounter resolves allied/hostile from the player's
    # reputation with the GATE faction. "allied" stands the encounter down (return a narration
    # string — no combat handoff); "hostile" falls through to the normal combat build. The
    # reputation defaults to neutral (0) when unset — no player_reputation writer ships yet
    # (debt 6e8c1e79a775), so gated encounters resolve hostile in prod until one does.
    stance_gate = encounter.get("stance_gate")
    if stance_gate is not None:
        faction_id = stance_gate.get("faction")
        if not faction_id:
            raise ToolError(f"Encounter '{encounter_id}' has a malformed stance gate: missing 'faction'.")
        faction = await content.get_faction(faction_id)
        if faction is None:
            raise ToolError(f"Stance-gate faction '{faction_id}' not found.")
        reputation = await queries.get_player_faction_reputation(session.player_id, faction_id)
        try:
            stance = resolve_encounter_stance(
                stance_gate,
                reputation if reputation is not None else 0,
                faction.get("reputation_tiers") or {},
            )
        except ValueError as e:
            raise ToolError(f"Encounter '{encounter_id}' has a malformed stance gate: {e}") from e
        if stance == "allied":
            session.record_event(f"{encounter.get('name', encounter_id)} stood down — allied")
            logger.info("start_combat: encounter %s resolved allied; combat averted", encounter_id)
            return f"The {faction.get('name', faction_id)} recognizes you as an ally and stands down. No combat."

    # Build participant dicts for initiative rolling
    player_hp = player.get("hp", {})

    # Multi-player combat build (M14 story-003): session.party.member_ids is the SSOT for
    # combat participation (not the mirrored session.player_id field). A solo party has
    # exactly one member — the already-fetched primary row — so this reuses `player` rather
    # than double-querying, and produces the same single participant as before the refactor.
    member_players: list[tuple[str, dict]] = []
    for member_id in session.party.member_ids:
        row = player if member_id == session.player_id else await queries.get_player(member_id)
        if row is None:
            raise ToolError(f"Player '{member_id}' not found.")
        member_players.append((member_id, row))

    initiative_inputs: list[dict] = [
        {
            "id": mid,
            "name": row.get("name", mid),
            "attributes": row.get("attributes", {}),
        }
        for mid, row in member_players
    ]

    enemies = encounter.get("enemies", [])
    # Surface a malformed enemy condition action as a DM-narratable ToolError (the _start_combat_impl
    # content-error convention, matching the stance-gate above), not a raw ValueError at the tool boundary.
    try:
        _validate_enemy_action_conditions(enemies)
    except ValueError as e:
        raise ToolError(f"Encounter '{encounter_id}' has a malformed enemy condition action: {e}") from e
    for enemy in enemies:
        initiative_inputs.append(
            {
                "id": enemy["id"],
                "name": enemy.get("name", enemy["id"]),
                "attributes": enemy.get("attributes", {}),
            }
        )

    # Add companion if present and conscious. Stats come from the companions.json profile
    # (companion_scaling: level scaler + action_pool translator), NOT npcs.json — and they are
    # independent of relationship (session_count/affinity); combat is never relationship-gated
    # (spec L871, the negative invariant).
    companion_scaled = None
    companion_action_pool: list[dict] = []
    if session.companion_can_act and session.companion:
        try:
            profile = get_companion_profile(session.companion.id)
            # Both translators consume the profile and fail loud on a corrupt seed (an attack
            # whose damage/hit has no parseable term). Keep them inside the try so a catalog
            # inconsistency surfaces as a DM-narratable ToolError, just like an unknown id —
            # instead of a raw ValueError that crashes combat init.
            companion_scaled = scale_companion_stats_to_player_level(
                profile, player_hp.get("max", 1), player.get("level", 1)
            )
            companion_action_pool = companion_attacks_to_action_pool(profile)
        except ValueError as e:
            # Unknown/unloaded companion id (stale id) or a malformed profile attack. Surface as
            # a ToolError so the DM narrates cleanly — matching the encounter/player/faction
            # not-found convention above — instead of crashing combat init.
            raise ToolError(f"Companion '{session.companion.id}' not found: {e}") from e
        initiative_inputs.append(
            {
                "id": session.companion.id,
                "name": session.companion.name,
                "attributes": companion_scaled.attributes,
            }
        )

    # Roll initiative and build lookup
    initiative_entries = combat_resolution.roll_initiative(initiative_inputs)
    initiative_order = [e.participant_id for e in initiative_entries]
    initiative_by_id = {e.participant_id: e.total for e in initiative_entries}

    # Build CombatParticipants — one per party member (M14 story-003). Each member's
    # conditions are loaded and Exhaustion-capped independently (M4.4 story-005): a
    # pre-combat Exhausted/Wounded/Hollowed on ONE member must not bleed onto siblings. They
    # ride the already-fetched row, so no extra query — validate at this boundary (fail-loud
    # on a corrupt stored dict) and clamp Exhausted to the iron-constitution cap (the
    # in-scope apply site until a forced-march producer). A corrupt stored condition row is a
    # data-integrity error in the same family as a malformed companion profile (below) — the
    # shared boundary guard surfaces it as a DM-narratable ToolError instead of a raw
    # ValueError (db_tool narrows on JSONDecodeError, so a bare ValueError here would escape
    # uncaught and crash combat init).
    participants: list[CombatParticipant] = []
    for mid, row in member_players:
        row_hp = row.get("hp", {})
        # Synthesize the member's combat action_pool from equipped weapons. Each equipment
        # entry is already resolve_attack-shaped (name/damage/damage_type/properties), so a
        # player attack declaration resolves through the same packet path as enemies and
        # companions (story-003 unified resolution). Non-weapon gear (no `damage`) is skipped;
        # spells/abilities are out-of-band tools in M4.1, not action_pool entries.
        row_equipment = row.get("equipment", {})
        row_action_pool = [item for item in row_equipment.values() if isinstance(item, dict) and item.get("damage")]
        validated_conditions = validated_player_conditions(row, mid)
        row_conditions = conditions.cap_exhaustion(
            validated_conditions,
            rules_engine.exhaustion_stack_cap(row),
        )
        participants.append(
            CombatParticipant(
                id=mid,
                name=row.get("name", mid),
                type="player",
                initiative=initiative_by_id[mid],
                hp_current=row_hp.get("current", 1),
                hp_max=row_hp.get("max", 1),
                ac=row.get("ac", 10),
                attributes=row.get("attributes", {}),
                level=row.get("level", 1),
                action_pool=row_action_pool,
                # Declaration enhancers granted via players.data.flags (M4.2, story-004). Only
                # extra_attack is grantable today; the rest populate when their grants land.
                enhancers=combat_enhancers.enhancers_from_flags(row.get("flags")),
                conditions=row_conditions,
                # Save proficiencies (M13 close-fix): carry the player's proficient saves onto
                # the participant so resolve_saving_throw adds the bonus when an enemy imposes
                # a save (e.g. Frightened). Sourced from players.data (creation_rules.py:309).
                saving_throw_proficiencies=row.get("saving_throw_proficiencies", []),
            )
        )
    for enemy in enemies:
        # Apply the encounter-role overlay (M4.7, story-001): the same base stat block becomes a
        # Minion (halved, actives stripped) or a Boss (doubled, signature + legendary) per its
        # ``role`` tag. derive_role_stats is pure and returns a NEW dict; an untagged enemy defaults
        # to "standard" (identity), so pre-M4.7 templates build exactly as before.
        derived = derive_role_stats(enemy, enemy.get("role", "standard"))
        participants.append(
            CombatParticipant(
                id=derived["id"],
                name=derived.get("name", derived["id"]),
                type="enemy",
                initiative=initiative_by_id[enemy["id"]],
                hp_current=derived.get("hp", 1),
                hp_max=derived.get("hp", 1),
                ac=derived.get("ac", 10),
                attributes=derived.get("attributes", {}),
                level=derived.get("level", 1),
                action_pool=derived.get("action_pool", []),
                xp_value=derived.get("xp_value", 0),
                role=derived["role"],
                attack_mod=derived["attack_mod"],
                damage_mult=derived["damage_mult"],
                dc_mod=derived["dc_mod"],
                legendary_actions=derived["legendary_actions"],
                signature_ability=derived["signature_ability"],
                # Loot/currency overlay (M4.7, story-002): carry the template enemy's category +
                # loot_table_id onto the participant so _end_combat_db can roll role-scaled loot
                # and currency on victory. derive_role_stats copies the source enemy, so these ride
                # through; empty-string defaults keep untagged/pre-M4.7 enemies inert (no drops).
                category=derived.get("category", ""),
                loot_table_id=derived.get("loot_table_id", ""),
            )
        )

    # Add companion participant
    if companion_scaled is not None and session.companion:
        participants.append(
            CombatParticipant(
                id=session.companion.id,
                name=session.companion.name,
                type="companion",
                initiative=initiative_by_id[session.companion.id],
                hp_current=companion_scaled.hp,
                hp_max=companion_scaled.hp,
                ac=companion_scaled.ac,
                attributes=companion_scaled.attributes,
                level=companion_scaled.level,
                action_pool=companion_action_pool,
                # Carry the companion's save proficiencies (M13 close-fix, symmetric with the player
                # build) so an enemy-inflicted save-based condition honors them — a WIS-proficient
                # companion resists Frightened like a proficient player. `profile` is bound here
                # (companion_scaled is not None => the profile-load try succeeded above).
                saving_throw_proficiencies=list(profile.save_proficiencies),
            )
        )

    combat_id = f"combat_{uuid.uuid4().hex[:8]}"
    combat_state = CombatState(
        combat_id=combat_id,
        participants=participants,
        initiative_order=initiative_order,
        round_number=1,
        current_turn_index=0,
        location_id=session.location_id,
    )

    # Persist and update session
    await mutations.save_combat_state(combat_id, combat_state.to_dict())
    session.combat_state = combat_state

    # Reset per-encounter weapon durability flags so each encounter is self-contained
    # (a swing outside combat won't leak into this encounter's end-of-combat accrual).
    session.weapon_used_this_encounter = False
    session.weapon_crit_vs_heavy = False
    session.draethar_inner_fire_used = False  # Inner Fire is once per encounter (M3.4)

    # Build initiative summary once for event + response
    initiative_summary = [
        {"id": e.participant_id, "name": e.name, "roll": e.roll, "total": e.total} for e in initiative_entries
    ]

    # Publish events
    await publish_game_event(
        session.room,
        E.COMBAT_STARTED,
        {
            "combat_id": combat_id,
            "encounter_id": encounter_id,
            "difficulty": encounter.get("difficulty", "moderate"),
            "initiative_order": initiative_summary,
        },
        event_bus=session.event_bus,
    )
    # Initial HUD push so the combat-tracker has live combatants from round 1
    # (M12 sprint-029 close fix, concern 4045481bfc3e). Without this the
    # producer only fires at Beat-4 wrap, leaving the tracker empty for all of
    # round 1. Direct publish (no in-tx sink here); ordered AFTER COMBAT_STARTED
    # so the mobile session.setCombat(true) gate latches before render.
    await publish_game_event(
        session.room,
        E.COMBAT_UI_UPDATE,
        build_combat_ui_update(combat_state),
        event_bus=session.event_bus,
    )
    await _publish_sounds(session, [SOUND_COMBAT_START])

    session.record_event(f"Combat started: {encounter.get('name', encounter_id)}")

    response = {
        "combat_id": combat_id,
        "encounter_name": encounter.get("name", encounter_id),
        "encounter_description": encounter_description,
        "initiative_order": initiative_summary,
        "participants": [_participant_summary(p) for p in participants],
    }
    logger.info("start_combat result: combat_id=%s, %d participants", combat_id, len(participants))

    # Record which agent type to return to after combat
    current_agent = context.session.current_agent
    session.pre_combat_agent_type = getattr(current_agent, "_agent_type", REGION_CITY)

    # Build CombatAgent with combat-entry context for handoff
    from livekit.agents.llm import ChatContext

    from combat_agent import create_combat_agent

    parts = [f"Combat begins: {encounter_description}"]
    loc_name = getattr(session, "cached_location_name", None) or session.location_id
    parts.append(f"Location: {loc_name}.")
    if session.companion and session.companion.is_present:
        parts.append(f"{session.companion.name} fights alongside the player.")

    combat_ctx = ChatContext()
    combat_ctx.add_message(role="system", content=" ".join(parts))

    return create_combat_agent(chat_ctx=combat_ctx), json.dumps(response)
