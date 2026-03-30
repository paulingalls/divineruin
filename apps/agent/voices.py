import logging
import os
from dataclasses import dataclass

logger = logging.getLogger("divineruin.voices")


@dataclass(frozen=True)
class VoiceConfig:
    voice: str
    speaking_rate: float
    inworld_markup: str = ""


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
# Keep offsets in [-0.2, +0.15] so all combos stay within Inworld's [0.5, 1.5].
VOICE_RATE_OFFSETS: dict[str, float] = {
    "GUILDMASTER_TORIN": 0.1,
    "COMPANION_KAEL": -0.05,
    "WOUNDED_RIDER": 0.1,
    "INNKEEPER_MAREN": 0.05,
    "FACTION_VALDRIS": -0.05,
    "GOD_KAELEN": -0.15,
    "GOD_SYRATH": -0.15,
    "GOD_VEYTHAR": -0.1,
    "GOD_MORTAEN": -0.2,
    "GOD_THYRA": -0.05,
    "GOD_AELORA": -0.05,
    "GOD_VALDRIS": -0.1,
    "GOD_NYTHERA": -0.05,
    "GOD_ORENTHEL": -0.1,
    "GOD_ZHAEL": -0.1,
}

# Emotion → speaking rate. Only affects PACE, not volume or vocal quality.
# Inworld API range is [0.5, 1.5]; keep base rates in [0.85, 1.15] so
# voice offsets don't push combos out of bounds.
EMOTION_RATES: dict[str, float] = {
    "calm": 0.9,
    "neutral": 0.95,
    "angry": 0.95,
    "threatening": 0.85,
    "nervous": 1.1,
    "excited": 1.1,
    "whispering": 1.0,  # whisper is volume/breath, not pace
    "secretive": 0.9,
    "sad": 0.9,
    "grieving": 0.85,
    "authoritative": 0.9,
    "stern": 0.9,
    "amused": 1.0,
    "weary": 0.85,
    "urgent": 1.15,
    "divine": 0.9,
}

EMOTIONS: list[str] = sorted(EMOTION_RATES.keys())

# Inworld TTS 1.5 audio markup tags, prepended to text per request.
# One emotion/delivery tag per API call; empty = use voice's default delivery.
INWORLD_MARKUPS: dict[str, str] = {
    "calm": "",
    "neutral": "",
    "angry": "[angry]",
    "threatening": "[angry]",
    "nervous": "[fearful]",
    "excited": "[happy]",
    "whispering": "[whispering]",
    "secretive": "[whispering]",
    "sad": "[sad]",
    "grieving": "[sad]",
    "authoritative": "",
    "stern": "",
    "amused": "[happy]",
    "weary": "[sad]",
    "urgent": "[surprised]",
    "divine": "",
}

assert set(INWORLD_MARKUPS.keys()) == set(EMOTION_RATES.keys()), (
    "INWORLD_MARKUPS and EMOTION_RATES must have the same emotion keys"
)

MIN_SPEAKING_RATE = 0.5
MAX_SPEAKING_RATE = 1.5


def apply_markup(text: str, markup: str) -> str:
    """Prepend an Inworld TTS audio markup tag to text if present."""
    if markup:
        return f"{markup} {text}"
    return text


def get_voice_config(character: str, emotion: str = "neutral") -> VoiceConfig:
    voice = VOICES.get(character, VOICES[DEFAULT_VOICE])
    if not voice:
        # Character-specific voice not configured; fall back to DM narrator
        voice = VOICES[DEFAULT_VOICE]
    if not voice:
        logger.warning(
            "No voice ID configured for %r or DM narrator (check INWORLD_VOICE_* env vars)",
            character,
        )
    rate = EMOTION_RATES.get(emotion.lower(), 1.0)
    rate += VOICE_RATE_OFFSETS.get(character, 0.0)
    # Inworld API requires speakingRate in [0.5, 1.5]
    rate = max(MIN_SPEAKING_RATE, min(MAX_SPEAKING_RATE, rate))
    markup = INWORLD_MARKUPS.get(emotion.lower(), "")
    return VoiceConfig(voice=voice, speaking_rate=rate, inworld_markup=markup)
