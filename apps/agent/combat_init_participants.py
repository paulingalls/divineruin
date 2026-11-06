"""Translate catalog references and party rows into initialized combat participants."""

from livekit.agents.llm import ToolError

import abilities
import choir_scene
import combat_enhancers
import combat_resolution
import conditions
import item_effects
import rules_engine
from combat_init_validation import _validate_enemy_tiers, validate_enemy_action_shapes, validate_enemy_resistance_tags
from combat_spatial_entry import build_spatial
from companion_profiles import get_companion_profile
from companion_scaling import companion_attacks_to_action_pool, scale_companion_stats_to_player_level
from db_errors import validated_player_conditions
from encounter_actions import validate_encounter_actions
from encounter_references import validate_encounter_references
from session_data import CombatParticipant


def class_reaction_ids(player_class: str, player_level: int) -> list[str]:
    """A class's catalog reaction ids. The capstone harness hand-builds its combat and calls this too,
    so a harness player cannot silently lack the ids a real one is handed at a window."""
    return [
        ability.id
        for ability in abilities.get_archetype_abilities(player_class)
        if ability.ability_type == "reaction"
        and abilities.owns_ability(player_class, player_level, ability, owns_elective=False)
    ]


async def assemble_participants(session, encounter, encounter_id, member_players, *, content, queries):
    initiative_inputs: list[dict] = [
        {
            "id": mid,
            "name": row.get("name", mid),
            "attributes": row.get("attributes", {}),
        }
        for mid, row in member_players
    ]

    enemies = []
    try:
        validate_encounter_references(encounter)
        for reference in encounter["enemies"]:
            enemies.append(
                await content.load_creature_enemy(
                    reference["creature_id"],
                    encounter_id=encounter_id,
                    enemy_id=reference["id"],
                    role=reference["role"],
                )
            )
        validate_enemy_action_shapes(enemies)
        validate_encounter_actions(enemies)
        validate_enemy_resistance_tags(enemies)
        _validate_enemy_tiers(enemies)
    except ValueError as e:
        raise ToolError(f"Encounter '{encounter_id}' has malformed enemy data: {e}") from e
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
            # The companion was hydrated from the primary's row, so it scales to its owner, not
            # to whichever member's turn opened the fight.
            owner = dict(member_players)[session.primary_player_id]
            companion_scaled = scale_companion_stats_to_player_level(
                profile, owner.get("hp", {}).get("max", 1), owner.get("level", 1)
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

    try:
        spatial = build_spatial(
            encounter,
            member_players,
            enemies,
            (session.companion.id, profile.speed)
            if companion_scaled is not None and session.companion is not None
            else None,
        )
    except ValueError as error:
        raise ToolError(str(error)) from error

    retained_choir = await choir_scene.preflight(session, encounter, queries=queries)

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
        try:
            inventory = await queries.get_player_inventory(mid)
            traits = item_effects.combat_traits([item for item in inventory if item.get("type") != "material"])
        except ValueError as error:
            raise ToolError(f"Player {mid!r} has malformed inventory: {error}") from error
        row_hp = row.get("hp", {})
        player_class = row.get("class")
        if not isinstance(player_class, str):
            raise ToolError(f"Player {mid!r} has invalid class {player_class!r}.")
        archetype_abilities = abilities.get_archetype_abilities(player_class)
        if not archetype_abilities:
            raise ToolError(f"Player {mid!r} has class {player_class!r} with no catalog abilities.")
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
        player_level = row["level"]
        reaction_ids = class_reaction_ids(player_class, player_level)
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
                level=player_level,
                action_pool=row_action_pool,
                # Declaration enhancers granted via players.data.flags (M4.2, story-004). Only
                # extra_attack is grantable today; the rest populate when their grants land.
                enhancers=combat_enhancers.enhancers_from_flags(row.get("flags")),
                conditions=row_conditions,
                has_reaction_ability=bool(reaction_ids),
                reaction_ids=reaction_ids,
                prone_immunity=rules_engine.prone_immunity(row),
                # Save proficiencies (M13 close-fix): carry the player's proficient saves onto
                # the participant so resolve_saving_throw adds the bonus when an enemy imposes
                # a save (e.g. Frightened). Sourced from players.data (creation_rules.py:309).
                saving_throw_proficiencies=row.get("saving_throw_proficiencies", []),
                condition_immunities=traits.condition_immunities,
                save_advantages=traits.save_advantages,
                advantage_vs=traits.advantage_vs,
            )
        )
    for enemy in enemies:
        derived = enemy
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
                creature_id=derived["creature_id"],
                catalog_narration=derived["catalog_narration"],
                catalog_audio=derived["catalog_audio"],
                deferred_effects=derived["deferred_effects"],
                multiattack_sequence=derived.get("multiattack_sequence"),
                turn_start_damage=derived.get("turn_start_damage"),
                condition_immunities=derived["condition_immunities"],
                choir_reaction=derived.get("choir_reaction"),
                hollow=derived["hollow"],
                saving_throw_proficiencies=derived["saving_throw_proficiencies"],
                xp_value=derived.get("xp_value", 0),
                role=derived["role"],
                attack_mod=derived["attack_mod"],
                damage_mult=derived["damage_mult"],
                dc_mod=derived["dc_mod"],
                legendary_actions=derived["legendary_actions"],
                signature_ability=derived["signature_ability"],
                category=derived.get("category", ""),
                tier=derived["tier"],
                loot_table_id=derived.get("loot_table_id", ""),
                resistance_tags=derived.get("resistance_tags", []),
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

    return participants, spatial, initiative_entries, initiative_order, retained_choir
