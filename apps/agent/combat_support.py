"""Shared helpers for combat tool modules."""

import logging

from livekit.agents.llm import ToolError

import combat_enhancers
import combat_resolution
import db_mutations_inventory
import durability
import event_types as E
from combat_events import EventSink, emit_or_publish
from session_data import CombatParticipant, CombatState, SessionData

logger = logging.getLogger("divineruin.tools")


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
