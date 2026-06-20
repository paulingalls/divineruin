"""Shared helpers for combat tool modules."""

import logging
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, cast

from livekit.agents.llm import ToolError

if TYPE_CHECKING:
    from spell_casting import CastResult

import check_resolution_attack
import combat_enhancers
import combat_resolution
import concentration_break
import conditions
import db_mutations
import db_mutations_inventory
import db_queries
import durability
import event_types as E
import spell_casting
from combat_events import EventSink, emit_or_publish
from dramatic import DramaticContext, evaluate_dramatic_context
from session_data import CombatParticipant, CombatState, SessionData
from tool_support import (
    SOUND_ATTACK_CRITICAL,
    SOUND_ATTACK_HIT,
    SOUND_ATTACK_MISS,
    SOUND_HEARTBEAT,
    SOUND_HOLLOW_RISE,
    SOUND_PLAYER_FALLEN,
)

logger = logging.getLogger("divineruin.tools")


@dataclass
class AbilityCastOutcome:
    """Side-channel carrying an in-loop ABILITY cast's ``CastResult`` back to the phase loop.

    At most one player ability resolves per phase (one declaration per participant), so a single
    slot suffices. The loop reads ``cast_result`` post-commit to seed the WRAP resonance, sync
    concentration in-memory, and flush the cast's deferred client events — all of which must happen
    after the phase tx commits (story-007). ``cast_result`` stays ``None`` when no ability resolved."""

    cast_result: "CastResult | None" = None


async def _resolve_ability_packet(
    session: SessionData,
    attacker: CombatParticipant,
    decl,
    *,
    cast_resolver,
    conn,
    player: dict | None,
    cast_outcome: AbilityCastOutcome,
) -> dict:
    """Resolve one in-combat ABILITY declaration through the shared cast logic (story-007).

    Player-gated: only the player carries a Focus pool + resonance track, so a non-player ABILITY
    (or one missing its action) is a *wasted* packet — enemy/companion casting is later M4.x work.
    Delegates to ``cast_resolver._resolve_cast`` with the cast's own RESONANCE_CHANGED suppressed
    (in combat the phase WRAP push is the single authoritative HUD update), stashing the returned
    CastResult on ``cast_outcome`` for the loop to commit. The returned summary carries the spell
    packet for the DM plus any narrated enhancer riders."""
    if attacker.type != "player":
        return {
            "actor_id": attacker.id,
            "resolved": False,
            "declaration_type": str(decl.type),
            "reason": "ability resolution not yet implemented for non-player actors",
        }
    if not decl.action:
        return {
            "actor_id": attacker.id,
            "resolved": False,
            "declaration_type": str(decl.type),
            "reason": "ability declaration missing an action",
        }

    result = await cast_resolver._resolve_cast(
        session,
        decl.action,
        conn=conn,
        player=player,
        suppress_resonance_changed=True,
    )
    cast_outcome.cast_result = result
    # Sync concentration into the session SSOT IN-LOOP (not post-commit): a lower-initiative enemy
    # attack later this same phase runs break_concentration_on_damage, which reads the in-memory
    # session.concentration to pick which spell to save for and to clear on a failed save. A
    # post-commit sync would leave it stale — the break would save against the OLD spell and, on a
    # break, write None to the DB (clearing the just-cast spell) while the post-commit sync forced
    # memory back to the new spell, diverging from the DB (story-007). _CombatScratchSnapshot
    # captures concentration, so this in-tx mutation is reverted if the phase rolls back.
    if result.concentration_spell_id is not spell_casting._UNCHANGED:
        session.concentration.spell_id = cast("str | None", result.concentration_spell_id)
    summary = {
        "actor_id": attacker.id,
        "resolved": True,
        "declaration_type": str(decl.type),
        "action": decl.action,
        "cast": result.packet,
    }
    return _attach_riders(summary, attacker, decl)


def _find_action(participant, action_name) -> dict | None:
    """Find the named action in a participant's action_pool (case-insensitive)."""
    if not action_name:
        return None
    wanted = str(action_name).lower()
    for a in participant.action_pool:
        if a.get("name", "").lower() == wanted:
            return a
    return None


def _attach_riders(summary: dict, attacker, decl) -> dict:
    """Add the actor's narrated enhancer riders to a packet summary, if any.

    Riders are descriptive (non-mechanical) — they carry no HP/AC effect, just the DM
    cue for an enhancer's expansion (Cunning Action's dash/disengage/hide, Hit and Run,
    Command Lesser, Quick Change). Omitted entirely when the actor has none, so a
    no-enhancer declaration keeps its flat summary (AC3: no phantom expansion)."""
    riders = combat_enhancers.declaration_riders(attacker.enhancers, decl)
    if riders:
        summary["riders"] = riders
    return summary


