"""Ownership and resource preflight before any phase packet writes."""

from livekit.agents.llm import ToolError

import abilities
import ability_persistence
import character_spells
import combat_ability_save
import combat_martial
import combat_voice_rules
import spell_knowledge
import spells
from combat_ability import (
    _gate_ability_condition,
    condition_ability,
)
from combat_ability_gate import (
    BLADE_FLURRY,
    CLEAVING_BLOW,
    CUNNING_ACTION,
    ELECTIVE_RIDER_ABILITIES,
    EXPLOIT_WEAKNESS,
    MULTI_TARGET_WEAPON_ABILITIES,
    SECOND_WIND,
    SHIELD_BASH,
    SINGLE_TARGET_WEAPON_ABILITIES,
    WAR_CRY,
    WHIRLWIND,
    declared_ability,
    war_cry_targets,
)
from combat_deescalation import (
    _gate_deescalation,
    _validate_argument_type,
)
from declarations import DeclarationType


async def _prevalidate_ability_focus(
    session, state, adv, *, conn, queries, cast_resolver, character_spells_mod=character_spells
) -> dict[str, dict]:
    """Pre-validate EVERY player ABILITY declaration's ownership, active variant and cost BEFORE the
    resolution loop (AC2), one per declaring member (M14 story-004).

    An unowned or unaffordable in-combat ability must fail loud (ToolError) with NO state writes — and crucially
    before any OTHER actor's HP/durability write, so a bad ability never rolls back a phase that has
    already resolved attacks. For each player-ability packet, fetch THAT actor's OWN for_update row
    (pid == packet.actor_id == player_id, since combat_init builds player participants with id=mid),
    locking each player once (deduped across a member's declarations), gate that declaration against
    its own row, and return {pid: row} for the loop to thread to each cast. Returns ``{}`` when no
    player ability was declared (the common all-attacks phase locks nothing). Non-player abilities are
    wasted downstream, so they are not gated here.

    The per-player locks are taken in initiative order within the phase tx (adv.packets is ordered),
    once per player — the deterministic ordering story-008's caster-vs-target locking builds on."""
    player_ability_packets = [
        (p.actor_id, p.declaration, actor)
        for p in adv.packets
        if (
            (p.declaration.type is DeclarationType.ABILITY and p.declaration.action)
            or combat_martial.attack_ability(p.declaration)
        )
        and (actor := state.get_participant(p.actor_id)) is not None
        and actor.type == "player"
    ]
    if not player_ability_packets:
        return {}
    players_by_id: dict[str, dict] = {}
    known_spell_ids_by_player: dict[str, frozenset[str]] = {}
    for actor_id, decl, actor in player_ability_packets:
        player = players_by_id.get(actor_id)
        if player is None:
            # Lock this member's row once (a member with two ability declarations reuses the lock).
            player = await queries.get_player(actor_id, conn=conn, for_update=True)
            if player is None:
                raise ToolError(f"Unknown player: {actor_id}")
            players_by_id[actor_id] = player
        try:
            combat_voice_rules.guard_declaration(state, actor, decl)
        except ValueError as e:
            raise ToolError(str(e)) from e
        action = decl.action if decl.type is DeclarationType.ABILITY else combat_martial.attack_ability(decl)
        assert action is not None
        is_deescalation = action.lower() == "de_escalate"
        resolved_ability = (
            (abilities.get_ability("diplomat_de_escalate"), None) if is_deescalation else declared_ability(action)
        )
        if resolved_ability is not None:
            ability, variant = resolved_ability
            owned_elective = (
                await ability_persistence.owns_elective(actor_id, ability.id, conn=conn)
                if ability.ability_type == "elective"
                else False
            )
            if (
                ability.id in (BLADE_FLURRY, *MULTI_TARGET_WEAPON_ABILITIES)
                and player.get("class") != ability.archetype_id
            ) or not abilities.owns_ability(
                player.get("class"), player["level"], ability, owns_elective=owned_elective
            ):
                raise ToolError(f"{actor.name} hasn't learned {ability.name}.")
            try:
                if ability.id not in MULTI_TARGET_WEAPON_ABILITIES:
                    combat_martial.require_targets(state, actor, decl, ability)
            except ValueError as e:
                raise ToolError(str(e)) from e
            if variant is not None:
                active_variant_id = await ability_persistence.get_active_variant(actor_id, ability.id, conn=conn)
                if active_variant_id != variant.id:
                    raise ToolError(f"{actor.name} does not have {variant.id} active for {ability.name}.")
        # Three non-spell-vs-spell ABILITY gates (pre-resolution, no writes): de_escalate (M4.6a)
        # has its own Focus+lockout gate; a non-spell condition ability (M4.8 story-005, e.g.
        # bard_inspire) gates its catalog Stamina/Focus; everything else is a spell-backed ability
        # gated against the spell catalog. _gate_spell would raise "Unknown spell" for the first two.
        if is_deescalation:
            _gate_deescalation(player, state)
            # Validate the Tier-3 argument category before resolution writes so a bad category
            # fails loud before ANY packet resolves — never rolling back a phase that already wrote
            # other actors' HP/Focus (the packet re-checks defensively for direct callers).
            _validate_argument_type(decl)
        elif resolved_ability is not None and resolved_ability[0].id in (
            SECOND_WIND,
            SHIELD_BASH,
            CUNNING_ACTION,
            EXPLOIT_WEAKNESS,
            *ELECTIVE_RIDER_ABILITIES,
            *SINGLE_TARGET_WEAPON_ABILITIES,
            *MULTI_TARGET_WEAPON_ABILITIES,
        ):
            ability, variant = resolved_ability
            if ability.id in ELECTIVE_RIDER_ABILITIES:
                variant = await combat_martial.active_rider_variant(actor_id, ability.id, conn=conn)
            if ability.id in (*SINGLE_TARGET_WEAPON_ABILITIES, *MULTI_TARGET_WEAPON_ABILITIES):
                try:
                    weapon = combat_martial.main_hand(player, ability.name)
                    if ability.id == CLEAVING_BLOW:
                        for target_id in combat_martial.cleave_targets(decl):
                            if reason := combat_martial.reach_refusal(state, actor, target_id, weapon):
                                raise ValueError(reason)
                    if ability.id == WHIRLWIND and not combat_martial.whirlwind_targets(state, actor, weapon):
                        raise ValueError("Whirlwind requires a standing foe within main-hand melee reach.")
                except ValueError as e:
                    raise ToolError(str(e)) from e
            _gate_ability_condition(player, ability, variant)
        elif resolved_ability is not None and resolved_ability[0].id == WAR_CRY:
            ability, variant = resolved_ability
            if not war_cry_targets(state):
                raise ToolError("War Cry requires a standing foe who can hear.")
            _gate_ability_condition(player, ability, variant)
        elif (cond_ability := condition_ability(resolved_ability)) is not None:
            ability, variant = cond_ability
            combat_ability_save.gate_hostile_target(state, decl, ability)
            _gate_ability_condition(player, ability, variant)
            # Multi-target cap (M4.8 story-016): reject an over-cap / malformed multi-target ability
            # (e.g. bard_mass_inspire) HERE, before resolution writes — reusing the SAME targeting
            # SSOT the spell branch uses (normalize_target_list accepts Spell | Ability).
            if decl.target_ids:
                try:
                    spells.normalize_target_list(ability, decl.target_id, decl.target_ids)
                except ValueError as e:
                    raise ToolError(str(e)) from e
        else:
            known_spell_ids = known_spell_ids_by_player.get(actor_id)
            if known_spell_ids is None:
                known_rows = await character_spells_mod.get_known(actor_id, conn=conn)
                known_spell_ids = spell_knowledge.castable_spell_ids(
                    player.get("class"), (row["spell_id"] for row in known_rows)
                )
                known_spell_ids_by_player[actor_id] = known_spell_ids
            spell = cast_resolver._gate_spell(player, action, known_spell_ids)
            import combat_spell_profile

            try:
                combat_spell_profile.validate_target(state, actor, decl, spell)
            except ValueError as e:
                raise ToolError(str(e)) from e
            if spell.applies_condition is not None:
                combat_ability_save.gate_hostile_condition_targets(state, decl, spell.applies_condition, spell.name)
            # Multi-target cap (M4.8 story-012): reject an over-cap / malformed multi-target spell
            # declaration HERE, before the resolution loop writes anything — reusing the targeting
            # SSOT. Spell-aware, so it belongs with the Focus gate, not in pure resolve_declaration.
            if decl.target_ids:
                try:
                    spells.normalize_target_list(spell, decl.target_id, decl.target_ids)
                except ValueError as e:
                    raise ToolError(str(e)) from e
    return players_by_id
