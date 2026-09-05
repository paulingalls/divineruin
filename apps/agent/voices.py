import logging
import os
from dataclasses import dataclass

logger = logging.getLogger("divineruin.voices")


@dataclass(frozen=True)
class VoiceConfig:
    voice: str
    speaking_rate: float
    inworld_markup: str = ""


# The 19 content/role_archetypes.json ids. Duplicated here as a literal because VOICES is
# built from os.getenv at IMPORT time while the archetype catalog is DB-loaded at STARTUP —
# there is no import-time path between them. test_voices.py pins this tuple against the
# catalog so the two cannot drift.
_ROLE_ARCHETYPE_IDS: tuple[str, ...] = (
    "merchant_general_goods",
    "merchant_weapons_armor",
    "merchant_alchemist",
    "merchant_jeweler",
    "merchant_exotic",
    "merchant_traveling",
    "merchant_black_market",
    "blacksmith",
    "innkeeper",
    "healer_temple",
    "scholar_sage",
    "guard",
    "soldier_ashmark",
    "assassin_rogue",
    "mage",
    "priest",
    "fence",
    "stablemaster",
    "shipwright",
)

# Generated townsfolk speak in their ROLE's voice, not a per-NPC one: every guard in a
# settlement shares ROLE_GUARD. agent.validate_env FAILS STARTUP when one of these is unset,
# because an empty registered value silently resolves to DM_NARRATOR (get_voice_config below).
ROLE_VOICE_KEYS: tuple[str, ...] = tuple(f"ROLE_{r.upper()}" for r in _ROLE_ARCHETYPE_IDS)

# The 51 VOICES keys and the env var each is read from. The env var name is NOT the key
# (COMPANION_KAEL<->INWORLD_VOICE_KAEL, DM_NARRATOR<->INWORLD_VOICE_DM), so this mapping is
# the ONE producer of both — test_voices.py set-differences its values against .env.example,
# which an ast walk for INWORLD_VOICE_* literals cannot do: the 19 role names are built by
# the f-string below and are written nowhere.
VOICE_ENV_VARS: dict[str, str] = {
    "DM_NARRATOR": "INWORLD_VOICE_DM",
    "GUILDMASTER_TORIN": "INWORLD_VOICE_TORIN",
    "COMPANION_KAEL": "INWORLD_VOICE_KAEL",
    "COMPANION_LIRA": "INWORLD_VOICE_LIRA",
    "COMPANION_TAM": "INWORLD_VOICE_TAM",
    # Sable is non-verbal (DM narrates her sound_palette); registered with an empty default so
    # the "every companion voice_id is a VOICES key" invariant holds uniformly. Falls back to
    # DM_NARRATOR if ever voiced, which non-verbal narration avoids.
    "COMPANION_SABLE": "INWORLD_VOICE_SABLE",
    "ELDER_YANNA": "INWORLD_VOICE_YANNA",
    "SCHOLAR_EMRIS": "INWORLD_VOICE_EMRIS",
    "GRIMJAW_BLACKSMITH": "INWORLD_VOICE_GRIMJAW",
    "WOUNDED_RIDER": "INWORLD_VOICE_RIDER",
    "INNKEEPER_MAREN": "INWORLD_VOICE_MAREN",
    "FACTION_VALDRIS": "INWORLD_VOICE_VALDRIS",
    "TAVERN_BRYN": "INWORLD_VOICE_BRYN",
    "TEMPLE_SELENE": "INWORLD_VOICE_SELENE",
    "ALDRIC_HOLLOWED": "INWORLD_VOICE_ALDRIC",
    "SYRATH_NYX": "INWORLD_VOICE_NYX",
    "VEYTHAR_THERON": "INWORLD_VOICE_THERON",
    "AELORA_DARA": "INWORLD_VOICE_DARA",
    "DRATHIAN_HESSA": "INWORLD_VOICE_DRATHIAN",
    "KELDARAN_DORAN": "INWORLD_VOICE_KELDARAN",
    "THORNWARDEN_SENNA": "INWORLD_VOICE_THORNWARDEN",
    "TIDECALLER_MAREK": "INWORLD_VOICE_TIDECALLER",
    "GOD_KAELEN": "INWORLD_VOICE_GOD_KAELEN",
    "GOD_SYRATH": "INWORLD_VOICE_GOD_SYRATH",
    "GOD_VEYTHAR": "INWORLD_VOICE_GOD_VEYTHAR",
    "GOD_MORTAEN": "INWORLD_VOICE_GOD_MORTAEN",
    "GOD_THYRA": "INWORLD_VOICE_GOD_THYRA",
    "GOD_AELORA": "INWORLD_VOICE_GOD_AELORA",
    "GOD_VALDRIS": "INWORLD_VOICE_GOD_VALDRIS",
    "GOD_NYTHERA": "INWORLD_VOICE_GOD_NYTHERA",
    "GOD_ORENTHEL": "INWORLD_VOICE_GOD_ORENTHEL",
    "GOD_ZHAEL": "INWORLD_VOICE_GOD_ZHAEL",
    **{k: f"INWORLD_VOICE_{k}" for k in ROLE_VOICE_KEYS},
}

VOICES: dict[str, str] = {key: os.getenv(var, "") for key, var in VOICE_ENV_VARS.items()}

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
