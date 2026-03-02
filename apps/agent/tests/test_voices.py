from voices import get_voice_config, EMOTION_RATES, EMOTIONS, VOICE_RATE_OFFSETS, VoiceConfig


def test_default_narrator():
    cfg = get_voice_config("DM_NARRATOR")
    assert isinstance(cfg, VoiceConfig)
    assert cfg.speaking_rate == EMOTION_RATES["neutral"]


def test_unknown_character_falls_back():
    cfg = get_voice_config("UNKNOWN_NPC")
    narrator = get_voice_config("DM_NARRATOR")
    assert cfg.voice == narrator.voice


def test_emotion_modifies_rate():
    cfg_angry = get_voice_config("GUILDMASTER_TORIN", "angry")
    cfg_excited = get_voice_config("GUILDMASTER_TORIN", "excited")
    assert cfg_angry.speaking_rate < cfg_excited.speaking_rate


def test_unknown_emotion_defaults_to_1():
    cfg = get_voice_config("DM_NARRATOR", "nonexistent")
    assert cfg.speaking_rate == 1.0


def test_emotions_list_matches_rates_dict():
    assert set(EMOTIONS) == set(EMOTION_RATES.keys())


def test_voice_rate_offset_applied():
    dm = get_voice_config("DM_NARRATOR", "neutral")
    torin = get_voice_config("GUILDMASTER_TORIN", "neutral")
    assert torin.speaking_rate == EMOTION_RATES["neutral"] + VOICE_RATE_OFFSETS["GUILDMASTER_TORIN"]
    assert torin.speaking_rate > dm.speaking_rate


def test_no_offset_for_unregistered_voice():
    cfg = get_voice_config("ELDER_YANNA", "neutral")
    assert cfg.speaking_rate == EMOTION_RATES["neutral"]
