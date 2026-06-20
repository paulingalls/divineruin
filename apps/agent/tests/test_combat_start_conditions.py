"""M4.4 story-005 — combat-START condition load (AC1), iron-constitution cap (AC3), E2E (AC4).

Persistent conditions stored out of combat (players.data.conditions) must be re-imported onto the
player CombatParticipant at combat start so they affect THIS fight's rolls, with Exhausted stacks
clamped to the iron-constitution cap at the load boundary (the in-scope apply site until a
forced-march/travel producer ships).
"""

import conditions
import rules_engine


class TestCapExhaustion:
    """cap_exhaustion clamps the exhausted entry's stacks to a supplied cap; pure, no-op otherwise."""

    def test_clamps_stacks_above_cap(self):
        conds = [{"type": "exhausted", "duration": None, "source": "march", "stacks": 5}]
        out = conditions.cap_exhaustion(conds, 3)
        assert out[0]["stacks"] == 3

    def test_leaves_stacks_at_or_below_cap(self):
        conds = [{"type": "exhausted", "stacks": 2}]
        assert conditions.cap_exhaustion(conds, 3)[0]["stacks"] == 2

    def test_noop_when_no_exhausted(self):
        conds = [{"type": "wounded", "stacks": 1}]
        assert conditions.cap_exhaustion(conds, 3) == conds

    def test_does_not_mutate_input(self):
        conds = [{"type": "exhausted", "stacks": 5}]
        conditions.cap_exhaustion(conds, 3)
        assert conds[0]["stacks"] == 5  # original untouched

    def test_other_conditions_pass_through(self):
        conds = [{"type": "exhausted", "stacks": 5}, {"type": "wounded", "stacks": 1}]
        out = conditions.cap_exhaustion(conds, 3)
        assert out[1] == {"type": "wounded", "stacks": 1}


class TestExhaustionStackCap:
    """exhaustion_stack_cap gives has_iron_constitution a production caller (AC3)."""

    def test_iron_constitution_caps_at_three(self):
        assert rules_engine.exhaustion_stack_cap({"skill_tiers": {"endurance": "master"}}) == 3

    def test_default_caps_at_five(self):
        assert rules_engine.exhaustion_stack_cap({"skill_tiers": {"endurance": "expert"}}) == 5
        assert rules_engine.exhaustion_stack_cap({}) == 5
