import json
import re
from pathlib import Path
from unittest.mock import patch

import voices
from voices import (
    EMOTION_RATES,
    EMOTIONS,
    INWORLD_MARKUPS,
    ROLE_VOICE_KEYS,
    VOICE_ENV_VARS,
    VOICE_RATE_OFFSETS,
    VOICES,
    VoiceConfig,
    apply_markup,
    get_voice_config,
)

_ROOT = Path(__file__).resolve().parents[3]


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


# --- Per-role townsfolk voices (story-014) ---


def test_role_voice_keys_mirror_the_archetype_catalog():
    """voices.py's literal role-id tuple cannot drift from content/role_archetypes.json.

    VOICES is built from os.getenv at IMPORT time; the archetype catalog is DB-loaded at
    STARTUP, so there is no import-time path between them and the ids are duplicated. Keys
    only, never values: the fast lane's env differs between CI (all empty) and a dev
    checkout (.env auto-loaded through bun run).
    """
    raw = json.loads((_ROOT / "content" / "role_archetypes.json").read_text())
    assert set(ROLE_VOICE_KEYS) == {f"ROLE_{e['id'].upper()}" for e in raw}
    assert set(ROLE_VOICE_KEYS) <= set(VOICES)


def test_empty_registered_value_falls_back_to_the_narrator():
    """The deliberate fallback for the 13 legitimately-empty keys (COMPANION_SABLE among them).

    patch.dict mutates the same dict object get_voice_config reads at call time; patch()
    would rebind the name and the lookup would not see it. Never read the AMBIENT registry:
    bun run auto-loads .env locally, while CI sets no INWORLD_VOICE_* at all.
    """
    with patch.dict(voices.VOICES, {"DM_NARRATOR": "Clive", "ROLE_GUARD": ""}, clear=True):
        assert get_voice_config("ROLE_GUARD").voice == "Clive"


def test_two_distinct_configured_values_resolve_distinctly():
    """So the fallback above is not masking a lookup that always returns the narrator."""
    with patch.dict(voices.VOICES, {"DM_NARRATOR": "Clive", "ROLE_GUARD": "Oliver"}, clear=True):
        assert get_voice_config("ROLE_GUARD").voice == "Oliver"
        assert get_voice_config("DM_NARRATOR").voice == "Clive"


def _env_example_voice_assignments() -> dict[str, str]:
    matches = (
        re.match(r"^INWORLD_VOICE_([A-Z_]+)=(.*)$", line.strip())
        for line in (_ROOT / ".env.example").read_text().splitlines()
    )
    return {m.group(1): m.group(2) for m in matches if m}


# Sable is non-verbal; voices.py registers her with an empty default deliberately, so the
# agent reads INWORLD_VOICE_SABLE while .env.example assigns nothing to it. A SECOND deliberate
# omission has to be argued for in the diff rather than absorbed by a count.
_UNSET_BY_DESIGN = frozenset({"INWORLD_VOICE_SABLE"})


class TestEnvExample:
    """.env.example is what scripts/init-worktree.sh generates every fresh worktree's .env from.

    A role voice missing here means a fresh checkout cannot boot the agent at all
    (agent.validate_env raises), so the assignment is part of the contract, not a convenience.
    """

    _ASSIGNMENTS = _env_example_voice_assignments()

    def test_every_role_voice_is_assigned_in_env_example(self):
        for key in ROLE_VOICE_KEYS:
            assert self._ASSIGNMENTS.get(key), f"INWORLD_VOICE_{key} is unassigned in .env.example"

    def test_every_assigned_inworld_voice_is_distinct(self):
        """Across EVERY assignment, not just the role block.

        Checking distinctness within the new block alone would let a role be handed Clive
        (the DM narrator) or Blake (COMPANION_KAEL) — two characters sounding identical.
        """
        values = list(self._ASSIGNMENTS.values())
        assert len(values) == len(set(values))

    def test_env_example_covers_exactly_the_names_voices_py_reads(self):
        """Set equality, not cardinality: .env.example's 50 entries and voices.py's 51 names
        differ by exactly SABLE, so a count check is green by coincidence and certifies nothing
        about WHICH entry backs which key — the whole point of the guard.

        Two directed assertions, because they fail for different reasons: an unassigned name
        the agent reads means a fresh worktree cannot boot (validate_env raises), while an
        orphan entry nothing reads is a stale line.
        """
        declared = {f"INWORLD_VOICE_{k}" for k in self._ASSIGNMENTS}
        read = set(VOICE_ENV_VARS.values())
        assert read - declared == _UNSET_BY_DESIGN, "names voices.py reads that .env.example does not assign"
        assert declared - read == set(), "entries in .env.example that nothing reads"
