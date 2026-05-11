"""Event dispatch logic extracted from BackgroundProcess."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import event_types as E
from bg_speech import PendingSpeech, SpeechPriority
from god_whisper_data import get_god_profile, should_trigger_whisper
from sanitize import sanitize_for_prompt
from tool_support import _disposition_rank

if TYPE_CHECKING:
    from event_bus import GameEvent
    from session_data import SessionData

logger = logging.getLogger("divineruin.background")

REBUILD_EVENT_TYPES = {
    E.LOCATION_CHANGED,
    E.QUEST_UPDATED,
    E.DISPOSITION_CHANGED,
    E.COMBAT_STARTED,
    E.COMBAT_ENDED,
    E.HOLLOW_CORRUPTION_CHANGED,
    E.DIVINE_FAVOR_CHANGED,
}

CORRUPTION_COMPANION_SPEECH: dict[int, str] = {
    1: (
        "Kael tenses and looks around slowly. Have him make one quiet observation: "
        "something about the silence, the wrongness, how the air feels different. "
        "One sentence. Use [COMPANION_KAEL, uneasy] tag."
    ),
    2: (
        "Kael is visibly on edge. Have him react to the corruption — something about sounds "
        "coming from wrong directions, distances feeling off. Shorter sentence. More tense. "
        "Use [COMPANION_KAEL, nervous] tag."
    ),
    3: (
        "Kael is deeply unsettled. One short, urgent sentence. He doesn't elaborate — "
        "just names what he's feeling. Use [COMPANION_KAEL, urgent] tag."
    ),
}


def _queue(
    speech_queue: list[PendingSpeech],
    priority: SpeechPriority,
    instructions: str,
    stinger_sound: str | None = None,
) -> None:
    speech_queue.append(PendingSpeech(priority=priority, instructions=instructions, stinger_sound=stinger_sound))


def handle_events(
    events: list[GameEvent],
    sd: SessionData,
    speech_queue: list[PendingSpeech],
    rider_triggered: bool,
    scene_cache: dict[str, dict],
    quest_cache: list[dict],
) -> tuple[bool, bool]:
    """Dispatch game events to handlers. Returns (needs_rebuild, rider_triggered)."""
    needs_rebuild = False
    can_act = sd.companion_can_act
    companion = sd.companion

    for ev in events:
        if ev.event_type in REBUILD_EVENT_TYPES:
            needs_rebuild = True

        if ev.event_type == E.LOCATION_CHANGED:
            new_loc = ev.payload.get("new_location", "")

            if not rider_triggered and not sd.has_companion and new_loc == "accord_market_square" and not quest_cache:
                rider_triggered = True
                rider_scene = scene_cache.get("scene_rider_arrival")
                if rider_scene:
                    _queue(speech_queue, SpeechPriority.CRITICAL, rider_scene["instructions"])
                continue

            if can_act and companion:
                companion.emotional_state = "curious"
                _queue(
                    speech_queue,
                    SpeechPriority.IMPORTANT,
                    f"The player just arrived at a new location ({new_loc}). "
                    f"Kael looks around. Have him make one brief observation about "
                    f"the new surroundings. Use [COMPANION_KAEL, {companion.emotional_state}] tag.",
                )
            else:
                _queue(
                    speech_queue,
                    SpeechPriority.IMPORTANT,
                    f"The player just arrived at a new location ({new_loc}). Describe the atmosphere briefly.",
                )

        elif ev.event_type == E.QUEST_UPDATED:
            quest_name = sanitize_for_prompt(ev.payload.get("quest_name", "unknown quest"), max_len=100)
            objective = sanitize_for_prompt(ev.payload.get("objective", ""), max_len=200)
            if can_act and companion:
                companion.emotional_state = "focused"
                _queue(
                    speech_queue,
                    SpeechPriority.IMPORTANT,
                    f"The quest '{quest_name}' just progressed. New objective: {objective}. "
                    "Kael reacts to the quest progression. One sentence. "
                    "Use [COMPANION_KAEL, focused] tag.",
                )
            else:
                _queue(
                    speech_queue,
                    SpeechPriority.IMPORTANT,
                    f"The quest '{quest_name}' just progressed. New objective: {objective}.",
                )

        elif ev.event_type == E.COMBAT_ENDED:
            outcome = ev.payload.get("outcome", "victory")
            if outcome == "victory":
                if can_act and companion:
                    companion.emotional_state = "relieved"
                    _queue(
                        speech_queue,
                        SpeechPriority.IMPORTANT,
                        "Combat has ended in victory. Catch your breath. "
                        "Describe the aftermath — the quiet after violence. "
                        "Kael catches his breath and checks if you're okay. "
                        "One sentence. Use [COMPANION_KAEL, relieved] tag.",
                    )
                elif sd.has_companion and companion and not companion.is_conscious:
                    companion.is_conscious = True
                    companion.emotional_state = "weary"
                    _queue(
                        speech_queue,
                        SpeechPriority.IMPORTANT,
                        "Combat has ended in victory. Kael stirs, groaning. "
                        "First thing he does is check if you're okay. "
                        "Use [COMPANION_KAEL, weary] tag.",
                    )
                else:
                    _queue(
                        speech_queue,
                        SpeechPriority.IMPORTANT,
                        "Combat has ended in victory. Catch your breath. "
                        "Describe the aftermath — the quiet after violence.",
                    )
            elif outcome == "defeat":
                _queue(
                    speech_queue,
                    SpeechPriority.CRITICAL,
                    "The player has fallen in combat. This is a dramatic moment. Narrate the darkness closing in.",
                )

        elif ev.event_type == E.DISPOSITION_CHANGED:
            if can_act and companion:
                npc_name = sanitize_for_prompt(ev.payload.get("npc_name", "someone"), max_len=100)
                new_disp = ev.payload.get("new", "neutral")
                prev_disp = ev.payload.get("previous", "neutral")
                delta_positive = _disposition_rank(new_disp) > _disposition_rank(prev_disp)
                if delta_positive:
                    companion.emotional_state = "pleased"
                    reaction = "approves"
                else:
                    companion.emotional_state = "troubled"
                    reaction = "is uncomfortable"
                _queue(
                    speech_queue,
                    SpeechPriority.ROUTINE,
                    f"Kael {reaction} of the player's interaction with {npc_name}. "
                    f"One sentence. Use [COMPANION_KAEL, {companion.emotional_state}] tag.",
                )

        elif ev.event_type == E.HOLLOW_CORRUPTION_CHANGED:
            level = ev.payload.get("level", 0)
            if level > 0 and can_act and companion:
                speech = CORRUPTION_COMPANION_SPEECH.get(level)
                if speech:
                    _queue(speech_queue, SpeechPriority.IMPORTANT, speech)

        elif ev.event_type == E.WORLD_EVENT:
            event_id = ev.payload.get("event_id", "")
            if event_id.startswith("god_whisper"):
                queue_god_whisper(ev.payload, sd, speech_queue)

        elif ev.event_type == E.DIVINE_FAVOR_CHANGED:
            new_level = ev.payload.get("new_level", 0)
            last_whisper = ev.payload.get("last_whisper_level", 0)
            if should_trigger_whisper(new_level, last_whisper):
                queue_god_whisper(ev.payload, sd, speech_queue)

    return needs_rebuild, rider_triggered


def queue_god_whisper(
    payload: dict,
    sd: SessionData,
    speech_queue: list[PendingSpeech],
) -> None:
    """Build god-specific whisper instructions and queue as CRITICAL."""
    patron_id = payload.get("patron_id") or sd.patron_id
    profile = get_god_profile(patron_id)
    context = payload.get("reason", "")
    instructions = (
        "Something shifts. The air thickens. Sound stops — not fades, stops, as if the world "
        "has held its breath. For a heartbeat, everything is impossibly still.\n\n"
        "Then a presence. Not a voice yet, but a weight — ancient, immense. "
        "Narrate this atmospheric shift in your DM narrator voice.\n\n"
        f"Then the god speaks. Use [{profile.voice_character}, {profile.voice_emotion}] tag. "
        f"Speaking style: {profile.speaking_style}. "
        f"{profile.personality_prompt}\n\n"
        "Two sentences from the god. Short. Weighted. Ancient perspective. "
        f"{f'Context: {context}. ' if context else ''}"
        "Then silence returns like a wave breaking, and the world resumes. "
        "The companion does NOT react during this moment. After the silence breaks, "
        "Kael looks shaken but says nothing unless the player speaks first."
    )
    _queue(speech_queue, SpeechPriority.CRITICAL, instructions, stinger_sound=profile.stinger_sound)
