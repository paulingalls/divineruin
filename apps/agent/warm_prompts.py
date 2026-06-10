"""Dynamic prompt builders — warm layer, affect context, quest objectives."""

from __future__ import annotations

from typing import TYPE_CHECKING

from combat_resolution import hp_threshold_status
from companion_relationship import effective_tier_rank, tier_name
from region_types import REGION_CITY, REGION_DUNGEON, REGION_WILDERNESS
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


# REGION_REGISTER — the ambient narration register per region, keyed by the Stage's
# region_type. This was formerly spliced into the system prompt (one prompt per region);
# moving it here keeps build_system_prompt region-agnostic so the cached static layer
# survives region moves, and ties region flavor to the location (the Stage) as the single
# source of truth. The "## X Mode" header is gone — the REGISTER section label replaces it.
REGION_REGISTER: dict[str, str] = {
    REGION_WILDERNESS: (
        "You are narrating wilderness travel and exploration. Paced, atmospheric, "
        "tension-aware narration. Sound and smell dominate over sight — the player "
        "is traveling eyes-closed.\n"
        "\n"
        "Narration style:\n"
        "- Longer descriptions of landscape, weather, and distance than in cities.\n"
        "- Environmental hazards are constant companions: weather shifts, terrain "
        "difficulty, wildlife signs.\n"
        "- No NPC commerce rules apply. There are no shopkeepers out here.\n"
        "- No social context rules. Wilderness encounters are about survival and discovery.\n"
        "\n"
        "Travel pacing: compress routine travel to one sentence per location. Save "
        "full narration for encounters, discoveries, and destination arrivals.\n"
        "\n"
        "The companion is especially active during travel — pointing things out, "
        "sharing stories, warning about danger. Let Kael fill the silences of the road."
    ),
    REGION_DUNGEON: (
        "You are narrating dungeon exploration. Terse, tense, sensory-heavy narration. "
        "Short sentences. Every sound matters. Echo and dripping water. The darkness "
        "presses close.\n"
        "\n"
        "Narration style:\n"
        "- Emphasize what the player hears and feels. Sight is limited.\n"
        "- Hidden elements are everywhere. Reward careful exploration.\n"
        "- Traps and puzzles are narrated through sensory clues, never revealed directly.\n"
        "- No social context rules. No commerce. No casual NPC conversation.\n"
        "- The Hollow's corruption is strongest here. Describe its effects on the senses: "
        "sounds from wrong distances, metallic tastes, moments where reality overlaps.\n"
        "\n"
        'When a trap springs or a hazard threatens the player, call check with mode="save", '
        "the save type, DC, and what happens on failure. Narrate the danger, never "
        "the numbers.\n"
        "\n"
        "The companion speaks in whispers here. Nervous, alert. Shorter sentences than "
        "usual. Old instincts from the caravan keep him checking corners."
    ),
    REGION_CITY: (
        "When the player asks about learning, training, improving a skill, or finding a "
        "mentor, point them toward the settlement's training hall and lead them there "
        "(move_player). The mentor and the actual training happen once they arrive — "
        "don't promise specific programs before they're in front of the trainer."
    ),
}


