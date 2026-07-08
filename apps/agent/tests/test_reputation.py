"""Tests for the pure reputation_shift resolver (story-002, M23).

Mirrors test coverage of social_resolution.disposition_shift: a named-event -> fixed
integer delta table, fail-loud on an unknown event. The DM tool + the quest / combat /
de-escalation triggers all route their magnitude through this one resolver, so the
event->delta contract is pinned here.
"""

import pytest

from reputation import REPUTATION_EVENTS, reputation_shift


@pytest.mark.parametrize(
    "event_type,expected",
    [
        ("completed_faction_quest", 5),
        ("aided_faction", 2),
        ("deescalated_faction", 3),
        ("attacked_faction", -2),
        ("killed_faction_member", -3),
        ("betrayed_faction", -5),
    ],
)
def test_named_event_returns_fixed_delta(event_type, expected):
    assert reputation_shift(event_type) == expected


def test_unknown_event_fails_loud():
    with pytest.raises(ValueError, match="unknown reputation event"):
        reputation_shift("smiled_politely")


def test_gains_are_positive_penalties_negative():
    # Contract: positive events raise standing, negative events lower it — no zero-delta
    # events (a zero-delta event would be a silent no-op the DM couldn't tell apart).
    for event, delta in REPUTATION_EVENTS.items():
        assert delta != 0, f"{event} has a zero delta"
    assert reputation_shift("completed_faction_quest") > 0
    assert reputation_shift("killed_faction_member") < 0


def test_resolver_reads_the_table_verbatim():
    for event, delta in REPUTATION_EVENTS.items():
        assert reputation_shift(event) == delta
