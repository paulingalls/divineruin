from voices import (
    EMOTION_RATES,
    EMOTIONS,
    INWORLD_MARKUPS,
    VOICE_RATE_OFFSETS,
    VoiceConfig,
    apply_markup,
    get_voice_config,
)


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


# --- Inworld markup tests ---


def test_markup_keys_match_emotion_rates():
    """Every emotion in EMOTION_RATES must have a markup entry (even if empty)."""
    assert set(INWORLD_MARKUPS.keys()) == set(EMOTION_RATES.keys())


def test_markup_values_are_valid_inworld_tags():
    valid_tags = {
        "",
        "[happy]",
        "[sad]",
        "[angry]",
        "[surprised]",
        "[fearful]",
        "[disgusted]",
        "[laughing]",
        "[whispering]",
    }
    for emotion, tag in INWORLD_MARKUPS.items():
        assert tag in valid_tags, f"Emotion {emotion!r} has invalid markup {tag!r}"


def test_voice_config_includes_markup():
    cfg = get_voice_config("DM_NARRATOR", "angry")
    assert cfg.inworld_markup == "[angry]"


def test_voice_config_no_markup_for_neutral():
    cfg = get_voice_config("DM_NARRATOR", "neutral")
    assert cfg.inworld_markup == ""


def test_voice_config_no_markup_for_unknown_emotion():
    cfg = get_voice_config("DM_NARRATOR", "nonexistent")
    assert cfg.inworld_markup == ""


def test_apply_markup_prepends_tag():
    assert apply_markup("Hello world", "[sad]") == "[sad] Hello world"


def test_apply_markup_empty_passthrough():
    assert apply_markup("Hello world", "") == "Hello world"