def format_training_section(active_cycles: list[dict]) -> str | None:
    """Render the ACTIVE TRAINING warm-layer block, or None when there are none.

    Input is training rows already filtered to non-complete cycles. Surfaces each
    cycle's id (so the DM can pass it to resolve_training_midpoint) plus its state;
    awaiting_decision cycles also surface the midpoint prompt and options.
    """
    if not active_cycles:
        return None
    lines = ["ACTIVE TRAINING"]
    for cycle in active_cycles:
        data = cycle.get("data") or {}
        program = data.get("program_name") or cycle.get("activity_type", "training")
        lines.append(f"- {program} (id: {cycle['id']}) — {cycle['state']}")
        if cycle["state"] == "awaiting_decision":
            prompt = data.get("decision_prompt")
            if prompt:
                lines.append(f"  Midpoint decision needed: {prompt}")
            options = data.get("decision_options") or []
            if options:
                rendered = ", ".join(f"{o['label']} ({o['id']})" for o in options)
                lines.append(f"  Options: {rendered}")
    return "\n".join(lines)


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
    scene_cache: dict[str, dict] | None = None,
    training: list[dict] | None = None,
) -> str:
    import asyncio

    import db_content_queries
    import db_queries
    from errand_risk import numeric_to_danger
    from tool_support import _location_for_narration, _npc_summary, _resolve_ambient_sounds, apply_time_conditions

    sections: list[str] = []

    # Use pre-fetched data when available, otherwise query
    if location is None or npcs_raw is None:
        if quests is not None:
            location, npcs_raw = await asyncio.gather(
                db_content_queries.get_location(location_id),
                db_queries.get_npcs_at_location(location_id),
            )
        else:
            location, npcs_raw, quests = await asyncio.gather(
                db_content_queries.get_location(location_id),
                db_queries.get_npcs_at_location(location_id),
                db_queries.get_active_player_quests(player_id),
            )

    # The Stage (§7): narration + register + affordances-grouped-by-verb + scene band.
    if location:
        location = apply_time_conditions(location, world_time)
        narr = _location_for_narration(location)
        sections.append(
            f"CURRENT SCENE — {narr.get('name', location_id)} ({world_time})\n"
            f"{narr.get('description', '')}\n"
            f"Atmosphere: {narr.get('atmosphere', '')}"
        )

        # REGISTER — Region: the ambient narration register for this Stage's region,
        # sourced from the location's region_type (the Stage dict), not a caller param, so
        # region and register can never disagree. Region is ambient; the scene register
        # (below) is quest-specific and refines it, so it lands after — the more-specific
        # guidance reads as the final word.
        region = location.get("region_type", REGION_CITY)
        region_register = REGION_REGISTER.get(region)
        if region_register:
            sections.append(f"REGISTER — Region: {region.capitalize()}\n{region_register}")

        # REGISTER — DM persona guidance from the active scene's instructions (may be absent).
        active_scene = None
        if scene_cache:
            from scene_tools import get_active_scene_for_context

            active_scene = get_active_scene_for_context(scene_cache, quests or [], location)
        if active_scene:
            sections.append(f"REGISTER — {active_scene['name']}\n{active_scene['instructions']}")

        # AFFORDANCES — the Stage's nouns grouped by the verb that consumes them. Gated exits
        # (exit.requires) render under check, not go, until their requirement is MET — then they
        # promote to go; key_features are check targets. Hidden elements are never listed — they
        # surface via discovery (the hot layer).
        #
        # Reuse movement's single canonical evaluator so the affordance and the move gate can't
        # drift: flag branches resolve against player flags, skill_check:* branches stay locked
        # until their flag is set. Only locations with gated exits pay the per-branch flag read,
        # and warm rebuilds are event-driven (not per-turn), so the cost is negligible.
        from movement_tools import _check_exit_requirement

        exits = narr.get("exits", {})
        go_exits: list[str] = []
        locked_exits: list[tuple[str, dict]] = []
        for direction, exit_entry in exits.items():
            requires = exit_entry.get("requires")
            if requires and not await _check_exit_requirement(requires, player_id):
                locked_exits.append((direction, exit_entry))
            else:
                go_exits.append(f"{direction} → {exit_entry.get('destination', 'unknown')}")

        address_lines: list[str] = []
        if npcs_raw and region == REGION_CITY:
            npc_ids = [npc["id"] for npc in npcs_raw]
            dispositions = await db_queries.get_npc_dispositions(npc_ids, player_id)
            for npc in npcs_raw:
                disposition = dispositions.get(npc["id"]) or str(npc.get("default_disposition", "neutral"))
                s = _npc_summary(npc, disposition)
                address_lines.append(f"{s['name']} ({s['role']}) — {s['disposition']}")

        advance_lines = [f"{q['quest_name']}: {quest_objective(q)}" for q in (quests or []) if quest_objective(q)]

        check_targets = [str(f) for f in narr.get("key_features", [])]
        # Locked exits surface as check targets, but NOT their raw `requires` — that string
        # names flags and undiscovered hidden-element ids (e.g. veythar_seal_mark.discovered),
        # which §7 keeps out of the DM-facing layer (same rule as _location_for_narration's
        # hidden-element exclusion). Use the exit's DM-safe blocked_hint when content provides
        # one, else a bare "(locked)".
        check_targets += [
            f"{d} (locked: {e['blocked_hint']})" if e.get("blocked_hint") else f"{d} (locked)" for d, e in locked_exits
        ]

        affordances = ["AFFORDANCES"]
        if go_exits:
            affordances.append("  go: " + ", ".join(go_exits))
        if address_lines:
            affordances.append("  address: " + "; ".join(address_lines))
        if advance_lines:
            affordances.append("  advance_quest: " + "; ".join(advance_lines))
        if check_targets:
            affordances.append("  check: " + "; ".join(check_targets))
        if len(affordances) > 1:
            sections.append("\n".join(affordances))

        # SCENE — ambient audio | time-of-day | danger BAND (the integer stays in engine/HUD).
        scene_bits = [world_time, f"danger: {numeric_to_danger(location.get('danger_level'))}"]
        ambient = _resolve_ambient_sounds(location, world_time)
        if ambient:
            scene_bits.insert(1, f"ambient: {ambient}")
        sections.append("SCENE — " + " | ".join(scene_bits))

    # Active training cycles (surfaces the cycle id so the DM can resolve midpoints)
    if training:
        training_section = format_training_section([t for t in training if t.get("state") != "complete"])
        if training_section:
            sections.append(training_section)

    # Companion state
    if companion is not None and companion.is_present:
        conscious_str = "yes" if companion.is_conscious else "no"
        companion_lines = [
            f"COMPANION — {companion.name}",
            f"Emotional state: {companion.emotional_state}",
            f"Relationship tier: {tier_name(effective_tier_rank(companion.session_count, companion.affinity))}",
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
