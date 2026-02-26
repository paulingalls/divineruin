import os

DM_VOICE = os.getenv("INWORLD_VOICE_DM", "")
TORIN_VOICE = os.getenv("INWORLD_VOICE_TORIN", "")
YANNA_VOICE = os.getenv("INWORLD_VOICE_YANNA", "")
EMRIS_VOICE = os.getenv("INWORLD_VOICE_EMRIS", "")

VOICES: dict[str, dict[str, str | float]] = {
    "dm_narrator": {
        "voice": DM_VOICE,
        "description": "Warm, mid-range narrator",
        "speaking_rate": 1.0,
    },
    "GUILDMASTER_TORIN": {
        "voice": TORIN_VOICE,
        "description": "Deep, authoritative",
        "speaking_rate": 1.0,
    },
    "ELDER_YANNA": {
        "voice": YANNA_VOICE,
        "description": "Warm, measured elder",
        "speaking_rate": 1.0,
    },
    "SCHOLAR_EMRIS": {
        "voice": EMRIS_VOICE,
        "description": "Quick, precise scholar",
        "speaking_rate": 1.0,
    },
}

EMOTION_RATE: dict[str, float] = {
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


def get_voice_config(character: str, emotion: str = "neutral") -> dict[str, str | float]:
    entry = VOICES.get(character, VOICES["dm_narrator"])
    base_rate = float(entry.get("speaking_rate", 1.0))
    emotion_modifier = EMOTION_RATE.get(emotion.lower(), 1.0)
    return {
        "voice": entry["voice"],
        "speaking_rate": base_rate * emotion_modifier,
    }