def _participant_summary(p: CombatParticipant) -> dict:
    """Serialize a participant for LLM response (no internal state like HP numbers)."""
    return {
        "id": p.id,
        "name": p.name,
        "type": p.type,
        "initiative": p.initiative,
        "hp_status": combat_resolution.hp_threshold_status(p.hp_current, p.hp_max),
        "ac": p.ac,
        "is_fallen": p.is_fallen,
    }


def _require_combat(session: SessionData) -> CombatState:
    """Return the combat state, or raise ToolError if not in combat (ADR 0002)."""
    if session.combat_state is None:
        raise ToolError("Not in combat.")
    return session.combat_state


async def _publish_sounds(session: SessionData, sounds: list[str], *, sink: EventSink | None = None) -> None:
    """Publish multiple sound events. When ``sink`` is active the events buffer until the phase
    transaction commits (rollback-safe); otherwise they publish immediately."""
    for sound in sounds:
        await emit_or_publish(
            sink,
            session.room,
            E.PLAY_SOUND,
            {"sound_name": sound},
            event_bus=session.event_bus,
        )


def _find_equipped(inventory: list[dict], item_type: str, name: str | None = None) -> dict | None:
    """Return the equipped inventory item of a given type (optionally matching a
    name), or None. Inventory dicts are get_player_inventory-shaped: catalog fields
    top-level, per-instance state under slot_info. Requires a durability_tier so the
    caller can damage it; an equipped item missing one is skipped (None) rather than
    blowing up the turn — durability is a side-effect, not worth failing over.
    Ambiguous matches log and take the first."""
    matches = [
        it
        for it in inventory
        if it.get("slot_info", {}).get("equipped")
        and it.get("type") == item_type
        and it.get("durability_tier")
        and (name is None or it.get("name", "").lower() == name.lower())
    ]
    if not matches:
        return None
    if len(matches) > 1:
        logger.warning("multiple equipped %s items; using first (%s)", item_type, matches[0].get("id"))
    return matches[0]


async def _accrue_durability(
    session: SessionData,
    player_id: str,
    item: dict,
    base_hits: int,
    *,
    is_hollow_zone: bool,
    mutations=db_mutations_inventory,
    conn=None,
    sink: EventSink | None = None,
) -> dict:
    """Apply base_hits durability damage to an equipped item, persist the new
    current_hits, and publish ITEM_DURABILITY_HIT. Hollow zones double the loss.

    A missing current_hits reads as full (max_hits for the tier) — never-damaged
    items start undamaged (decision durability-current-hits-lazy-default). When the
    item is already broken and the loss can't lower it further, the write and event
    are skipped. Returns {"broken", "penalty", "current_hits"}.
    """
    durability_tier = item["durability_tier"]
    current_hits = item.get("slot_info", {}).get("current_hits")
    if current_hits is None:
        current_hits = durability.max_hits(durability_tier)

    item_state = {"type": item["type"], "durability_tier": durability_tier, "current_hits": current_hits}
    updated = durability.apply_durability_damage(item_state, base_hits, is_hollow_zone=is_hollow_zone)
    condition = durability.check_item_condition(updated)
    new_hits = updated["current_hits"]

    if new_hits == current_hits and condition["broken"]:
        return {**condition, "current_hits": new_hits}

    await mutations.update_item_durability(player_id, item["id"], new_hits, conn=conn)
    await emit_or_publish(
        sink,
        session.room,
        E.ITEM_DURABILITY_HIT,
        {"item_id": item["id"], "item_type": item["type"], "current_hits": new_hits, **condition},
        event_bus=session.event_bus,
    )
    return {**condition, "current_hits": new_hits}


