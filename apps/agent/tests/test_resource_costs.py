"""Unit tests for resource_costs.gate_pool — the shared Focus/Stamina pool gate
extracted from ability_tools, veil_ward_tools, and spell_casting._gate_spell."""

import pytest
from livekit.agents.llm import ToolError

from resource_costs import gate_pool


def _player(**pools):
    """A player dict carrying the given pools, e.g. _player(focus={"current": 3})."""
    return {"player_id": "p1", **pools}


class TestGatePool:
    def test_zero_cost_returns_none_and_never_raises(self):
        # A cantrip / free action: no pool needed, no deduction.
        assert gate_pool(_player(), "focus", 0, label="Cantrip") is None
        # Even a missing/empty pool is fine when nothing is spent.
        assert gate_pool({}, "stamina", 0, label="Stretch") is None

    def test_sufficient_pool_returns_post_deduct_value(self):
        assert gate_pool(_player(focus={"current": 5}), "focus", 2, label="Bolt") == 3
        assert gate_pool(_player(stamina={"current": 4}), "stamina", 4, label="Charge") == 0

    def test_missing_pool_raises_fail_loud(self):
        with pytest.raises(ToolError) as exc:
            gate_pool(_player(), "focus", 1, label="Bolt")
        assert str(exc.value) == "Bolt costs Focus but you have no Focus pool."

    def test_empty_pool_dict_is_treated_as_no_pool(self):
        # `player.get("stamina")` returning {} (no "current" key) must read as "no pool".
        with pytest.raises(ToolError) as exc:
            gate_pool(_player(stamina={}), "stamina", 1, label="Heave")
        assert str(exc.value) == "Heave costs Stamina but you have no Stamina pool."

    def test_insufficient_pool_raises_with_costs_and_current(self):
        with pytest.raises(ToolError) as exc:
            gate_pool(_player(focus={"current": 1}), "focus", 3, label="Nova")
        assert str(exc.value) == "Not enough Focus for Nova: costs 3, you have 1."

    def test_no_pool_message_sentence_cases_a_lowercase_label(self):
        # Veil Ward passes label="a Veil Ward" (mid-sentence shape). The no-pool
        # message is sentence-initial, so it must read "A Veil Ward ...".
        with pytest.raises(ToolError) as exc:
            gate_pool(_player(), "focus", 1, label="a Veil Ward")
        assert str(exc.value) == "A Veil Ward costs Focus but you have no Focus pool."

    def test_insufficient_message_keeps_label_verbatim_mid_sentence(self):
        # The same lowercase label stays lowercase mid-sentence in "Not enough ...".
        with pytest.raises(ToolError) as exc:
            gate_pool(_player(focus={"current": 0}), "focus", 1, label="a Veil Ward")
        assert str(exc.value) == "Not enough Focus for a Veil Ward: costs 1, you have 0."

    def test_pool_name_capitalized_in_messages(self):
        # The Stamina path uses the same capitalized title as Focus.
        with pytest.raises(ToolError) as exc:
            gate_pool(_player(stamina={"current": 0}), "stamina", 2, label="Sprint")
        assert str(exc.value) == "Not enough Stamina for Sprint: costs 2, you have 0."
