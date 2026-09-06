"""Which message of a turn the judge reads (sprint-048 land, note 020c90c6's sibling).

Pure, so its falsifiers live in the fast lane (``tests/test_judged_turn.py``) rather than behind
an API key — the split ``_m29_guards.py`` takes, for the same reason: this selection has been
wrong twice, and both times it was a real-LLM run that paid to discover it.
"""

from __future__ import annotations


def last_assistant_message_index(events: list) -> int:
    """Index of the turn's last assistant MESSAGE, never its last EVENT.

    Turn shape is not something the DM owes us: it narrates the outcome and then calls the tool
    about as often as the reverse, so the final event is a ``FunctionCallOutputEvent`` as often as
    a message, and ``expect[-1]`` died with "Expected ChatMessageEvent" over narration that
    satisfied the intent perfectly (observed at the sprint-048 land: narration at event 0,
    ``resolve_activity`` at 1). Returns an index into the SAME list ``RunResult.expect`` indexes.

    Raises rather than returning a sentinel: a turn that narrated nothing is a failure to report,
    and a caller that tested the result for truth would mistake the index 0 this very defect
    produces for "nothing found".
    """
    for i in range(len(events) - 1, -1, -1):
        event = events[i]
        if event.type == "message" and event.item.role == "assistant":
            return i
    raise AssertionError(f"turn emitted no assistant message to judge: {events}")
