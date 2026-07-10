"""Archetype ability activation tool for the DM agent (M2.2).

request_ability_activation validates a character's Stamina/Focus against an
ability's cost, deducts on success, rejects via ToolError when insufficient, and
returns the ability's narration_cue for the DM to voice.

Cost is a {stamina, focus, scaling} object (decision m22-cost-object-schema).
Variable/pool-cost abilities (Lay on Hands, Divine Smite) carry cost{0,0} with the
real cost in the free-text scaling field. The tool always surfaces scaling as
variable_cost so the DM tracks the pool/variable portion — a scaling-bearing
ability is NEVER reported as a plain free activation (resolves concern
7b34ebf86b57). Combat-window gating for reactions is deferred to Phase 4.
"""

import json
import logging

from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext

import abilities
import ability_persistence
import condition_produce
import conditions
import db
import db_mutations_conditions
import db_queries
import mentor_variants
import spells
from db_errors import db_tool
from resource_costs import gate_pool
from session_data import SessionData
from tool_support import _validate_id

logger = logging.getLogger("divineruin.tools")


@function_tool()
@db_tool
async def request_ability_activation(
    context: RunContext[SessionData],
    ability_id: str,
    target_id: str | None = None,
    target_ids: list[str] | None = None,
) -> str:
    """Activate one of the character's archetype abilities.
    Call when the player uses a named ability, technique, spell, or reaction.
    Provide the ability_id (e.g. 'warrior_devastating_strike'). Validates and
    deducts the Stamina/Focus cost, rejecting if the character lacks the resource.
    Returns the narration cue to voice; for pool/variable-cost abilities (e.g. Lay
    on Hands) the variable_cost field carries the rule for you to track.

    Pass target_id when the ability buffs ONE other entity (e.g. Inspire on an ally).
    Pass target_ids (a list) for a party-wide buff that names several allies
    (e.g. Mass Inspire) — not both. Omit both for a self-targeted ability."""
    return await _request_ability_activation_impl(context, ability_id, target_id=target_id, target_ids=target_ids)


