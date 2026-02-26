from voices import get_voice_config, EMOTION_RATE


def test_default_narrator():
    cfg = get_voice_config("dm_narrator")
    assert "voice" in cfg
    assert cfg["speaking_rate"] == 1.0


def test_unknown_character_falls_back():
    cfg = get_voice_config("UNKNOWN_NPC")
    narrator = get_voice_config("dm_narrator")
    assert cfg["voice"] == narrator["voice"]


def test_emotion_modifies_rate():
    cfg_angry = get_voice_config("GUILDMASTER_TORIN", "angry")
    cfg_excited = get_voice_config("GUILDMASTER_TORIN", "excited")
    assert cfg_angry["speaking_rate"] < 1.0
    assert cfg_excited["speaking_rate"] > 1.0


def test_all_emotions_have_rates():
    for emotion in ["calm", "angry", "nervous", "sad", "excited", "whispering", "authoritative", "stern", "amused", "weary", "urgent"]:
        assert emotion in EMOTION_RATE
