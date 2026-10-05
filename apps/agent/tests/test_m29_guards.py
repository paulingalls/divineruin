"""Fault injection for the M29 acceptance guards (story-022): each reds against its own target.

The guards live in ``tests/acceptance/_m29_guards.py`` but are pure, so their falsifiers run HERE —
in the fast lane, on every push, rather than behind an API key in the tier they were written for.
A green that comes from an assertion which cannot fail is worse than no assertion (constraint 1).
"""

from __future__ import annotations

import contextlib
import inspect

import pytest
from acceptance._m29_guards import (
    DECLARATIONS,
    TRUNCATION_WARNING,
    capture_livekit_warnings,
)
from livekit.agents.log import logger as livekit_logger
from livekit.agents.voice import agent_activity
from pydantic import ValidationError

_GOOD_DECL = {"kind": "attack", "actor_id": "m29_rogue", "action": "Longsword", "target_id": "mawling_1", "rider": ""}


def test_the_declaration_union_rejects_a_malformed_variant():
    """AC1 leans on this validator, so it reds against the two defects the AC names by hand."""
    DECLARATIONS.validate_python([_GOOD_DECL])
    for missing in ("kind", "target_id"):
        with pytest.raises(ValidationError):
            DECLARATIONS.validate_python([{k: v for k, v in _GOOD_DECL.items() if k != missing}])


def test_the_warning_sink_reads_livekits_own_logger_and_livekits_own_words():
    """The truncation arm's only SILENT failure mode, moved off the API key.

    If the logger name drifts or livekit rewords the line, `warnings` stays empty forever and
    the arm certifies instead of checking — and nothing else in this lane would say so: the
    test above hands `assert_within_ceiling` a list it built itself. Both halves are read off
    the vendor rather than modelled (constraint 9): the logger is livekit's own object, and the
    constant is matched against the module that emits it.
    """
    assert TRUNCATION_WARNING in inspect.getsource(agent_activity), (
        "livekit no longer logs these words — the truncation arm now matches nothing"
    )
    with contextlib.ExitStack() as stack:
        messages = capture_livekit_warnings(stack)
        livekit_logger.warning("%s, generating final response with tool_choice='none'", TRUNCATION_WARNING)
    assert any(TRUNCATION_WARNING in m for m in messages), messages
    livekit_logger.warning("after the scope closed")
    assert len(messages) == 1, f"the sink outlived its ExitStack scope: {messages}"
