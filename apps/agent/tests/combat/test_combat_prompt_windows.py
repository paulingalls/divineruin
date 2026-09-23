"""Beat-3 window guidance names the reactions offered at each pause."""

from combat_prompts import COMBAT_PROMPT
from system_prompts import COMBAT_SYSTEM_PROMPT


def _window_guidance(prompt: str) -> str:
    start = prompt.index("next.waiting_on.reactions")
    return prompt[start : prompt.index("When you close a window", start)]


def test_every_window_guides_the_dm_to_a_listed_reaction():
    guidance = _window_guidance(COMBAT_PROMPT).lower()
    assert "lists at least one reaction" in guidance
    assert "exactly as listed" in guidance


def test_the_offer_rule_reaches_the_assembled_system_prompt():
    assert "lists at least one reaction" in COMBAT_SYSTEM_PROMPT.lower()
