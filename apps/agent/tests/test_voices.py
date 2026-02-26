from voices import get_voice_config, EMOTION_RATES, EMOTIONS, VoiceConfig


def test_default_narrator():
    cfg = get_voice_config("DM_NARRATOR")
    assert isinstance(cfg, VoiceConfig)
    assert cfg.speaking_rate == 1.0


def test_unknown_character_falls_back():
    cfg = get_voice_config("UNKNOWN_NPC")
    narrator = get_voice_config("DM_NARRATOR")
    assert cfg.voice == narrator.voice


def test_emotion_modifies_rate():
    cfg_angry = get_voice_config("GUILDMASTER_TORIN", "angry")
    cfg_excited = get_voice_config("GUILDMASTER_TORIN", "excited")
    assert cfg_angry.speaking_rate < 1.0
    assert cfg_excited.speaking_rate > 1.0


def test_unknown_emotion_defaults_to_1():
    cfg = get_voice_config("DM_NARRATOR", "nonexistent")
    assert cfg.speaking_rate == 1.0


def test_emotions_list_matches_rates_dict():
    assert set(EMOTIONS) == set(EMOTION_RATES.keys())