async def _request_ability_activation_impl(
    context: RunContext[SessionData],
    ability_id: str,
    *,
    target_id: str | None = None,
    target_ids: list[str] | None = None,
    db_mod=db,
    queries_mod=db_queries,
    persistence_mod=ability_persistence,
    abilities_mod=abilities,
    variants_mod=mentor_variants,
    conditions_mod=conditions,
    conditions_mutations_mod=db_mutations_conditions,
    condition_produce_mod=condition_produce,
) -> str:
    context.disallow_interruptions()
    _validate_id(ability_id, "ability_id")
    if target_id is not None:
        _validate_id(target_id, "target_id")
    for tid in target_ids or []:
        _validate_id(tid, "target_id")
    session: SessionData = context.userdata
    player_id = session.player_id
    logger.info("request_ability_activation called: ability=%s player=%s", ability_id, player_id)

    try:
        ability = abilities_mod.get_ability(ability_id)
    except ValueError as e:
        raise ToolError(str(e)) from e

    # Multi-target cap (M4.8 story-017): normalize + validate a party-wide ability target list through
    # the SAME normalize_target_list SSOT the spell + in-combat-ability paths use (rejects both-args /
    # over-cap / empty / a single-target ability mass-targeted). BEFORE any resource write.
    if target_ids is not None:
        try:
            target_ids = spells.normalize_target_list(ability, target_id, target_ids)
        except ValueError as e:
            raise ToolError(str(e)) from e

    condition_applied: str | None = None  # the produced condition, surfaced on the response post-commit
    condition_targets: list[str] | None = None  # multi-target voiced allies (M4.8 story-017)

    # Deterministic cross-player lock order (M14 story-008, debt 361417d1bea5), via the shared
    # deadlock-safe helper (story-005): pre-lock the caster + any OOC condition-producing targets in
    # ONE ascending-player_id batch — an in-combat call, or a self / companion / no-target activation,
    # locks just the caster.
    produces_ooc = ability.applies_condition is not None and not session.in_combat
    async with db_mod.transaction() as conn:
        locked_rows, player = await condition_produce_mod.lock_ooc_caster_and_targets(
            produces_ooc=produces_ooc,
            player_id=player_id,
            target_id=target_id,
            target_ids=target_ids,
            party_member_ids=session.party.member_ids,
            queries_mod=queries_mod,
            conn=conn,
        )

        # Own-the-base gate (story-006): reject an ability the player hasn't learned
        # BEFORE any resource deduction. Core/reaction are always-known for the
        # archetype; an elective needs a character_abilities row (queried only then).
        owned_elective = (
            await persistence_mod.owns_elective(player_id, ability_id, conn=conn)
            if ability.ability_type == "elective"
            else False
        )
        if not abilities_mod.owns_ability(player.get("class"), ability, owns_elective=owned_elective):
            raise ToolError(f"You haven't learned {ability.name}.")

        # An unlocked-and-active mentor variant overrides the base technique wholesale
        # (cost/effect/narration — decision m9 override shape). get_variant validates the
        # variant belongs to this ability and fails loud on a mismatch.
        variant = None
        active_variant_id = await persistence_mod.get_active_variant(player_id, ability_id, conn=conn)
        if active_variant_id is not None:
            try:
                variant = variants_mod.get_variant(ability_id, active_variant_id)
            except ValueError as e:
                raise ToolError(str(e)) from e
        cost = variant.cost if variant is not None else ability.cost

        # Gate Stamina then Focus (fail-loud, pure); each returns the post-deduct
        # value or None when its cost is 0. One write below applies both.
        new_stamina = gate_pool(player, "stamina", cost.stamina, label=ability.name)
        new_focus = gate_pool(player, "focus", cost.focus, label=ability.name)
        if new_stamina is not None or new_focus is not None:
            await persistence_mod.update_player_resources(player_id, stamina=new_stamina, focus=new_focus, conn=conn)

        # Beneficial-condition PRODUCER (M4.8 story-005), out-of-combat half. An ability carrying
        # applies_condition lands it on the target's players.data SSOT — applied AFTER the resource
        # gate so a refused (unaffordable) activation produces nothing, and inside this tx so the
        # write commits atomically with the deduct. The OOC persist is gated on not session.in_combat,
        # mirroring the spell producer (_resolve_cast): in combat the participant is the SSOT and the
        # declare_phase ability-condition path owns the apply, so an in-combat call here must NOT write
        # to players.data. condition_applied is captured here and surfaced on the response AFTER the
        # block (the response dict is built post-commit). Self-target (no target_id) reuses the
        # for_update caster row; a non-player target (companion/NPC) has no players.data store, so it
        # narrates without a write rather than hard-erroring on the missing row. The persist only fires
        # when the condition actually LANDS (has_condition) — an immunity no-op writes nothing.
        # Mirrors story-004's spell producer (decision applies-condition-producer-contract).
        if ability.applies_condition is not None and not session.in_combat:
            # Route through the shared OOC producer (story-007), which lands on the multi-target list,
            # the single target_id, or the caster (self) — unifying the OOC ability path with the OOC
            # spell path. target_ids was already normalized/capped above.
            try:
                voiced = await condition_produce_mod.produce_ooc_condition(
                    ability.applies_condition,
                    ability_id,
                    target_id=None if target_ids else target_id,
                    target_ids=target_ids,
                    caster_row=player,
                    caster_id=player_id,
                    party_member_ids=session.party.member_ids,
                    companion_id=(session.companion.id if session.companion and session.companion.is_present else None),
                    queries_mod=queries_mod,
                    conditions_mod=conditions_mod,
                    conditions_mutations_mod=conditions_mutations_mod,
                    locked_rows=locked_rows,
                    conn=conn,
                )
            except ValueError as e:
                raise ToolError(str(e)) from e
            if voiced:
                condition_applied = ability.applies_condition
                # Surface the per-ally voiced set only on the multi-target path (audio-first
                # attribution), mirroring the spell producer; single/self keep just condition_applied.
                if target_ids:
                    condition_targets = voiced

    response = {
        "narration_cue": variant.narration_cue if variant is not None else ability.narration_cue,
        "deducted": {"stamina": cost.stamina, "focus": cost.focus},
        "variable_cost": cost.scaling,
    }
    # On the override path, surface the variant's effect + cultural attribution so the DM
    # voices the variant (not the base) and attributes the technique to its culture (AC4).
    if variant is not None:
        response["effect"] = variant.effect
        response["cultural_attribution"] = variant.cultural_attribution
    # Producer narration signal (M4.8 story-005) — set only when the condition actually landed
    # (or a non-player narrate-only target); the apply/persist happened inside the tx above.
    if condition_applied is not None:
        response["condition_applied"] = condition_applied
    if condition_targets is not None:
        response["condition_targets"] = condition_targets
    return json.dumps(response)
