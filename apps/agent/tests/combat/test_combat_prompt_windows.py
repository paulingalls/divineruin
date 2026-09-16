"""Beat-3 window guidance in COMBAT_PROMPT: a pause nothing can answer is not a hold.

game_mechanics_combat.md, Beat 3: the DM pauses for a reaction only when one is available, and with
none the narration flows on. At an open window, next.waiting_on.reactions is the producer of
"available", so the prompt must tell the DM that an empty list means advance in the same turn and
never ask the player to react; only a listed reaction earns the STOP.
"""

from combat_prompts import COMBAT_PROMPT
from system_prompts import COMBAT_SYSTEM_PROMPT


def _window_guidance(prompt: str) -> str:
    start = prompt.index("next.waiting_on.reactions")
    return prompt[start : prompt.index("When you close a window", start)]


def test_an_empty_reactions_list_tells_the_dm_to_advance_without_waiting():
    guidance = _window_guidance(COMBAT_PROMPT).lower()
    assert "empty" in guidance
    assert "resolve_phase again in the same turn" in guidance


def test_the_advance_rule_reaches_the_assembled_system_prompt():
    assert "resolve_phase again in the same turn" in COMBAT_SYSTEM_PROMPT.lower()
