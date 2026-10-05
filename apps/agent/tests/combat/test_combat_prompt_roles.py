from combat_prompts import COMBAT_PROMPT
from system_prompts import COMBAT_SYSTEM_PROMPT


def test_combat_prompt_names_the_three_role_cadences():
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
    assert "dramatic pause" in lowered or "full pause" in lowered


def test_role_cadence_reaches_the_assembled_system_prompt():
    assert "Minion" in COMBAT_SYSTEM_PROMPT
    assert "climactic" in COMBAT_SYSTEM_PROMPT.lower()


def test_combat_prompt_instructs_buff_narration():
    lowered = COMBAT_PROMPT.lower()
    assert "condition_targets" in lowered or "condition_applied" in lowered
    assert "blessed" in lowered or "inspired" in lowered or "buff" in lowered or "boon" in lowered


def test_buff_narration_reaches_the_assembled_system_prompt():
    lowered = COMBAT_SYSTEM_PROMPT.lower()
    assert "condition_targets" in lowered or "condition_applied" in lowered


def test_combat_prompt_pins_no_single_companion_voice_tag():
    """The combat prompt is cached across archetypes, so a fixed companion tag would voice all four as one."""
    for tag in ("COMPANION_KAEL", "COMPANION_LIRA", "COMPANION_TAM", "COMPANION_SABLE"):
        assert tag not in COMBAT_PROMPT, f"{tag} pinned in the shared combat prompt"
