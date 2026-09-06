"""Content coverage for the role-aware narration cadence woven into COMBAT_PROMPT (M4.7, story-004).

The combat system prompt must carry per-role narration cadence so the DM voices a throwaway
Minion differently from a climactic Boss. This is additive to the existing Beat-3 dramatic-pause
guidance — these tests pin that the three role cadences (Minion / Elite / Boss) survive future
prompt edits. Mirrors the prompt-content assertion style of tests/test_prompts.py.
"""

from combat_prompts import COMBAT_PROMPT
from system_prompts import COMBAT_SYSTEM_PROMPT


def test_combat_prompt_names_the_three_role_cadences():
    # Each derivable narration role is called out by name so the cadence guidance is discoverable.
    assert "Minion" in COMBAT_PROMPT
    assert "Elite" in COMBAT_PROMPT
    assert "Boss" in COMBAT_PROMPT


def test_minion_cadence_is_quick_and_dismissive():
    lowered = COMBAT_PROMPT.lower()
    assert "dismissive" in lowered
    assert "one sentence" in lowered or "single sentence" in lowered


def test_elite_cadence_is_methodical_and_weighty():
    lowered = COMBAT_PROMPT.lower()
    assert "methodical" in lowered
    assert "weight" in lowered  # matches "weighty" / "weight"


def test_boss_cadence_is_climactic_with_the_dramatic_pause():
    lowered = COMBAT_PROMPT.lower()
    assert "climactic" in lowered
    # The Boss earns the full dramatic pause already described in Beat 3.
    assert "dramatic pause" in lowered or "full pause" in lowered


def test_role_cadence_reaches_the_assembled_system_prompt():
    # COMBAT_PROMPT is embedded in COMBAT_SYSTEM_PROMPT, so the cadence ships to the agent.
    assert "Minion" in COMBAT_SYSTEM_PROMPT
    assert "climactic" in COMBAT_SYSTEM_PROMPT.lower()


def test_combat_prompt_instructs_buff_narration():
    # M4.8 story-006 (assumption b99c818fa7c2): a landed beneficial condition must be VOICED, not
    # left silently on state. The DM is the beat consumer of the packet's condition_applied /
    # condition_targets, so the Beat-3 guidance must name those keys and the buff to narrate.
    lowered = COMBAT_PROMPT.lower()
    assert "condition_targets" in lowered or "condition_applied" in lowered
    assert "blessed" in lowered or "inspired" in lowered or "buff" in lowered or "boon" in lowered


def test_buff_narration_reaches_the_assembled_system_prompt():
    lowered = COMBAT_SYSTEM_PROMPT.lower()
    assert "condition_targets" in lowered or "condition_applied" in lowered


def test_combat_prompt_pins_no_single_companion_voice_tag():
    """One of the four companions is assigned per archetype; COMBAT_PROMPT is a single cached
    constant, so a hardcoded tag in its companion instructions voices all four as that one.
    (VOICE_STYLE_PROMPT's even enumeration of the AUTHORED voice registry is not a pin.)"""
    for tag in ("COMPANION_KAEL", "COMPANION_LIRA", "COMPANION_TAM", "COMPANION_SABLE"):
        assert tag not in COMBAT_PROMPT, f"{tag} pinned in the shared combat prompt"
