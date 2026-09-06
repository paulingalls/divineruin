"""The pure guards the M29 real-LLM combat scenarios assert through (story-022).

Split from ``tests/acceptance/test_m29_combat_reactions.py`` so each has one job: that module
drives a live Haiku session, this one holds the assertions it leans on — which are pure, and whose
own fault injection therefore belongs in the fast lane (``tests/test_m29_guards.py``) rather than
behind an API key. A guard that cannot red against its target defect certifies (constraint 1).
"""

from __future__ import annotations

import logging

from pydantic import TypeAdapter

from declaration_payloads import DeclPayload

# livekit's own words at agent_activity.py:3076, matched against its emission rather than modelled.
TRUNCATION_WARNING = "maximum number of function calls steps reached"

# The REAL discriminated union combat_turn.declare_phase is compiled from, so "correct kind, no
# missing required field" is checked by the type itself, not by a hand-written field list.
DECLARATIONS = TypeAdapter(list[DeclPayload])


class _WarningSink(logging.Handler):
    """Collects livekit's own WARNING records so the truncation signal is read, never modelled."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def capture_livekit_warnings(stack) -> list[str]:
    """Attach a WARNING sink to the ``livekit.agents`` logger for the caller's ExitStack scope."""
    sink = _WarningSink()
    lk = logging.getLogger("livekit.agents")
    lk.addHandler(sink)
    stack.callback(lk.removeHandler, sink)
    prior = lk.level
    lk.setLevel(logging.WARNING)
    stack.callback(lk.setLevel, prior)
    return sink.messages


def assert_within_ceiling(handles: list, warnings: list[str], *, max_tool_steps: int) -> None:
    """No turn chained past what ``max_tool_steps`` actually permits, and none was regenerated.

    livekit permits ``max_tool_steps + 1`` consecutive steps (agent_activity.py:3073) and, on
    reaching the cap, does not raise: it logs and regenerates with ``tool_choice="none"``, so a
    dropped tool call reaches the player as a plausible sentence. Both arms read the STEP COUNT and
    the vendor's own log line — never the narration, which says nothing either way.
    """
    assert handles, "no speech handle was created — the run never reached the LLM"
    permitted = max_tool_steps + 1
    steps = max(h.num_steps for h in handles)
    assert steps <= permitted, f"a turn chained {steps} steps; {permitted} are permitted"
    assert not [w for w in warnings if TRUNCATION_WARNING in w], (
        f"a reply was regenerated with tool_choice='none' — a tool call was silently dropped: {warnings}"
    )


def assert_halved(hp_before: int, full: int, participant_hp: int, db_hp: int) -> None:
    """The halved figure — not the full one — is what reached the player's HP on both sides."""
    halved = full // 2
    # Nonzero AND distinct: a 1-damage blow halves to 0, which is indistinguishable from a miss —
    # the exact vacuity the forced damage die exists to prevent (constraint 1).
    assert 0 < halved != full, f"halving is unobservable at {full} damage"
    assert participant_hp != hp_before - full, "the full blow landed — the reaction changed nothing"
    assert participant_hp == hp_before - halved, (
        f"hp_current {participant_hp} is neither {hp_before} - {halved} (halved) nor "
        f"{hp_before} - {full} (full) — something else moved the player's HP"
    )
    assert db_hp == participant_hp, f"players.data->hp->current is {db_hp}, the participant is {participant_hp}"
