"""Tests for god whisper profile data."""

from unittest.mock import patch

import pytest

from _gods_content import load_gods
from god_whisper_data import (
    FAVOR_WHISPER_COOLDOWN,
    FAVOR_WHISPER_THRESHOLD,
    GOD_WHISPER_PROFILES,
    _load_profiles,
    get_god_profile,
    should_trigger_whisper,
)


class TestGodWhisperProfiles:
    def test_all_ten_gods_have_profiles(self):
        expected = {
            "kaelen",
            "syrath",
            "veythar",
            "mortaen",
            "thyra",
            "aelora",
            "valdris",
            "nythera",
            "orenthel",
            "zhael",
        }
        assert set(GOD_WHISPER_PROFILES.keys()) == expected

    def test_real_roster_has_authored_displeasure_for_every_god(self):
        entries = load_gods()
        assert entries
        assert set(GOD_WHISPER_PROFILES) == {entry["god_id"] for entry in entries}
        assert len(entries) == 10
        for entry in entries:
            prompt = entry["whisper_profile"]["displeasure_prompt"]
            assert prompt.strip(), entry["god_id"]
            assert sum(prompt.count(mark) for mark in ".!?") <= 2, entry["god_id"]
            assert GOD_WHISPER_PROFILES[entry["god_id"]].displeasure_prompt == prompt

    @pytest.mark.parametrize("value", [None, "  "])
    def test_missing_or_blank_displeasure_raises_at_load(self, value):
        entry = {**load_gods()[0], "whisper_profile": {**load_gods()[0]["whisper_profile"]}}
        if value is None:
            del entry["whisper_profile"]["displeasure_prompt"]
        else:
            entry["whisper_profile"]["displeasure_prompt"] = value
        with patch("god_whisper_data.load_gods", return_value=[entry]):
            with pytest.raises((KeyError, ValueError)):
                _load_profiles()

    def test_all_profiles_have_required_fields(self):
        for deity_id, profile in GOD_WHISPER_PROFILES.items():
            assert profile.deity_id == deity_id
            assert profile.display_name, f"{deity_id} missing display_name"
            assert "," in profile.display_name, f"{deity_id} display_name should contain epithet"
            assert profile.voice_character.startswith("GOD_")
            assert profile.voice_emotion == "divine"
            assert len(profile.speaking_style) > 0
            assert profile.stinger_sound == "god_whisper_stinger"
            assert len(profile.personality_prompt) > 20

    def test_get_god_profile_returns_known(self):
        profile = get_god_profile("kaelen")
        assert profile.deity_id == "kaelen"
        assert profile.voice_character == "GOD_KAELEN"

    def test_get_god_profile_returns_default_for_none(self):
        profile = get_god_profile("none")
        assert profile.deity_id == "unknown"
        assert profile.voice_character == "DM_NARRATOR"

    def test_get_god_profile_returns_default_for_unknown(self):
        profile = get_god_profile("nonexistent_god")
        assert profile.deity_id == "unknown"

    def test_favor_constants(self):
        assert FAVOR_WHISPER_THRESHOLD == 25
        assert FAVOR_WHISPER_COOLDOWN == 25


class TestShouldTriggerWhisper:
    def test_triggers_at_threshold(self):
        assert should_trigger_whisper(25, 0) is True

    def test_no_trigger_below_threshold(self):
        assert should_trigger_whisper(20, 0) is False

    def test_no_trigger_within_cooldown(self):
        assert should_trigger_whisper(40, 25) is False

    def test_triggers_after_cooldown(self):
        assert should_trigger_whisper(50, 25) is True