async def _resolve_attack_packet(
    session: SessionData,
    attacker,
    action: dict,
    target,
    *,
    target_ac_bonus: int = 0,
    shield_reaction: str | None = None,
    enemies_remaining: int | None = None,
    is_first_attack_of_combat: bool = False,
    mutations=db_mutations,
    queries=db_queries,
    resolver=check_resolution_attack,
    concentration_break_mod=concentration_break,
    conn=None,
    sink=None,
) -> dict:
    """Resolve ONE declared attack against CombatParticipant HP.

    Mutates ``target`` in place (hp_current, is_fallen), publishes the attack's
    DICE_ROLL, sounds, and any durability hits in strike order, and returns a
    response dict for the caller (a per-packet narration summary). It does NOT
    persist — the caller owns one ``save_combat_state`` per phase so the multi-packet
    phase loop persists exactly once. ``attacker``/``target`` are CombatParticipants;
    ``action`` is an entry from the attacker's action_pool (weapon-shaped).

    ``shield_reaction`` is a forward seam for the M4.x reaction-window feature
    (combat_phase's ``reactions_available``): when a future declaration spends a
    shield reaction it threads the shield name here to accrue shield durability. The
    live phase loop (``_resolve_one_packet``) does not yet declare reactions, so it
    is always ``None`` on the live path today; the accrual branch is exercised by
    test_combat_durability."""
    attacker_data = {
        "attributes": attacker.attributes,
        "level": attacker.level,
        # Attacker's active conditions (M4.3): resolve_attack folds Exhausted into the roll,
        # Prone/Blinded into disadvantage, and Enraged into +2 damage.
        "conditions": attacker.conditions,
    }

    # ``target_ac_bonus`` is the target's phase-scoped AC modifier (Defend's +2, M4.2);
    # the live caller passes state.ac_modifiers[target.id]. Defaults to 0 for direct callers.
    # The target's condition AC modifier (M4.3, e.g. Enraged -2 AC) makes them easier to hit.
    target_condition_ac = conditions.get_condition_effects(target.conditions).ac_modifier
    effective_ac = target.ac + target_ac_bonus + target_condition_ac
    attack_result = resolver.resolve_attack(
        attacker_data,
        action,
        effective_ac,
        target.hp_current,
    )

    # Dramatic-dice (M4.5, story-004): the resolver's intrinsic verdict (nat-20/nat-1/
    # killing-blow) is the floor. If it didn't fire, PROMOTE on the encounter-context
    # signals only the caller can see — the last enemy standing, or the opening strike.
    # The caller supplies these (combat_turn counts non-fallen enemies + tracks first
    # attack); never downgrade an already-dramatic intrinsic verdict.
    if not attack_result.dramatic:
        verdict = evaluate_dramatic_context(
            DramaticContext(
                roll_type="attack",
                enemies_remaining=enemies_remaining,
                is_first_attack_of_combat=is_first_attack_of_combat,
            )
        )
        if verdict.dramatic:
            attack_result = replace(attack_result, dramatic=True, context=verdict.context)

    # Capture pre-hit Fallen state: the instant-death verdict (below) is scoped to the
    # live -> 0 transition (spec game_mechanics_combat.md L350 + on_hp_zero pseudocode L554:
    # "a single source of damage REDUCES HP to 0"). A hit on a target already at 0 is the
    # distinct "damage while Fallen" mechanic (L369: auto death-save failures), not instant
    # death — without this guard overkill = damage - 0 = damage would wrongly flag is_dead.
    was_fallen = target.is_fallen

    # Update target HP
    target.hp_current = attack_result.target_hp_remaining

    # Determine sounds
    sounds: list[str] = []
    if attack_result.critical_success:
        sounds.append(SOUND_ATTACK_CRITICAL)
    elif attack_result.hit:
        sounds.append(SOUND_ATTACK_HIT)
    else:
        sounds.append(SOUND_ATTACK_MISS)

    # Check HP thresholds
    hp_status = combat_resolution.hp_threshold_status(target.hp_current, target.hp_max)
    rose_hollowed = False
    if target.hp_current <= 0:
        if not was_fallen and target.type == "player" and conditions.hollowed_stage(target.conditions) >= 2:
            # Temporary Hollowed rise (M4.4 story-008): a Stage-2+ Hollowed player at 0 HP does NOT
            # fall — their corpse rises as a hostile Temporary Hollowed combatant (HP=50% of max,
            # hits add 1d6 necrotic, immune to Charmed/Frightened/Poisoned) that blocks combat-end
            # until destroyed (combat_phase._wrap). Transform in place: flipping `type` makes the
            # engine's player-defeat gate go dormant (no player participant) and the echo block
            # victory, AND it deliberately suppresses the player-HP write + concentration-break +
            # armor-durability accrual below — the echo's HP is the monster's, not the player's.
            # The persisted Hollowed condition is left intact; trigger_character_death reads it at
            # the echo's destruction to mark hollow_killed and clear it.
            target.type = "temporary_hollowed"
            target.hp_current = max(1, target.hp_max // 2)
            target.conditions = conditions.apply_condition(target.conditions, "temporary_hollowed")
            hp_status = combat_resolution.hp_threshold_status(target.hp_current, target.hp_max)
            rose_hollowed = True
            sounds.append(SOUND_HOLLOW_RISE)
        else:
            target.is_fallen = True
            # Instant death (M4.4 story-002): overkill (excess damage past 0) >= max HP kills
            # outright — no Fallen grace, no death saves. is_dead is the stronger state; the pure
            # _wrap reads it to end combat without a death-save beat. This is the one site with both
            # attack_result + hp_max. Gated on `not was_fallen` so it fires only on the live -> 0
            # transition the spec scopes it to; a hit on an already-downed target is the separate
            # "damage while Fallen" failure mechanic.
            if not was_fallen and attack_result.overkill >= target.hp_max:
                target.is_dead = True
            sounds.append(SOUND_PLAYER_FALLEN)
            # Handle companion KO
            if target.type == "companion" and session.companion and target.id == session.companion.id:
                session.companion.is_conscious = False
                session.record_companion_memory(f"{target.name} was knocked unconscious in combat")
    elif hp_status in ("bloodied", "critical"):
        sounds.append(SOUND_HEARTBEAT)

    # Update DB if target is a player
    if target.type == "player":
        await mutations.update_player_hp(target.id, target.hp_current, conn=conn)

    # Combat damage is the canonical concentration-break trigger: a concentrating player who takes
    # damage rolls a CON save (DC scales with the damage); failing it — or being dropped to 0 HP
    # (incapacitated) — ends concentration. The helper no-ops when the player isn't concentrating
    # or the attack dealt no damage; its return (the broken spell id, or None) is narrated below.
    concentration_broken = None
    if target.type == "player":
        concentration_broken = await concentration_break_mod.break_concentration_on_damage(
            session, attack_result.damage, incapacitated=target.hp_current <= 0, conn=conn
        )

    # Publish events (buffered into ``sink`` during the phase tx; released post-commit)
    await emit_or_publish(
        sink,
        session.room,
        E.DICE_ROLL,
        {
            "roll_type": "attack",
            "attacker": attacker.name,
            "hit": attack_result.hit,
            "roll": attack_result.roll,
            "damage": attack_result.damage,
            "critical": attack_result.critical_success,
            "dramatic": attack_result.dramatic,
            "context": attack_result.context,
        },
        event_bus=session.event_bus,
    )
    await _publish_sounds(session, sounds, sink=sink)

    # Accrue durability on the player's equipped armor (1 hit per damage taken),
    # and on a shield when the player spends a shield reaction. Hollow zones double.
    # Runs after the attack's DICE_ROLL so ITEM_DURABILITY_HIT follows the strike.
    durability_results: dict = {}
    if target.type == "player" and attack_result.hit:
        inventory = await queries.get_player_inventory(target.id, conn=conn)
        is_hollow = combat_resolution.is_hollow_zone(session.corruption_level)
        armor = _find_equipped(inventory, "armor")
        if armor is not None:
            durability_results["armor"] = await _accrue_durability(
                session, target.id, armor, 1, is_hollow_zone=is_hollow, conn=conn, sink=sink
            )
        if shield_reaction:
            shield = _find_equipped(inventory, "shield")
            if shield is not None:
                durability_results["shield"] = await _accrue_durability(
                    session, target.id, shield, 1, is_hollow_zone=is_hollow, conn=conn, sink=sink
                )

    hit_miss = "hit" if attack_result.hit else "miss"
    session.record_event(f"{attacker.name} attacks {target.name}: {hit_miss}, {attack_result.damage} damage")

    response = {
        "attacker": attacker.name,
        "action": action.get("name", ""),
        "target": target.name,
        "hit": attack_result.hit,
        "roll": attack_result.roll,
        "attack_total": attack_result.attack_total,
        "target_ac": effective_ac,
        "damage": attack_result.damage,
        "damage_type": attack_result.damage_type,
        "critical": attack_result.critical_success,
        "target_hp_status": hp_status,
        "target_fallen": target.is_fallen,
        "narrative_hint": attack_result.narrative_hint,
        "durability": durability_results,
        "concentration_broken": concentration_broken,
        "dramatic": attack_result.dramatic,
        "context": attack_result.context,
        # Bonus-damage rider (M4.4 story-008): the necrotic bite a Temporary Hollowed attacker
        # adds, for the DM to voice. 0/None on a normal hit.
        "bonus_damage": attack_result.bonus_damage,
        "bonus_damage_type": attack_result.bonus_damage_type,
        # Set when this hit raised a Stage-2+ Hollowed target as a Temporary Hollowed echo
        # instead of felling them — the DM narrates the corpse rising.
        "target_rose_hollowed": rose_hollowed,
    }
    logger.info(
        "resolve_attack_packet result: %s → %s, %s, damage=%d, hp_status=%s",
        attacker.name,
        target.name,
        hit_miss,
        attack_result.damage,
        hp_status,
    )
    return response
