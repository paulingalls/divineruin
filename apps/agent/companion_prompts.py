from __future__ import annotations

from typing import TYPE_CHECKING

from companion_profiles import get_companion_profile, progression_gains_up_to

if TYPE_CHECKING:
    from session_data import CompanionState


def _non_verbal_note(name: str) -> str:
    """The one phrasing of the non-verbal marker.

    build_companion_cue writes it and is_companion_cue reads it back off a queued
    instruction, so a reworded copy on either side would silently stop matching.
    """
    return f"{name} is non-verbal."


def build_companion_prompt(companion_id: str, player_level: int) -> str:
    profile = get_companion_profile(companion_id)
    personality = "\n".join(f"- {trait}" for trait in profile.personality)
    mannerisms = "\n".join(f"- {mannerism}" for mannerism in profile.mannerisms)
    gains = progression_gains_up_to(profile, player_level)
    progression_lines = "\n".join(
        f"- Level {milestone.level}: {milestone.gains}"
        + (" — DM: once per session; you track it" if milestone.level == 20 else "")
        for milestone in gains
    )
    # Below the first gain (L3 for Tam, L5 for the rest) this section is EMPTY, and a labelled
    # section with nothing under it reads to the model as "this companion has no progression".
    # Every character starts at level 1, so that is the common case, not an edge.
    progression_section = (
        f"\n\nProgression gains unlocked at player level {player_level}:\n{progression_lines}" if gains else ""
    )

    if profile.non_verbal:
        voice_instruction = f"""\
{_non_verbal_note(profile.name)} Narrate {profile.name}'s vocalizations, posture, and movement in the DM voice.
Registered voice ID: {profile.voice_id}. Never use it as a dialogue tag."""
    else:
        voice_instruction = f"""\
Always use the tag format: [{profile.voice_id}, emotion]: \"Their dialogue here.\"
Never speak as {profile.name} without the tag. Never narrate {profile.name}'s dialogue in the DM voice.

Speech rules:
- One to two sentences max per interjection. {profile.name} does not monologue.
- Comment on the environment, react to events, and fill silence naturally.
- In combat, use urgent, clipped callouts of one sentence."""

    return f"""\

## Companion — {profile.name}

{profile.name} is the player's traveling companion. {profile.name} is NOT you, but a separate character
with their own voice and personality.

Tool id: {profile.id} — the only companion id begin_activity with kind="companion_errand" accepts;
any other id is refused. Never say it aloud.

{voice_instruction}

Speech style: {profile.speech_style}

Personality:
{personality}

Mannerisms:
{mannerisms}{progression_section}

When unconscious, generate no companion dialogue or intentional vocalization. The silence is the design.

Relationship tiers:
- Tier 1: helpful and reliable, but guarded on personal topics.
- Tier 2+: warmth and personal history emerge more freely.\
"""


def build_companion_cue(companion: CompanionState, staging: str, emotion: str) -> str:
    profile = get_companion_profile(companion.id)
    if profile.non_verbal:
        return (
            f"{profile.name} {staging} {_non_verbal_note(profile.name)} "
            "Narrate the reaction through vocalization, posture, or movement in the DM voice; "
            "do not generate dialogue or use a companion dialogue tag."
        )
    return f"{profile.name} {staging} One sentence. Use [{profile.voice_id}, {emotion}] tag."


def companion_voice_directive(companion: CompanionState) -> str:
    """How to voice this companion — the registered tag, or the non-verbal narration rule.

    Named producer for the tag id (constraint 6): CombatAgent gets COMBAT_SYSTEM_PROMPT,
    not the companion section, so the combat-entry context is the only channel that can
    tell it which of the four tags to use.
    """
    profile = get_companion_profile(companion.id)
    if profile.non_verbal:
        return (
            f"{_non_verbal_note(profile.name)} Narrate {profile.name}'s vocalizations, posture "
            f"and movement in the DM voice; never use a dialogue tag for {profile.name}."
        )
    return f'Voice {profile.name} with the [{profile.voice_id}, emotion]: "..." dialogue tag.'


def is_companion_cue(instructions: str, companion: CompanionState) -> bool:
    profile = get_companion_profile(companion.id)
    if profile.non_verbal:
        return _non_verbal_note(profile.name) in instructions
    return f"[{profile.voice_id}," in instructions
