"""M4.4 story-005 — combat-START condition load (AC1), iron-constitution cap (AC3), E2E (AC4).

Persistent conditions stored out of combat (players.data.conditions) must be re-imported onto the
player CombatParticipant at combat start so they affect THIS fight's rolls, with Exhausted stacks
clamped to the iron-constitution cap at the load boundary (the in-scope apply site until a
forced-march/travel producer ships).
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import make_context

import conditions
import rules_engine
from check_resolution import resolve_skill_check
from combat_init import _start_combat_impl

_ATTRS = {
    "strength": 14,
    "dexterity": 12,
    "constitution": 13,
    "intelligence": 10,
    "wisdom": 11,
    "charisma": 8,
}

_ENCOUNTER = {
    "id": "goblin_patrol",
    "name": "Goblin Patrol",
    "difficulty": "easy",
    "enemies": [
        {"id": "goblin_1", "name": "Goblin", "level": 1, "ac": 13, "hp": 7, "attributes": _ATTRS, "action_pool": []},
    ],
}


def _player(*, stored_conditions=None, skill_tiers=None):
    """A players.data dict — conditions ride it (get_player returns the whole data dict)."""
    return {
        "player_id": "player_1",
        "name": "Kael",
        "class": "warrior",
        "level": 5,
        "attributes": dict(_ATTRS),
        "hp": {"current": 25, "max": 25},
        "ac": 14,
        "skill_tiers": skill_tiers or {},
        "conditions": stored_conditions if stored_conditions is not None else [],
    }


async def _run_start(player):
    mutations = MagicMock(save_combat_state=AsyncMock())
    queries = MagicMock(get_player=AsyncMock(return_value=player))
    content = MagicMock(
        get_encounter_template=AsyncMock(return_value=_ENCOUNTER),
        get_npc=AsyncMock(return_value=None),
    )
    ctx = make_context()
    await _start_combat_impl(
        ctx,
        encounter_id="goblin_patrol",
        encounter_description="Goblins attack.",
        mutations=mutations,
        queries=queries,
        content=content,
    )
    cs = ctx.userdata.combat_state
    assert cs is not None
    return next(p for p in cs.participants if p.type == "player")


class TestCombatStartLoad:
    """AC1: persisted conditions are loaded onto the player CombatParticipant at combat start."""

    @pytest.mark.asyncio
    async def test_persisted_exhausted_loads_onto_participant(self):
        stored = conditions.apply_condition([], "exhausted", source="forced_march")
        player_part = await _run_start(_player(stored_conditions=stored))
        types = [c["type"] for c in player_part.conditions]
        assert "exhausted" in types

    @pytest.mark.asyncio
    async def test_no_persisted_conditions_loads_empty(self):
        player_part = await _run_start(_player())
        assert player_part.conditions == []

    @pytest.mark.asyncio
    async def test_iron_constitution_clamps_loaded_exhausted_to_three(self):
        # AC3: a stored Exhausted at 5 stacks loads clamped to 3 for an Iron Constitution character.
        stored = [{"type": "exhausted", "duration": None, "source": "march", "stacks": 5}]
        iron_player = _player(stored_conditions=stored, skill_tiers={"endurance": "master"})
        player_part = await _run_start(iron_player)
        exhausted = next(c for c in player_part.conditions if c["type"] == "exhausted")
        assert exhausted["stacks"] == 3

    @pytest.mark.asyncio
    async def test_default_character_keeps_five_stacks(self):
        stored = [{"type": "exhausted", "duration": None, "source": "march", "stacks": 5}]
        player_part = await _run_start(_player(stored_conditions=stored))
        exhausted = next(c for c in player_part.conditions if c["type"] == "exhausted")
        assert exhausted["stacks"] == 5

    @pytest.mark.asyncio
    async def test_corrupt_stored_condition_raises_toolerror_not_valueerror(self):
        # A corrupt stored row surfaces as a DM-narratable ToolError (db_tool narrows on
        # JSONDecodeError, so a bare ValueError would escape and crash combat init) — matching
        # the companion-profile not-found convention in the same function.
        with pytest.raises(ToolError, match="corrupt stored conditions"):
            await _run_start(_player(stored_conditions=[{"type": "not_a_condition", "stacks": 1}]))


class TestCombatStartE2E:
    """AC4: stored Exhausted out of combat -> enter combat -> the first check carries the penalty."""

    @pytest.mark.asyncio
    async def test_loaded_exhausted_penalizes_an_in_combat_check(self):
        stored = conditions.apply_condition([], "exhausted", source="forced_march")  # 1 stack, -1
        player_part = await _run_start(_player(stored_conditions=stored))

        # The in-combat check path builds player_data from the participant's conditions
        # (combat_turn). Resolve a check both with and without the loaded conditions: the
        # Exhausted -1/stack penalty must land on the modifier.
        baseline = resolve_skill_check({"attributes": dict(_ATTRS), "level": 5}, "athletics", "moderate")
        in_combat = resolve_skill_check(
            {"attributes": dict(_ATTRS), "level": 5, "conditions": player_part.conditions},
            "athletics",
            "moderate",
        )
        assert in_combat.modifier == baseline.modifier - 1


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
