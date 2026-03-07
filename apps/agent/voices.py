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
    "GRIMJAW_BLACKSMITH": os.getenv("INWORLD_VOICE_GRIMJAW", ""),
    "WOUNDED_RIDER": os.getenv("INWORLD_VOICE_RIDER", ""),
    "INNKEEPER_MAREN": os.getenv("INWORLD_VOICE_MAREN", ""),
    "FACTION_VALDRIS": os.getenv("INWORLD_VOICE_VALDRIS", ""),
    "GOD_KAELEN": os.getenv("INWORLD_VOICE_GOD_KAELEN", ""),
    "GOD_SYRATH": os.getenv("INWORLD_VOICE_GOD_SYRATH", ""),
    "GOD_VEYTHAR": os.getenv("INWORLD_VOICE_GOD_VEYTHAR", ""),
    "GOD_MORTAEN": os.getenv("INWORLD_VOICE_GOD_MORTAEN", ""),
    "GOD_THYRA": os.getenv("INWORLD_VOICE_GOD_THYRA", ""),
    "GOD_AELORA": os.getenv("INWORLD_VOICE_GOD_AELORA", ""),
    "GOD_VALDRIS": os.getenv("INWORLD_VOICE_GOD_VALDRIS", ""),
    "GOD_NYTHERA": os.getenv("INWORLD_VOICE_GOD_NYTHERA", ""),
    "GOD_ORENTHEL": os.getenv("INWORLD_VOICE_GOD_ORENTHEL", ""),
    "GOD_ZHAEL": os.getenv("INWORLD_VOICE_GOD_ZHAEL", ""),
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
    "GOD_KAELEN": -0.35,
    "GOD_SYRATH": -0.40,
    "GOD_VEYTHAR": -0.30,
    "GOD_MORTAEN": -0.45,
    "GOD_THYRA": -0.10,
    "GOD_AELORA": -0.15,
    "GOD_VALDRIS": -0.25,
    "GOD_NYTHERA": -0.05,
    "GOD_ORENTHEL": -0.20,
    "GOD_ZHAEL": -0.30,
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
    "divine": 1.0,
}

EMOTIONS: list[str] = sorted(EMOTION_RATES.keys())


def get_voice_config(character: str, emotion: str = "neutral") -> VoiceConfig:
    voice = VOICES.get(character, VOICES[DEFAULT_VOICE])
    rate = EMOTION_RATES.get(emotion.lower(), 1.0)
    rate += VOICE_RATE_OFFSETS.get(character, 0.0)
    return VoiceConfig(voice=voice, speaking_rate=rate)
