import os
from dataclasses import dataclass


@dataclass(frozen=True)
class VoiceConfig:
    voice: str
    speaking_rate: float


VOICES: dict[str, str] = {
    "DM_NARRATOR": os.getenv("INWORLD_VOICE_DM", ""),
    "GUILDMASTER_TORIN": os.getenv("INWORLD_VOICE_TORIN", ""),
    "ELDER_YANNA": os.getenv("INWORLD_VOICE_YANNA", ""),
    "SCHOLAR_EMRIS": os.getenv("INWORLD_VOICE_EMRIS", ""),
}

DEFAULT_VOICE = "DM_NARRATOR"

EMOTION_RATES: dict[str, float] = {
    "calm": 1.0,
    "neutral": 1.0,
    "angry": 0.9,
    "threatening": 0.9,
    "nervous": 1.15,
    "excited": 1.2,
    "whispering": 0.8,
    "secretive": 0.8,
    "sad": 0.8,
    "grieving": 0.8,
    "authoritative": 0.9,
    "stern": 0.9,
    "amused": 1.05,
    "weary": 0.85,
    "urgent": 1.1,
}

EMOTIONS: list[str] = sorted(EMOTION_RATES.keys())


def get_voice_config(character: str, emotion: str = "neutral") -> VoiceConfig:
    voice = VOICES.get(character, VOICES[DEFAULT_VOICE])
    rate = EMOTION_RATES.get(emotion.lower(), 1.0)
    return VoiceConfig(voice=voice, speaking_rate=rate)
