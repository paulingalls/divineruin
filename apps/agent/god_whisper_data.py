"""God whisper personality data, profiles, and favor thresholds.

Profiles sourced from `content/gods.json` (`whisper_profile` block per patron)
per ADR 0001. No IO, no async beyond a one-shot file read at module import.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

_GODS_JSON_PATH = Path(__file__).resolve().parents[2] / "content" / "gods.json"


@dataclass(frozen=True)
class GodWhisperProfile:
    deity_id: str
    display_name: str
    voice_character: str
    voice_emotion: str
    speaking_style: str
    stinger_sound: str
    personality_prompt: str


FAVOR_WHISPER_THRESHOLD = 25
FAVOR_WHISPER_COOLDOWN = 25


def _load_profiles() -> dict[str, GodWhisperProfile]:
    entries = json.loads(_GODS_JSON_PATH.read_text())
    return {
        entry["god_id"]: GodWhisperProfile(
            deity_id=entry["god_id"],
            display_name=entry["name"],
            voice_character=entry["whisper_profile"]["voice_character"],
            voice_emotion=entry["whisper_profile"]["voice_emotion"],
            speaking_style=entry["whisper_profile"]["speaking_style"],
            stinger_sound=entry["whisper_profile"]["stinger_sound"],
            personality_prompt=entry["whisper_profile"]["personality_prompt"],
        )
        for entry in entries
    }


GOD_WHISPER_PROFILES: dict[str, GodWhisperProfile] = _load_profiles()

_DEFAULT_PROFILE = GodWhisperProfile(
    deity_id="unknown",
    display_name="Unknown Presence",
    voice_character="DM_NARRATOR",
    voice_emotion="divine",
    speaking_style="ancient, vast, weary",
    stinger_sound="god_whisper_stinger",
    personality_prompt=(
        "You are an ancient, unknowable presence. Speak with vast, weary omniscience. Two sentences maximum."
    ),
)


def get_god_profile(deity_id: str) -> GodWhisperProfile:
    """Return the whisper profile for a deity, or a default for unknown/none."""
    return GOD_WHISPER_PROFILES.get(deity_id, _DEFAULT_PROFILE)


def should_trigger_whisper(new_level: int, last_whisper_level: int) -> bool:
    """Check if favor level crossed a whisper threshold."""
    if new_level < FAVOR_WHISPER_THRESHOLD:
        return False
    return new_level - last_whisper_level >= FAVOR_WHISPER_COOLDOWN
