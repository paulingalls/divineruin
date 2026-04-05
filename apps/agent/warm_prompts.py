"""Dynamic prompt builders — warm layer, affect context, quest objectives."""

from __future__ import annotations

from typing import TYPE_CHECKING

from combat_resolution import hp_threshold_status
from region_types import REGION_CITY
from session_data import CombatState

if TYPE_CHECKING:
    from session_data import CompanionState


def format_affect_context(affect: dict) -> str:
    """Format an affect vector as a compact bracketed string for hot layer injection."""
    eng = affect.get("engagement", {})
    energy = affect.get("energy", {})
    style = affect.get("interaction_style", {})
    turn = affect.get("turn_number", 0)
    calibration = affect.get("calibration_confidence", "low")

    parts = [
        f"engagement: {eng.get('level', '?')}, trend: {eng.get('trend', '?')}",
    ]

    eng_signals = eng.get("signals", [])
    if eng_signals:
        parts.append(f"signals: {', '.join(eng_signals)}")

    rate = energy.get("speech_rate_wps")
    if rate is not None:
        rate_str = f"speech rate: {rate} wps"
        rate_vs = energy.get("rate_vs_baseline", "n/a")
        if rate_vs != "n/a":
            rate_str += f" ({rate_vs} vs baseline)"
        parts.append(rate_str)

    mode = style.get("mode", "?")
    parts.append(f"mode: {mode}")

    latency = affect.get("response_latency_ms", 0)
    if latency > 0:
        lat_str = f"response latency: {latency}ms"
        lat_vs = affect.get("latency_vs_baseline", "n/a")
        if lat_vs != "n/a":
            lat_str += f" ({lat_vs})"
        parts.append(lat_str)

    cal_note = ""
    if calibration == "low":
        cal_note = " (low confidence — still calibrating)"
    elif calibration == "medium":
        cal_note = " (medium confidence — calibrating)"

    return f"[Player Affect — turn {turn}{cal_note}: {'; '.join(parts)}]"


def quest_objective(quest: dict) -> str:
    """Extract the current objective string from a quest dict."""
    stages = quest.get("stages", [])
    idx = quest.get("current_stage", 0)
    if 0 <= idx < len(stages):
        return stages[idx].get("objective", "")
    return ""


CORRUPTION_GUIDANCE: dict[int, str] = {
    1: (
        "HOLLOW CORRUPTION — Stage 1\n"
        "Ambient sounds are sparser. Describe longer silences, emptiness. "
        "Pauses where there should be birdsong. The world is holding its breath."
    ),
    2: (
        "HOLLOW CORRUPTION — Stage 2\n"
        "Sounds come from wrong distances. Echo is unreliable. "
        "Footsteps sound twice — once underfoot, once from somewhere else. "
        "Distances feel compressed or stretched."
    ),
    3: (
        "HOLLOW CORRUPTION — Stage 3\n"
        "New sounds intrude — subsonic hum, metallic resonances, a pitch "
        "that doesn't belong to any instrument. Wrongness is pervasive. "
        "Brief moments where two versions of reality overlap."
    ),
}


async def build_warm_layer(
    location_id: str,
    player_id: str,
    world_time: str,
    combat_state: CombatState | None = None,
    companion: CompanionState | None = None,
    quests: list[dict] | None = None,
    corruption_level: int = 0,
    location: dict | None = None,
    npcs_raw: list[dict] | None = None,
    region_type: str = REGION_CITY,
    scene_cache: dict[str, dict] | None = None,
) -> str:
    import asyncio

    import db_queries
    from tools import _location_for_narration, _npc_summary, apply_time_conditions

    sections: list[str] = []

    # Use pre-fetched data when available, otherwise query
    if location is None or npcs_raw is None:
        if quests is not None:
            location, npcs_raw = await asyncio.gather(
                db_queries.get_location(location_id),
                db_queries.get_npcs_at_location(location_id),
            )
        else:
            location, npcs_raw, quests = await asyncio.gather(
                db_queries.get_location(location_id),
                db_queries.get_npcs_at_location(location_id),
                db_queries.get_active_player_quests(player_id),
            )

    # Current scene
    if location:
        location = apply_time_conditions(location, world_time)
        narr = _location_for_narration(location)
        sections.append(
            f"CURRENT SCENE — {narr.get('name', location_id)} ({world_time})\n"
            f"{narr.get('description', '')}\n"
            f"Atmosphere: {narr.get('atmosphere', '')}"
        )

        # Exits
        exits = narr.get("exits", {})
        if exits:
            exit_lines = []
            for direction, exit_data in exits.items():
                dest = exit_data.get("destination", "unknown")
                requires = exit_data.get("requires")
                line = f"- {direction} \u2192 {dest}"
                if requires:
                    line += f" (blocked: requires {requires})"
                exit_lines.append(line)
            sections.append("EXITS\n" + "\n".join(exit_lines))

    # Active NPCs at location (city only — wilderness/dungeon de-emphasize NPCs)
    if npcs_raw and region_type == REGION_CITY:
        npc_ids = [npc["id"] for npc in npcs_raw]
        dispositions = await db_queries.get_npc_dispositions(npc_ids, player_id)
        npc_lines = []
        for npc in npcs_raw:
            disposition = dispositions.get(npc["id"], npc.get("default_disposition", "neutral"))
            summary = _npc_summary(npc, disposition)
            npc_lines.append(f"- {summary['name']} ({summary['role']}) — disposition: {summary['disposition']}")
        sections.append("NPCS PRESENT\n" + "\n".join(npc_lines))

    # Active quests
    if quests:
        quest_lines = []
        for q in quests:
            objective = quest_objective(q)
            quest_lines.append(f"- {q['quest_name']}: {objective}")
        sections.append("ACTIVE QUESTS\n" + "\n".join(quest_lines))

    # Active scene (from quest play tree or location default)
    if scene_cache:
        from tools import get_active_scene_for_context

        active_scene = get_active_scene_for_context(scene_cache, quests or [], location)
        if active_scene:
            sections.append(f"ACTIVE SCENE — {active_scene['name']}\n{active_scene['instructions']}")

    # Companion state
    if companion is not None and companion.is_present:
        conscious_str = "yes" if companion.is_conscious else "no"
        companion_lines = [
            f"COMPANION — {companion.name}",
            f"Emotional state: {companion.emotional_state}",
            f"Relationship tier: {companion.relationship_tier}",
            f"Conscious: {conscious_str}",
        ]
        recent_memories = companion.session_memories[-5:]
        if recent_memories:
            companion_lines.append("Recent memories: " + "; ".join(recent_memories))
        sections.append("\n".join(companion_lines))

    # Hollow corruption
    if corruption_level > 0:
        guidance = CORRUPTION_GUIDANCE.get(corruption_level)
        if guidance:
            sections.append(guidance)

    # Active combat
    if combat_state is not None:
        combat_lines = [f"Round {combat_state.round_number}"]
        for pid in combat_state.initiative_order:
            p = combat_state.get_participant(pid)
            if p is not None:
                status = hp_threshold_status(p.hp_current, p.hp_max)
                fallen = " [FALLEN]" if p.is_fallen else ""
                combat_lines.append(f"- {p.name} ({p.type}) — {status}{fallen}")
        sections.append("ACTIVE COMBAT\n" + "\n".join(combat_lines))

    return "\n\n".join(sections)


def build_full_prompt(static_layer: str, warm_layer: str) -> str:
    parts = [static_layer]
    if warm_layer:
        parts.append(warm_layer)
    return "\n\n---\n\n".join(parts)
