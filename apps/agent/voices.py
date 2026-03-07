import os
from dataclasses import dataclass


@dataclass(frozen=True)
class VoiceConfig:
    voice: str
    speaking_rate: float


VOICES: dict[str, str] = {
    "DM_NARRATOR": os.getenv("INWORLD_VOICE_DM", ""),
    "GUILDMASTER_TORIN": os.getenv("INWORLD_VOICE_TORIN", ""),
    "COMPANION_KAEL": os.getenv("INWORLD_VOICE_KAEL", ""),
    "ELDER_YANNA": os.getenv("INWORLD_VOICE_YANNA", ""),
    "SCHOLAR_EMRIS": os.getenv("INWORLD_VOICE_EMRIS", ""),
    "WOUNDED_RIDER": os.getenv("INWORLD_VOICE_RIDER", ""),
    "INNKEEPER_MAREN": os.getenv("INWORLD_VOICE_MAREN", ""),
    "FACTION_VALDRIS": os.getenv("INWORLD_VOICE_VALDRIS", ""),
}

DEFAULT_VOICE = "DM_NARRATOR"

# Per-voice rate offset added to the emotion rate.
# Compensates for inherent speed differences between Inworld voices.
# Positive = faster, negative = slower. DM is the baseline.
VOICE_RATE_OFFSETS: dict[str, float] = {
    "GUILDMASTER_TORIN": 0.15,
    "COMPANION_KAEL": -0.05,
    "WOUNDED_RIDER": 0.20,
    "INNKEEPER_MAREN": 0.05,
    "FACTION_VALDRIS": -0.10,
}

EMOTION_RATES: dict[str, float] = {
    "calm": 0.8,
    "neutral": 0.8,
    "angry": 0.75,
    "threatening": 0.7,
    "nervous": 0.95,
    "excited": 1.0,
    "whispering": 0.65,
    "secretive": 0.65,
    "sad": 0.65,
    "grieving": 0.65,
    "authoritative": 0.75,
    "stern": 0.75,
    "amused": 0.85,
    "weary": 0.7,
    "urgent": 0.9,
}

EMOTIONS: list[str] = sorted(EMOTION_RATES.keys())


def get_voice_config(character: str, emotion: str = "neutral") -> VoiceConfig:
    voice = VOICES.get(character, VOICES[DEFAULT_VOICE])
    rate = EMOTION_RATES.get(emotion.lower(), 1.0)
    rate += VOICE_RATE_OFFSETS.get(character, 0.0)
    return VoiceConfig(voice=voice, speaking_rate=rate)
